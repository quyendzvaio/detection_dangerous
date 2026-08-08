"""Compact thread-safe overlay state for asynchronous Layer 2 results."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, replace

import cv2
import numpy as np

from ai_engine.contracts.event_schema import (
    FallDetectedEvent,
    FallSuspectedEvent,
    PPEViolationEvent,
    RestrictedZoneEvent,
    SafetyEvent,
)
from ai_engine.pipeline.layer2_runtime import LocalTrackUpdate

PPE_LABELS = {
    "no_helmet": "NO HELMET",
    "no_glasses": "NO GLASSES",
    "no_gloves": "NO GLOVES",
    "no_vest": "NO VEST",
}

GREEN = (0, 190, 0)
YELLOW = (0, 215, 255)
ORANGE = (0, 140, 255)
RED = (0, 0, 255)
WHITE = (245, 245, 245)
DARK = (25, 25, 25)


@dataclass(frozen=True)
class TrackOverlayState:
    track_id: str
    ppe_violations: tuple[str, ...] = ()
    fall_warning: bool = False
    fall_detected: bool = False
    fall_probability: float | None = None
    zones: tuple[str, ...] = ()
    last_seen_at: float = 0.0
    updated_at: float = 0.0

    @property
    def severity(self) -> str:
        if self.fall_detected:
            return "CRITICAL"
        if self.zones or self.ppe_violations:
            return "DANGER"
        if self.fall_warning:
            return "WARNING"
        return "NORMAL"


class OverlayStateStore:
    """Bridges Layer 2 worker threads to the preview renderer."""

    def __init__(self, missing_track_ttl_s: float = 3.0) -> None:
        self.missing_track_ttl_s = float(missing_track_ttl_s)
        self._states: dict[str, TrackOverlayState] = {}
        self._lock = threading.Lock()

    def mark_seen(self, track_ids, now: float | None = None) -> None:
        now = time.time() if now is None else float(now)
        visible = set(track_ids)
        with self._lock:
            for track_id in visible:
                current = self._states.get(track_id, TrackOverlayState(track_id))
                self._states[track_id] = replace(current, last_seen_at=now)
            stale = [
                track_id
                for track_id, state in self._states.items()
                if track_id not in visible
                and now - state.last_seen_at > self.missing_track_ttl_s
            ]
            for track_id in stale:
                del self._states[track_id]

    def apply_update(self, update: LocalTrackUpdate) -> None:
        with self._lock:
            current = self._states.get(update.track_id, TrackOverlayState(update.track_id))
            if update.branch == "ppe":
                violations = tuple(
                    label
                    for field_name, label in PPE_LABELS.items()
                    if int(update.details.get(field_name, 0)) == 1
                )
                current = replace(
                    current,
                    ppe_violations=violations,
                    updated_at=update.captured_at,
                )
            elif update.branch == "fall":
                probability = update.details.get("probability")
                phase = update.details.get("phase")
                if phase in {"NORMAL", "WARNING", "CRITICAL"}:
                    warning = phase == "WARNING"
                    detected = phase == "CRITICAL"
                else:
                    warning = current.fall_warning
                    detected = current.fall_detected or bool(
                        update.details.get("detected", False)
                    )
                current = replace(
                    current,
                    fall_probability=(
                        float(probability) if probability is not None else None
                    ),
                    fall_warning=warning,
                    fall_detected=detected,
                    updated_at=update.captured_at,
                )
            self._states[update.track_id] = current

    def apply_event(self, event: SafetyEvent) -> None:
        with self._lock:
            current = self._states.get(event.track_id, TrackOverlayState(event.track_id))
            if isinstance(event, FallDetectedEvent):
                current = replace(
                    current,
                    fall_warning=False,
                    fall_detected=True,
                    fall_probability=event.confidence,
                    updated_at=event.detected_at,
                )
            elif isinstance(event, FallSuspectedEvent):
                current = replace(
                    current,
                    fall_warning=True,
                    fall_detected=False,
                    fall_probability=event.confidence,
                    updated_at=event.detected_at,
                )
            elif isinstance(event, RestrictedZoneEvent):
                zone = str(event.zone_id)
                current = replace(
                    current,
                    zones=tuple(sorted(set(current.zones) | {zone})),
                    updated_at=event.detected_at,
                )
            elif isinstance(event, PPEViolationEvent):
                labels = tuple(code.value.replace("_", " ") for code in event.violation_codes)
                current = replace(
                    current,
                    ppe_violations=labels,
                    updated_at=event.detected_at,
                )
            self._states[event.track_id] = current

    def clear_fall(self, track_id: str) -> None:
        """Hook for future recovery/operator acknowledgement control."""
        with self._lock:
            current = self._states.get(track_id)
            if current is not None:
                self._states[track_id] = replace(
                    current, fall_warning=False, fall_detected=False,
                    fall_probability=None
                )

    def clear_branch(self, branch: str) -> None:
        """Remove visible state when a per-camera analysis branch is disabled."""
        if branch not in {"fall", "ppe", "zone"}:
            raise ValueError(f"Unknown overlay branch: {branch}")
        with self._lock:
            for track_id, current in tuple(self._states.items()):
                if branch == "fall":
                    current = replace(
                        current, fall_warning=False, fall_detected=False,
                        fall_probability=None
                    )
                elif branch == "ppe":
                    current = replace(current, ppe_violations=())
                else:
                    current = replace(current, zones=())
                self._states[track_id] = current

    def snapshot(self) -> dict[str, TrackOverlayState]:
        with self._lock:
            return dict(self._states)


def _short_track_id(track_id: str) -> str:
    return f"#{track_id.rsplit('-', 1)[-1]}"


def _style(state: TrackOverlayState | None):
    if state is None:
        return GREEN, "NORMAL"
    if state.fall_detected:
        return RED, "CRITICAL FALL"
    if state.zones:
        return ORANGE, "DANGER ZONE"
    if state.ppe_violations:
        return ORANGE, f"DANGER PPE {len(state.ppe_violations)}"
    if state.fall_warning:
        return YELLOW, "WARNING FALL"
    return GREEN, "NORMAL"


def _draw_label(frame, text: str, origin: tuple[int, int], color) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale, thickness = 0.58, 2
    (width, height), baseline = cv2.getTextSize(text, font, scale, thickness)
    x, y = origin
    y = max(height + baseline + 3, y)
    cv2.rectangle(
        frame,
        (x, y - height - baseline - 4),
        (x + width + 8, y + 2),
        color,
        -1,
    )
    cv2.putText(
        frame, text, (x + 4, y - baseline), font, scale, WHITE, thickness, cv2.LINE_AA
    )


def draw_tracking_overlay(
    frame, tracked, metrics, store: OverlayStateStore, zones=()
) -> None:
    """Draw compact bboxes and a small alert panel; no pose skeleton."""
    _draw_zones(frame, zones)
    store.mark_seen((person.track_id for person in tracked.persons), tracked.captured_at)
    states = store.snapshot()

    for person in tracked.persons:
        x1, y1, x2, y2 = person.bbox_xyxy.astype(int)
        state = states.get(person.track_id)
        color, badge = _style(state)
        thickness = 4 if state is not None and state.fall_detected else 2
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, thickness)
        label = _short_track_id(person.track_id)
        if badge:
            label += f" {badge}"
        _draw_label(frame, label, (x1, y1 - 5), color)

    _draw_metrics(frame, metrics)
    _draw_alert_panel(frame, states)


def _draw_zones(frame, zones) -> None:
    height, width = frame.shape[:2]
    for zone in zones:
        polygon = np.asarray(
            [[point[0] * width, point[1] * height] for point in zone["polygon"]],
            dtype=np.int32,
        )
        if len(polygon) < 3:
            continue
        cv2.polylines(frame, [polygon], True, ORANGE, 2, cv2.LINE_AA)
        x, y = polygon[0]
        _draw_label(frame, str(zone.get("name", "ZONE"))[:24], (int(x), int(y)), ORANGE)


def _draw_metrics(frame, metrics) -> None:
    lines = (
        f"FPS {metrics.processing_fps:.1f}",
        f"Pose {metrics.pose_ms:.1f} ms",
        f"Track {metrics.tracker_ms:.1f} ms",
        f"E2E {metrics.end_to_end_ms:.1f} ms",
    )
    for index, line in enumerate(lines):
        cv2.putText(
            frame,
            line,
            (12, 27 + index * 23),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.58,
            YELLOW,
            2,
            cv2.LINE_AA,
        )


def _draw_alert_panel(frame, states: dict[str, TrackOverlayState], max_rows: int = 6) -> None:
    active = [state for state in states.values() if state.severity != "NORMAL"]
    active.sort(key=lambda item: (item.severity != "CRITICAL", item.track_id))
    if not active:
        return
    panel_width = min(390, max(250, frame.shape[1] // 3))
    x1, y1 = frame.shape[1] - panel_width - 10, 10
    rows = active[:max_rows]
    panel_height = 35 + 29 * len(rows) + (24 if len(active) > max_rows else 0)
    overlay = frame.copy()
    cv2.rectangle(
        overlay, (x1, y1), (frame.shape[1] - 10, y1 + panel_height), DARK, -1
    )
    cv2.addWeighted(overlay, 0.78, frame, 0.22, 0, frame)
    cv2.putText(
        frame,
        "ACTIVE ALERTS",
        (x1 + 10, y1 + 23),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        WHITE,
        2,
        cv2.LINE_AA,
    )
    for index, state in enumerate(rows):
        if state.fall_detected:
            score = (
                f" {state.fall_probability * 100:.1f}%"
                if state.fall_probability is not None
                else ""
            )
            text, color = f"{_short_track_id(state.track_id)} FALL{score}", RED
        elif state.zones:
            text, color = (
                f"{_short_track_id(state.track_id)} ZONE {state.zones[0]}",
                ORANGE,
            )
        else:
            detail = ", ".join(state.ppe_violations)
            text, color = f"{_short_track_id(state.track_id)} PPE: {detail}", ORANGE
        cv2.putText(
            frame,
            text[:52],
            (x1 + 10, y1 + 51 + index * 29),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            2,
            cv2.LINE_AA,
        )
    if len(active) > max_rows:
        cv2.putText(
            frame,
            f"+{len(active) - max_rows} more",
            (x1 + 10, y1 + panel_height - 7),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.48,
            WHITE,
            1,
            cv2.LINE_AA,
        )

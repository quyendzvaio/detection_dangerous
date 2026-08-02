"""Layer 2 runtime: independent bounded analysis branches per camera process."""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from ai_engine.analytics.crop_body import get_crop
from ai_engine.analytics.fall import FallConfig, FallProcessor, TritonFallDetector
from ai_engine.analytics.ppe_detection import PPEDetector
from ai_engine.analytics.zone import ZoneChecker
from ai_engine.contracts.event_schema import (
    FallDetectedEvent,
    FallTask,
    PPEViolationEvent,
    PpeTask,
    PpeViolationCode,
    RestrictedZoneEvent,
    SafetyEvent,
    TrackedFrame,
    ZoneTask,
)


@dataclass(frozen=True)
class ModelToggles:
    zone: bool = True
    fall: bool = True
    ppe: bool = False


@dataclass(frozen=True)
class CameraLayer2Config:
    camera_id: int
    camera_key: str
    models: ModelToggles = field(default_factory=ModelToggles)
    zones: tuple[dict, ...] = ()
    queue_size: int = 32
    ppe_interval_s: float = 2.0
    triton_url: str = "localhost:8001"


@dataclass(frozen=True)
class LocalTrackUpdate:
    """Latest branch state for preview only; never persisted as a safety event."""

    branch: str
    camera_id: int
    camera_key: str
    track_id: str
    captured_at: float
    details: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Layer2Metrics:
    dispatched: dict[str, int]
    dropped: dict[str, int]
    processed: dict[str, int]
    queue_depths: dict[str, int]


class DropOldestQueue:
    """Bounded realtime queue that replaces stale work with fresh work."""

    def __init__(self, maxsize: int) -> None:
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self.dropped = 0

    def put_latest(self, item: object) -> None:
        try:
            self._queue.put_nowait(item)
            return
        except queue.Full:
            pass
        try:
            self._queue.get_nowait()
            self.dropped += 1
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def get(self, timeout: float) -> object:
        return self._queue.get(timeout=timeout)

    def qsize(self) -> int:
        return self._queue.qsize()

    def clear(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return


class Layer2Control:
    """Thread-safe per-camera model switches for the active product branches."""

    _ALLOWED = frozenset({"zone", "fall", "ppe"})

    def __init__(self, initial: ModelToggles) -> None:
        self._lock = threading.Lock()
        self._models = initial

    def models(self) -> ModelToggles:
        with self._lock:
            return self._models

    def set_models(self, **changes: bool) -> ModelToggles:
        unknown = set(changes) - self._ALLOWED
        if unknown:
            raise ValueError(f"Unknown model toggles: {sorted(unknown)}")
        with self._lock:
            values = {name: getattr(self._models, name) for name in self._ALLOWED}
            values.update(changes)
            self._models = ModelToggles(**values)
            return self._models


class PPEStateStabilizer:
    """Require repeated PPE observations before changing visible/event state."""

    def __init__(self, required_observations: int = 2) -> None:
        self.required_observations = required_observations
        self._candidates: dict[str, tuple[tuple[int, int, int, int], int]] = {}
        self._stable: dict[str, tuple[int, int, int, int]] = {}

    def observe(
        self, track_id: str, state: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int] | None:
        candidate, count = self._candidates.get(track_id, (state, 0))
        count = count + 1 if candidate == state else 1
        self._candidates[track_id] = (state, count)
        current = self._stable.get(track_id)
        if count < self.required_observations and current != state:
            return None
        self._stable[track_id] = state
        return state

class Layer2Runtime:
    """Dispatcher plus one consumer thread per active branch for one camera."""

    BRANCHES = ("zone", "fall", "ppe")

    def __init__(
        self,
        config: CameraLayer2Config,
        on_event: Callable[[SafetyEvent], None] | None = None,
        on_track_update: Callable[[LocalTrackUpdate], None] | None = None,
        on_models_changed: Callable[[ModelToggles, ModelToggles], None] | None = None,
    ) -> None:
        self.config = config
        self.control = Layer2Control(config.models)
        self.on_event = on_event or (lambda event: None)
        self.on_track_update = on_track_update or (lambda update: None)
        self.on_models_changed = on_models_changed or (lambda previous, current: None)
        self._queues = {name: DropOldestQueue(config.queue_size) for name in self.BRANCHES}
        self._processed = {name: 0 for name in self.BRANCHES}
        self._dispatched = {name: 0 for name in self.BRANCHES}
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._last_ppe: dict[str, float] = {}
        self._last_ppe_state: dict[str, tuple[int, int, int, int]] = {}
        self._ppe_stabilizer = PPEStateStabilizer()
        self._zone_lock = threading.Lock()
        self._zones = config.zones
        self._zone_revision = 0
        self._branch_epoch_lock = threading.Lock()
        self._branch_epochs = {name: 0 for name in self.BRANCHES}

    def start(self) -> None:
        if self._threads:
            return
        targets = {"zone": self._run_zone, "fall": self._run_fall, "ppe": self._run_ppe}
        for branch in self.BRANCHES:
            thread = threading.Thread(
                target=targets[branch],
                name=f"l2-{self.config.camera_key}-{branch}",
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def close(self, timeout: float = 3.0) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def set_models(self, **changes: bool) -> ModelToggles:
        previous = self.control.models()
        current = self.control.set_models(**changes)
        with self._branch_epoch_lock:
            for branch in self.BRANCHES:
                if getattr(previous, branch) == getattr(current, branch):
                    continue
                self._branch_epochs[branch] += 1
                if not getattr(current, branch):
                    self._queues[branch].clear()
        if previous.ppe and not current.ppe:
            self._last_ppe.clear()
            self._last_ppe_state.clear()
        if previous != current:
            self.on_models_changed(previous, current)
        return current

    def models(self) -> ModelToggles:
        return self.control.models()

    def _branch_epoch(self, branch: str) -> int:
        with self._branch_epoch_lock:
            return self._branch_epochs[branch]

    def set_zones(self, zones: list[dict] | tuple[dict, ...]) -> None:
        with self._zone_lock:
            self._zones = tuple(zones)
            self._zone_revision += 1

    def zones(self) -> tuple[dict, ...]:
        with self._zone_lock:
            return self._zones

    def dispatch(self, tracked: TrackedFrame) -> None:
        """Fast non-blocking fan-out from Layer 1 into enabled branches."""
        models = self.control.models()
        for person in tracked.persons:
            if models.zone:
                self._put(
                    "zone",
                    ZoneTask(
                        tracked.camera_id,
                        tracked.camera_key,
                        person.track_id,
                        person.bbox_xyxy.copy(),
                        tracked.captured_at,
                        tracked.frame_width,
                        tracked.frame_height,
                    ),
                )
            if models.fall:
                self._put(
                    "fall",
                    FallTask(
                        tracked.camera_id,
                        tracked.camera_key,
                        person.track_id,
                        person.keypoints.copy(),
                        tracked.captured_at,
                    ),
                )
            if not models.ppe:
                continue
            crop, relative = self._person_crop(
                tracked.frame_bgr, person.bbox_xyxy, person.keypoints
            )
            if crop is not None and self._should_run_ppe(
                person.track_id, tracked.captured_at
            ):
                self._put(
                    "ppe",
                    PpeTask(
                        tracked.camera_id,
                        tracked.camera_key,
                        person.track_id,
                        crop,
                        relative,
                        tracked.captured_at,
                    ),
                )

    def metrics(self) -> Layer2Metrics:
        return Layer2Metrics(
            self._dispatched.copy(),
            {name: self._queues[name].dropped for name in self.BRANCHES},
            self._processed.copy(),
            {name: self._queues[name].qsize() for name in self.BRANCHES},
        )

    def _put(self, branch: str, task: object) -> None:
        self._queues[branch].put_latest(task)
        self._dispatched[branch] += 1

    def _should_run_ppe(self, track_id: str, now: float) -> bool:
        last = self._last_ppe.get(track_id)
        if last is None or now - last >= self.config.ppe_interval_s:
            self._last_ppe[track_id] = now
            return True
        return False

    @staticmethod
    def _person_crop(frame: np.ndarray, bbox: np.ndarray, keypoints: np.ndarray):
        x1, y1, x2, y2 = np.asarray(bbox, dtype=int)
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(width, x2), min(height, y2)
        if x2 <= x1 or y2 <= y1:
            return None, None
        crop = frame[y1:y2, x1:x2].copy()
        relative = np.asarray(keypoints, dtype=np.float32).copy()
        relative[:, 0] -= x1
        relative[:, 1] -= y1
        return crop, relative

    def _emit(self, event: SafetyEvent) -> None:
        try:
            self.on_event(event)
        except Exception as exc:
            print(f"[layer2:{self.config.camera_key}] event callback error: {exc}", flush=True)

    def _update(self, branch: str, track_id: str, captured_at: float, **details: object) -> None:
        try:
            self.on_track_update(
                LocalTrackUpdate(
                    branch,
                    self.config.camera_id,
                    self.config.camera_key,
                    track_id,
                    captured_at,
                    details,
                )
            )
        except Exception as exc:
            print(f"[layer2:{self.config.camera_key}] track update callback error: {exc}", flush=True)

    def _run_zone(self) -> None:
        checker = ZoneChecker()
        loaded_revision = -1
        while not self._stop.is_set():
            try:
                task: ZoneTask = self._queues["zone"].get(0.2)
            except queue.Empty:
                continue
            if not self.control.models().zone:
                continue
            with self._zone_lock:
                revision = self._zone_revision
                zones = self._zones
            if loaded_revision != revision:
                checker.set_zones(
                    [
                        {
                            **zone,
                            "polygon": [
                                [point[0] * task.frame_width, point[1] * task.frame_height]
                                for point in zone["polygon"]
                            ],
                        }
                        for zone in zones
                    ]
                )
                loaded_revision = revision
            for zone in checker.check(task.track_id, task.bbox_xyxy):
                if not self.control.models().zone:
                    break
                self._emit(
                    RestrictedZoneEvent(
                        camera_id=task.camera_id,
                        track_id=task.track_id,
                        detected_at=task.captured_at,
                        zone_id=int(zone["id"]),
                    )
                )
            self._processed["zone"] += 1

    def _run_fall(self) -> None:
        config_path = (
            Path(__file__).resolve().parents[2]
            / "weights"
            / "fall_model"
            / "inference_config.json"
        )
        processor = None
        processor_epoch = -1
        while not self._stop.is_set():
            try:
                task: FallTask = self._queues["fall"].get(0.2)
            except queue.Empty:
                continue
            epoch = self._branch_epoch("fall")
            if not self.control.models().fall:
                continue
            if processor is None or processor_epoch != epoch:
                processor = FallProcessor(
                    FallConfig.from_json(config_path),
                    TritonFallDetector(url=self.config.triton_url),
                )
                processor_epoch = epoch
            result = processor.process(task)
            if not self.control.models().fall or self._branch_epoch("fall") != epoch:
                continue
            if result.probability is not None:
                self._update(
                    "fall",
                    task.track_id,
                    task.captured_at,
                    probability=result.probability,
                    detected=result.alert_fired,
                    threshold=processor.config.threshold,
                )
            if result.alert_fired:
                self._emit(
                    FallDetectedEvent(
                        camera_id=task.camera_id,
                        track_id=task.track_id,
                        detected_at=task.captured_at,
                        confidence=float(result.probability),
                    )
                )
            self._processed["fall"] += 1

    def _run_ppe(self) -> None:
        detector = None
        processor_epoch = -1
        flag_to_code = (
            ("no_helmet", PpeViolationCode.NO_HELMET),
            ("no_glasses", PpeViolationCode.NO_GLASSES),
            ("no_gloves", PpeViolationCode.NO_GLOVES),
            ("no_vest", PpeViolationCode.NO_VEST),
        )
        while not self._stop.is_set():
            try:
                task: PpeTask = self._queues["ppe"].get(0.2)
            except queue.Empty:
                continue
            epoch = self._branch_epoch("ppe")
            if not self.control.models().ppe:
                continue
            if processor_epoch != epoch:
                self._ppe_stabilizer = PPEStateStabilizer()
                self._last_ppe_state.clear()
                processor_epoch = epoch
            try:
                detector = detector or PPEDetector()
                flags = detector.detect_violations(
                    get_crop(task.person_crop_bgr, task.relative_keypoints)
                )
                if not self.control.models().ppe or self._branch_epoch("ppe") != epoch:
                    continue
                state = tuple(int(flags[name]) for name, _ in flag_to_code)
                stable_state = self._ppe_stabilizer.observe(task.track_id, state)
                if stable_state is None:
                    self._processed["ppe"] += 1
                    continue
                stable_flags = {
                    name: bool(value)
                    for (name, _), value in zip(flag_to_code, stable_state)
                }
                self._update("ppe", task.track_id, task.captured_at, **stable_flags)
                previous = self._last_ppe_state.get(task.track_id)
                if any(stable_state):
                    if previous != stable_state:
                        codes = tuple(
                            code
                            for (_, code), enabled in zip(flag_to_code, stable_state)
                            if enabled
                        )
                        self._emit(
                            PPEViolationEvent(
                                camera_id=task.camera_id,
                                track_id=task.track_id,
                                detected_at=task.captured_at,
                                violation_codes=codes,
                            )
                        )
                    self._last_ppe_state[task.track_id] = stable_state
                else:
                    self._last_ppe_state.pop(task.track_id, None)
            except Exception as exc:
                print(f"[layer2:{self.config.camera_key}] ppe error: {exc}", flush=True)
            self._processed["ppe"] += 1

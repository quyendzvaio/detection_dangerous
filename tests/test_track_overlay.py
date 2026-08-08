"""State-machine tests for compact asynchronous track overlays."""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from ai_engine.contracts.event_schema import (
    FallDetectedEvent,
    FallSuspectedEvent,
    RestrictedZoneEvent,
)
from ai_engine.pipeline.layer2_runtime import LocalTrackUpdate
from ai_engine.visualization.track_overlay import OverlayStateStore


def update(branch, track_id="cam1-7", captured_at=1.0, **details):
    return LocalTrackUpdate(branch, 1, "cam1", track_id, captured_at, details)


def fall_event(track_id="cam1-7", detected_at=1.0, confidence=0.828):
    return FallDetectedEvent(
        camera_id=1,
        track_id=track_id,
        detected_at=detected_at,
        confidence=confidence,
    )


def test_ppe_state_stays_until_a_clean_result():
    store = OverlayStateStore()
    store.apply_update(
        update("ppe", no_helmet=1, no_glasses=0, no_gloves=0, no_vest=1)
    )
    state = store.snapshot()["cam1-7"]
    assert state.ppe_violations == ("NO HELMET", "NO VEST")
    assert state.severity == "DANGER"

    store.apply_update(
        update(
            "ppe",
            captured_at=3.0,
            no_helmet=0,
            no_glasses=0,
            no_gloves=0,
            no_vest=0,
        )
    )
    state = store.snapshot()["cam1-7"]
    assert state.ppe_violations == ()
    assert state.severity == "NORMAL"


def test_fall_is_latched_until_explicit_clear():
    store = OverlayStateStore()
    store.apply_event(fall_event())
    store.apply_update(
        update("fall", captured_at=2.0, probability=0.01, detected=False)
    )
    state = store.snapshot()["cam1-7"]
    assert state.fall_detected is True
    assert state.severity == "CRITICAL"

    store.clear_fall("cam1-7")
    assert store.snapshot()["cam1-7"].fall_detected is False


def test_zone_event_uses_zone_id():
    store = OverlayStateStore()
    store.apply_event(
        RestrictedZoneEvent(
            camera_id=1, track_id="cam1-7", detected_at=1.0, zone_id=42
        )
    )
    assert store.snapshot()["cam1-7"].zones == ("42",)


def test_disabling_each_branch_clears_only_its_overlay_state():
    store = OverlayStateStore()
    store.apply_event(fall_event())
    store.apply_event(
        RestrictedZoneEvent(
            camera_id=1, track_id="cam1-7", detected_at=1.0, zone_id=42
        )
    )
    store.apply_update(
        update("ppe", no_helmet=1, no_glasses=0, no_gloves=0, no_vest=1)
    )

    store.clear_branch("fall")
    state = store.snapshot()["cam1-7"]
    assert state.fall_detected is False
    assert state.zones == ("42",)
    assert state.ppe_violations == ("NO HELMET", "NO VEST")

    store.clear_branch("zone")
    store.clear_branch("ppe")
    state = store.snapshot()["cam1-7"]
    assert state.severity == "NORMAL"
    assert state.zones == ()
    assert state.ppe_violations == ()


def test_missing_track_prunes_latched_state():
    store = OverlayStateStore(missing_track_ttl_s=3.0)
    store.mark_seen(["cam1-7"], now=10.0)
    store.apply_event(fall_event(detected_at=10.0, confidence=0.9))
    store.mark_seen([], now=12.9)
    assert "cam1-7" in store.snapshot()
    store.mark_seen([], now=13.1)
    assert "cam1-7" not in store.snapshot()


def test_fall_overlay_transitions_warning_critical_normal():
    store = OverlayStateStore()
    store.apply_event(
        FallSuspectedEvent(
            camera_id=1, track_id="cam1-7", detected_at=1.0, confidence=0.8
        )
    )
    state = store.snapshot()["cam1-7"]
    assert state.fall_warning is True
    assert state.severity == "WARNING"

    store.apply_event(fall_event(detected_at=11.0, confidence=0.8))
    state = store.snapshot()["cam1-7"]
    assert state.fall_warning is False
    assert state.severity == "CRITICAL"

    store.apply_update(update("fall", captured_at=13.0, phase="NORMAL"))
    state = store.snapshot()["cam1-7"]

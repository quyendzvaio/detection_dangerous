"""Tests for the stable Layer 2 -> backend event contract."""
from dataclasses import FrozenInstanceError

from ai_engine.contracts.event_schema import (
    CameraStatus,
    CameraStatusEvent,
    EvidenceStatus,
    FallDetectedEvent,
    FallSuspectedEvent,
    PPEViolationEvent,
    PpeViolationCode,
    RestrictedZoneEvent,
)

NOW = 1_700_000_000.125


def test_ppe_payload_has_only_common_fields_and_codes():
    event = PPEViolationEvent(
        camera_id=1,
        track_id="cam1-7",
        detected_at=NOW,
        violation_codes=(PpeViolationCode.NO_HELMET, PpeViolationCode.NO_VEST),
    )
    payload = event.to_backend_payload()
    assert payload["violation_type"] == "PPE_VIOLATION"
    assert payload["severity_level"] == "DANGER"
    assert payload["violation_codes"] == ["NO_HELMET", "NO_VEST"]
    assert payload["evidence_status"] == EvidenceStatus.PROCESSING.value
    assert "sequence_id" not in payload
    assert "schema_version" not in payload
    assert "ai_metadata_json" not in payload
    assert "person_id" not in payload


def test_fall_payload_contains_confidence_only_as_specific_data():
    event = FallDetectedEvent(
        camera_id=2, track_id="cam2-9", detected_at=NOW, confidence=0.828
    )
    payload = event.to_backend_payload()
    assert payload["violation_type"] == "FALL_DETECTED"
    assert payload["severity_level"] == "CRITICAL"
    assert payload["confidence"] == 0.828
    assert "model_name" not in payload
    assert "model_version" not in payload


def test_fall_suspected_contract_is_kept():
    event = FallSuspectedEvent(
        camera_id=2, track_id="cam2-9", detected_at=NOW, confidence=0.41
    )
    assert event.to_backend_payload()["violation_type"] == "FALL_SUSPECTED"


def test_zone_payload_uses_id_without_name():
    payload = RestrictedZoneEvent(
        camera_id=3, track_id="cam3-1", detected_at=NOW, zone_id=12
    ).to_backend_payload()
    assert payload["zone_id"] == 12
    assert "zone_name" not in payload


def test_camera_status_is_not_a_safety_violation():
    payload = CameraStatusEvent(
        camera_id=3,
        status=CameraStatus.OFFLINE,
        observed_at=NOW,
        reason="read timeout",
    ).to_backend_payload()
    assert payload["event_category"] == "CAMERA_STATUS"
    assert "violation_type" not in payload


def test_events_are_immutable_and_validate_confidence():
    event = FallDetectedEvent(
        camera_id=1, track_id="cam1-1", detected_at=NOW, confidence=0.5
    )
    try:
        event.confidence = 0.7
        raise AssertionError("event mutation should fail")
    except FrozenInstanceError:
        pass
    try:
        FallDetectedEvent(
            camera_id=1, track_id="cam1-1", detected_at=NOW, confidence=1.1
        )
        raise AssertionError("invalid confidence should fail")
    except ValueError:
        pass

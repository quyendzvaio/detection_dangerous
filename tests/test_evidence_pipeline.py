import time
from pathlib import Path

import cv2
import numpy as np

from ai_engine.contracts.event_schema import (
    FallDetectedEvent,
    PPEViolationEvent,
    PpeViolationCode,
    TrackObservation,
    TrackedFrame,
)
from ai_engine.evidence import (
    EvidenceCapture,
    EvidenceFile,
    EvidenceJob,
    EvidenceUploader,
)


def tracked_frame(captured_at: float) -> TrackedFrame:
    frame = np.full((120, 160, 3), 180, dtype=np.uint8)
    person = TrackObservation(
        track_id="cam1-7",
        bbox_xyxy=np.array([30, 20, 100, 110], dtype=np.float32),
        keypoints=np.zeros((17, 3), dtype=np.float32),
        detection_confidence=0.9,
    )
    return TrackedFrame(
        camera_id=1,
        camera_key="cam1",
        captured_at=captured_at,
        frame_bgr=frame,
        frame_width=160,
        frame_height=120,
        persons=(person,),
        pose_model="yolo_pose",
        pose_model_version="1",
    )


def wait_for(predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not reached")


def test_ppe_capture_creates_annotated_jpeg_without_blocking(tmp_path):
    jobs = []
    capture = EvidenceCapture("cam1", tmp_path, jobs.append, sample_fps=8)
    capture.observe(tracked_frame(1000.0))
    wait_for(lambda: capture.stats()["ring_frames"] == 1)
    event = PPEViolationEvent(
        camera_id=1,
        track_id="cam1-7",
        detected_at=1000.0,
        violation_codes=(PpeViolationCode.NO_HELMET,),
    )
    capture.submit_event(event)
    wait_for(lambda: len(jobs) == 1)
    capture.close()
    assert [item.kind for item in jobs[0].files] == ["IMAGE"]
    image_path = jobs[0].files[0].path
    image = cv2.imread(str(image_path))
    assert image is not None
    assert image.shape[:2] == (120, 160)


def test_fall_capture_creates_thumbnail_and_pre_post_mp4(tmp_path):
    jobs = []
    capture = EvidenceCapture(
        "cam1",
        tmp_path,
        jobs.append,
        sample_fps=4,
        pre_seconds=0.5,
        post_seconds=0.5,
    )
    for timestamp in (1000.0, 1000.25, 1000.5):
        capture.observe(tracked_frame(timestamp))
        time.sleep(0.04)
    wait_for(lambda: capture.stats()["ring_frames"] >= 2)
    event = FallDetectedEvent(
        camera_id=1,
        track_id="cam1-7",
        detected_at=1000.5,
        confidence=0.95,
    )
    capture.submit_event(event)
    for timestamp in (1000.75, 1001.0):
        capture.observe(tracked_frame(timestamp))
        time.sleep(0.05)
    wait_for(lambda: len(jobs) == 1, timeout=5)
    capture.close()
    files = {item.kind: item.path for item in jobs[0].files}
    assert set(files) == {"IMAGE", "VIDEO"}
    assert files["IMAGE"].stat().st_size > 0
    assert files["VIDEO"].stat().st_size > 0


class FakeResponse:
    def __init__(self, status_code, payload=None, text="", headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeUploadSession:
    def __init__(self):
        self.posts = []
        self.puts = []

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        if url.endswith("/presign"):
            spec = kwargs["json"]["objects"][0]
            return FakeResponse(
                200,
                {
                    "event_id": "33333333-3333-4333-8333-333333333333",
                    "uploads": [
                        {
                            "evidence_id": 9,
                            "kind": spec["kind"],
                            "object_key": "evidence/test/image.jpg",
                            "upload_url": "https://azure.example/signed",
                            "upload_headers": {"x-ms-blob-type": "BlockBlob"},
                            "content_type": spec["content_type"],
                            "expires_in_seconds": 900,
                        }
                    ],
                },
            )
        return FakeResponse(200, {"evidence_status": "READY"})

    def put(self, url, **kwargs):
        self.puts.append((url, kwargs["headers"], kwargs["data"].read()))
        return FakeResponse(200, headers={"ETag": '"etag-1"'})


def test_uploader_uses_signed_put_and_removes_spool_after_complete(tmp_path):
    event_id = "33333333-3333-4333-8333-333333333333"
    image = tmp_path / "image.jpg"
    image.write_bytes(b"jpeg-bytes")
    session = FakeUploadSession()
    uploader = EvidenceUploader(
        "http://backend/api/v1/internal/events",
        "secret",
        tmp_path,
        session=session,
        retries=0,
    )
    uploader.submit(
        EvidenceJob(event_id, (EvidenceFile("IMAGE", "image/jpeg", image),))
    )
    uploader.close(timeout=3)
    assert uploader.stats()["uploaded"] == 1
    assert not image.exists()
    assert not (tmp_path / f"{event_id}.job.json").exists()
    assert session.puts[0][1] == {
        "Content-Type": "image/jpeg",
        "x-ms-blob-type": "BlockBlob",
    }
    assert session.puts[0][2] == b"jpeg-bytes"
    assert session.posts[-1][0].endswith("/complete")


class FailingUploadSession(FakeUploadSession):
    def put(self, url, **kwargs):
        kwargs["data"].read()
        return FakeResponse(503, text="temporary object storage outage")


def test_failed_upload_survives_restart_and_is_recovered(tmp_path):
    event_id = "44444444-4444-4444-8444-444444444444"
    image = tmp_path / "retry.jpg"
    image.write_bytes(b"retry-jpeg")
    first = EvidenceUploader(
        "http://backend/api/v1/internal/events",
        "secret",
        tmp_path,
        session=FailingUploadSession(),
        retries=0,
    )
    first.submit(EvidenceJob(event_id, (EvidenceFile("IMAGE", "image/jpeg", image),)))
    first.close(timeout=3)
    manifest = tmp_path / f"{event_id}.job.json"
    assert first.stats()["failed"] == 1
    assert image.exists()
    assert manifest.exists()

    recovered = EvidenceUploader(
        "http://backend/api/v1/internal/events",
        "secret",
        tmp_path,
        session=FakeUploadSession(),
        retries=0,
    )
    recovered.close(timeout=3)
    assert recovered.stats()["uploaded"] == 1
    assert not image.exists()
    assert not manifest.exists()

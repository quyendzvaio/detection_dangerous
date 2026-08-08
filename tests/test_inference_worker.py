import pytest

from inference_worker import main as worker


def test_worker_accepts_empty_camera_assignment_as_idle(monkeypatch, capsys):
    monkeypatch.setenv("INFERENCE_CAMERAS", "[]")
    monkeypatch.setattr(worker, "_probe_required_services", lambda: None)
    monkeypatch.setattr(worker, "_mark_ready", lambda: None)

    def stop_idle_loop(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker.time, "sleep", stop_idle_loop)
    with pytest.raises(KeyboardInterrupt):
        worker.main()
    assert "NO_CAMERA_CONFIGURED" in capsys.readouterr().out


def test_worker_rejects_malformed_camera_assignment(monkeypatch):
    monkeypatch.setenv("INFERENCE_CAMERAS", '[{"id": 1}]')
    monkeypatch.setattr(worker, "_probe_required_services", lambda: None)

    with pytest.raises(SystemExit, match="requires id, key and stream"):
        worker.main()

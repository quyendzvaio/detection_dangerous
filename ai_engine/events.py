"""
HỢP ĐỒNG ① — EVENT SCHEMA & TRANSPORT (v2 — 25/07/2026)

Định nghĩa MỘT sự kiện vi phạm trông như thế nào, và đường nó đi từ AI worker
sang backend. Ba bên cùng đụng file này:
  - AIE #1 (producer): camera_worker / 4 nhánh phân tích tạo Event và publish()
  - Data #1 (consumer): backend nhận -> ghi bảng `violations` -> upload R2
  - Data #2 (forwarder): backend đẩy tiếp qua WebSocket /ws/alerts cho dashboard

=== VÌ SAO DÙNG HTTP CHỨ KHÔNG PHẢI multiprocessing.Queue HAY gRPC ===

multiprocessing.Queue (v1): chỉ hoạt động khi mọi process do CÙNG một chương
trình cha sinh ra. Thực tế backend chạy bằng lệnh riêng (`uvicorn backend.main:app`)
nên không thể dùng chung Queue với worker — loại.

gRPC: đúng cho kênh worker<->Triton (tensor ảnh 1.2MB, 25 lần/giây). Nhưng cho
kênh event thì phải viết .proto + sinh stub + thêm dependency, đổi lại chỉ nhanh
hơn HTTP vài trăm micro-giây — vô nghĩa khi tần suất chỉ ~1 event/giây.

HTTP POST tới FastAPI: backend đã là HTTP sẵn, không cần hạ tầng mới, debug được
bằng curl, chạy xuyên process/máy. Đây là lựa chọn đúng cho kênh này.

Transport là thành phần THAY THẾ ĐƯỢC (xem EventTransport). Khi nào lên nhiều
edge box thì đổi sang MQTT — 4 nhánh phân tích không sửa một dòng.

=== NGUYÊN TẮC REAL-TIME ===
publish() KHÔNG BAO GIỜ chặn vòng lặp frame. Nó chỉ bỏ event vào buffer nội bộ;
một thread nền lo việc gửi đi. Mạng chậm/backend chết cũng không làm tụt FPS.

LUẬT: sửa file này (thêm/bớt field, đổi giá trị enum) phải báo cả team + được
duyệt. Thêm EventType MỚI thì an toàn; đổi field CŨ thì không.
"""
import json
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

log = logging.getLogger(__name__)


class EventType(str, Enum):
    """
    Bộ từ vựng dùng chung — khớp cột `violations.violation_type` của backend.
    VIẾT HOA theo quy ước backend đã chọn.
    """
    PPE_VIOLATION = 'PPE_VIOLATION'       # ai_metadata: {"no_helmet": bool, "no_glasses": bool, "no_gloves": bool, "no_vest": bool}
    RESTRICTED_ZONE = 'RESTRICTED_ZONE'   # ai_metadata: {"zone_id": int, "zone_name": str}
    FALL_DETECTED = 'FALL_DETECTED'       # ai_metadata: {"score": float, "detector": "model"}
    FALL_SUSPECTED = 'FALL_SUSPECTED'     # ai_metadata: {"score": float, "detector": "heuristic"} — lưới an toàn
    CAMERA_OFFLINE = 'CAMERA_OFFLINE'
    CAMERA_ONLINE = 'CAMERA_ONLINE'
    EMERGENCY = 'EMERGENCY'               # ai_metadata: {"triggered_by": str, "message": str}


class Severity(str, Enum):
    """Khớp cột `violations.severity_level` của backend."""
    INFO = 'INFO'
    WARNING = 'WARNING'
    DANGER = 'DANGER'
    CRITICAL = 'CRITICAL'


DEFAULT_SEVERITY = {
    EventType.PPE_VIOLATION: Severity.DANGER,
    EventType.RESTRICTED_ZONE: Severity.DANGER,
    EventType.FALL_DETECTED: Severity.CRITICAL,
    EventType.FALL_SUSPECTED: Severity.WARNING,
    EventType.CAMERA_OFFLINE: Severity.WARNING,
    EventType.CAMERA_ONLINE: Severity.INFO,
    EventType.EMERGENCY: Severity.CRITICAL,
}


@dataclass
class Event:
    """Một sự kiện vi phạm. Nhẹ — KHÔNG chứa bytes ảnh, chỉ chứa đường dẫn."""

    type: EventType
    camera_id: int                        # khóa ngoại tới bảng `cameras`
    track_id: Optional[str] = None        # "cam1-17" — id tracker, không phải danh tính
    person_id: Optional[int] = None       # khóa ngoại `persons` — None nếu Re-ID chưa định danh
    worker_code: Optional[str] = None     # mã nhân viên (nếu đã enrollment)
    severity: Optional[Severity] = None   # None -> lấy DEFAULT_SEVERITY[type]
    payload: dict[str, Any] = field(default_factory=dict)   # -> cột ai_metadata

    # Bằng chứng: worker chỉ GHI FILE ra spool rồi đặt đường dẫn vào đây.
    # Backend/uploader đọc file, đẩy lên R2, điền image_path/video_path, xóa spool.
    image_spool_path: Optional[str] = None
    video_spool_path: Optional[str] = None

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))  # chống ghi trùng khi retry
    timestamp: float = field(default_factory=time.time)               # epoch giây, UTC

    def __post_init__(self):
        if self.severity is None:
            self.severity = DEFAULT_SEVERITY[self.type]

    @property
    def iso_timestamp(self) -> str:
        return (datetime.fromtimestamp(self.timestamp, tz=timezone.utc)
                .isoformat(timespec='milliseconds'))

    def to_backend_payload(self) -> dict:
        """
        Body HTTP gửi sang backend — TÊN FIELD KHỚP CHÍNH XÁC
        backend.grpc_services.handlers.handle_detection_event().
        Đổi tên field ở đây = làm vỡ backend, phải báo team.
        """
        return {
            'event_id': self.event_id,
            'camera_id': self.camera_id,
            'violation_type': self.type.value,
            'severity_level': self.severity.value,
            'worker_code': self.worker_code,
            'person_id': self.person_id,
            'track_id': self.track_id,
            'detected_time': self.iso_timestamp,
            'image_spool_path': self.image_spool_path,
            'video_spool_path': self.video_spool_path,
            'ai_metadata_json': json.dumps(self.payload, ensure_ascii=False),
        }

    def to_dict(self) -> dict:
        """Dạng JSON-safe dùng cho log và WS broadcast."""
        return {
            'event_id': self.event_id,
            'type': self.type.value,
            'severity': self.severity.value,
            'camera_id': self.camera_id,
            'track_id': self.track_id,
            'person_id': self.person_id,
            'worker_code': self.worker_code,
            'timestamp': self.iso_timestamp,
            'payload': self.payload,
        }


# ---------------------------------------------------------------------------
# Transport — thay thế được, không đụng tới logic 4 nhánh phân tích
# ---------------------------------------------------------------------------

class EventTransport:
    """Giao diện gửi event. Cài đặt phải BLOCKING và tự retry — EventBus
    gọi nó trong thread nền nên chậm cũng không ảnh hưởng vòng lặp frame."""

    def send(self, event: 'Event') -> None:
        raise NotImplementedError


class HttpEventTransport(EventTransport):
    """Mặc định: POST sang backend FastAPI."""

    def __init__(self, url='http://localhost:8080/api/v1/internal/events',
                 timeout=3.0, retries=2):
        self.url = url
        self.timeout = timeout
        self.retries = retries
        self._session = None

    def _get_session(self):
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    def send(self, event: 'Event') -> None:
        session = self._get_session()
        body = event.to_backend_payload()
        for attempt in range(self.retries + 1):
            try:
                resp = session.post(self.url, json=body, timeout=self.timeout)
                if resp.status_code < 400:
                    return
                log.warning('Backend từ chối event %s: HTTP %s',
                            event.event_id, resp.status_code)
            except Exception as exc:
                log.warning('Gửi event %s thất bại (lần %d): %s',
                            event.event_id, attempt + 1, exc)
            time.sleep(0.5 * (attempt + 1))   # backoff tuyến tính
        log.error('BỎ event %s sau %d lần thử', event.event_id, self.retries + 1)


class InProcessTransport(EventTransport):
    """Dùng cho test và cho trường hợp chạy mọi thứ trong một launcher."""

    def __init__(self, sink):
        self.sink = sink   # callable(event) hoặc list để append

    def send(self, event: 'Event') -> None:
        if callable(self.sink):
            self.sink(event)
        else:
            self.sink.append(event)


class EventBus:
    """
    Cầu nối giữa vòng lặp frame (nhanh, không được chặn) và mạng (chậm, hay lỗi).

        worker  --publish()-->  [buffer nội bộ]  --thread nền-->  transport --> backend
                 (micro-giây)     (RAM, có hạn)      (chấp nhận chậm)

    Buffer đầy: bỏ event thường, nhưng CRITICAL thì đẩy bằng cách vứt event cũ
    nhất — cú ngã không bao giờ bị hy sinh cho một cảnh báo PPE.
    """

    def __init__(self, transport: EventTransport, max_buffer: int = 200):
        self.transport = transport
        self._buffer = queue.Queue(maxsize=max_buffer)
        self._stop = threading.Event()
        self.dropped_count = 0          # -> telemetry hiển thị lên dashboard
        self.sent_count = 0
        self._thread = threading.Thread(target=self._drain_loop, daemon=True,
                                        name='event-sender')
        self._thread.start()

    def publish(self, event: Event) -> None:
        """Gọi từ vòng lặp frame. Không bao giờ chặn, không bao giờ ném lỗi."""
        try:
            self._buffer.put_nowait(event)
            return
        except queue.Full:
            pass

        if event.severity == Severity.CRITICAL:
            try:                       # vứt event cũ nhất để nhường chỗ
                self._buffer.get_nowait()
                self.dropped_count += 1
                self._buffer.put_nowait(event)
                return
            except Exception:
                pass

        self.dropped_count += 1
        log.warning('Buffer đầy — bỏ event %s (%s)', event.event_id, event.type.value)

    def _drain_loop(self):
        while not self._stop.is_set():
            try:
                event = self._buffer.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self.transport.send(event)
                self.sent_count += 1
            except Exception:
                log.exception('Transport lỗi không mong đợi')

    def stats(self) -> dict:
        return {'sent': self.sent_count, 'dropped': self.dropped_count,
                'pending': self._buffer.qsize()}

    def close(self, timeout=3.0):
        """Gọi khi worker tắt — cố gửi nốt event còn trong buffer."""
        deadline = time.time() + timeout
        while not self._buffer.empty() and time.time() < deadline:
            time.sleep(0.05)
        self._stop.set()
        self._thread.join(timeout=1.0)

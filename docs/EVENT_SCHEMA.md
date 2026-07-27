# Hợp đồng Message & Event giữa các tầng

> **v1.0 — 27/07/2026.** Đây là nguồn tham chiếu chung cho đội AI Engine,
> Backend, Data và Frontend. Thay đổi phá vỡ tương thích phải được thảo luận và
> tăng `schema_version`.

Hệ thống dùng ba loại thông điệp khác nhau. Không gọi chung tất cả là “event”,
vì vòng lặp frame và sự kiện nghiệp vụ có yêu cầu hoàn toàn khác nhau.

| Loại | Hướng đi | Mục đích | Transport |
|---|---|---|---|
| **Observation message** | Tầng 1 → Tầng 2 | Dữ liệu frame/tracking tần suất cao | RAM + bounded queue, không JSON/HTTP |
| **Safety event** | Tầng 2 → Tầng 4 | Một sự việc an toàn đã được kết luận | HTTP Event Bus, retry, idempotency |
| **Control command** | Backend → worker | Điều khiển worker/cấu hình | Kênh control riêng, không vào frame queue |

---

## 1. Observation message — Tầng 1 → Tầng 2

### Vai trò trong pipeline

```text
OpenCV frame
  → Triton YOLO Pose
  → BoT-SORT gán track_id
  → TrackedFrame
  → dispatcher
  ├→ ZoneTask
  ├→ FallTask
  ├→ ReIdTask (chỉ track mới/cần nhận diện lại)
  └→ PpeTask  (chỉ khi đến chu kỳ kiểm tra)
```

Tầng 1 là một `CameraWorker` process cho mỗi camera; nó sở hữu frame OpenCV và
tracker. Tầng 2 chỉ nhận dữ liệu mà từng nhánh phân tích cần. Triton không tự
đọc queue Python: worker của nhánh lấy task từ queue, chuẩn bị tensor và gọi
Triton.

### `TrackedFrame`

`TrackedFrame` là bức ảnh chụp toàn cảnh của **một frame** sau Pose + tracking.
Nó chứa ảnh gốc một lần và danh sách toàn bộ người trong frame.

```python
@dataclass(frozen=True)
class TrackedFrame:
    schema_version: str               # "1.0"
    camera_id: int                    # FK cameras.id
    camera_key: str                   # ví dụ "cam1"
    sequence_id: int                  # tăng dần, riêng từng camera
    captured_at: float                # Unix epoch lúc camera capture frame
    frame_bgr: np.ndarray             # uint8 H×W×3, chỉ tồn tại trong RAM
    frame_width: int
    frame_height: int
    persons: tuple[TrackObservation, ...]
    pose_model: str                   # "yolo_pose"
    pose_model_version: str
```

`frame_bgr` không được serialize thành JSON, gửi HTTP hay ghi database. Nếu crop
được đưa sang queue/process khác, crop phải `.copy()` trước khi enqueue.

### `TrackObservation`

`TrackObservation` mô tả **một người trong một `TrackedFrame`**. Một frame có
ba người sẽ có một `TrackedFrame` và ba observation; điều này tránh lặp lại ảnh
720p ba lần.

```python
@dataclass(frozen=True)
class TrackObservation:
    track_id: str                     # "cam1-17", duy nhất khi track còn sống
    bbox_xyxy: np.ndarray             # float32 [x1, y1, x2, y2], theo frame gốc
    keypoints: np.ndarray             # float32 (17, 3): x, y, confidence
    detection_confidence: float
    timestamp: float                  # bằng captured_at của TrackedFrame
```

Keypoint luôn theo tọa độ frame gốc. Chỉ `PpeTask` dùng keypoint tương đối với
person crop vì nó cần cắt đầu/mặt/tay/thân.

### Task cho từng nhánh phân tích

Dispatcher tạo task nhỏ, không đẩy nguyên `TrackedFrame` vào cả bốn queue.

| Queue | Task | Dữ liệu bắt buộc | Quy tắc tạo |
|---|---|---|---|
| `zone_queue` | `ZoneTask` | `camera_id`, `track_id`, `bbox_xyxy`, `timestamp` | Mọi frame/mọi track |
| `fall_queue` | `FallTask` | `camera_id`, `track_id`, `keypoints`, `timestamp` | Mọi frame/mọi track |
| `reid_queue` | `ReIdTask` | `camera_id`, `track_id`, `person_crop`, `timestamp` | Track mới hoặc cần re-check |
| `ppe_queue` | `PpeTask` | `camera_id`, `track_id`, `person_crop`, `relative_keypoints`, `timestamp` | Theo `ppe_check_interval_s` |

`person_crop` là mảng BGR cắt từ `frame_bgr` theo bbox và **thuộc sở hữu của
task**. Zone và Fall không nhận ảnh, nên không phải copy frame lớn.

### Quy tắc hàng đợi

- Queue có kích thước giới hạn; không tích lũy frame cũ.
- Queue realtime đầy thì ưu tiên bỏ task cũ hơn là tăng latency. Fall vẫn giữ
  timestamp thật để preprocessing resample đúng.
- Không truyền `frame_bgr` qua `multiprocessing.Queue` ở giai đoạn đầu vì sẽ
  copy ảnh lớn. Mỗi process camera tự dispatch task của nó.
- `track_id` chỉ ổn định trong camera; bắt buộc có prefix camera. Danh tính toàn
  cục là `person_id` do Re-ID quyết định.

---

## 2. Safety event — Tầng 2 → Tầng 4

Safety event chỉ được phát sau khi một nhánh đã kết luận vi phạm hoặc trạng thái
hệ thống. Nó không chứa tensor, frame bytes, `payload`, hay `ai_metadata_json`.

```jsonc
{
  "event_id": "b3f1c8e2-...",       // UUID, idempotency khi retry
  "camera_id": 1,
  "violation_type": "RESTRICTED_ZONE",
  "severity_level": "DANGER",
  "track_id": "cam1-17",
  "person_id": 42,                  // null nếu Re-ID chưa xác định
  "worker_code": null,
  "detected_time": "2026-07-27T08:15:32.120+00:00",
  "image_spool_path": "/spool/cam1-abc.jpg",
  "video_spool_path": null
}
```

Đường đi: `publish()` → EventBus buffer → HTTP POST → backend. EventBus chạy
thread nền để mạng chậm hoặc backend tạm lỗi không chặn vòng lặp frame.

| `violation_type` | Severity mặc định | Đích dữ liệu |
|---|---|---|
| `PPE_VIOLATION` | `DANGER` | `violations` |
| `RESTRICTED_ZONE` | `DANGER` | `violations` |
| `FALL_DETECTED` | `CRITICAL` | `violations` |
| `FALL_SUSPECTED` | `WARNING` | `violations` |
| `EMERGENCY` | `CRITICAL` | `violations` |
| `CAMERA_OFFLINE` | `WARNING` | `system_events` |
| `CAMERA_ONLINE` | `INFO` | `system_events` |

---

## 3. Control command và telemetry

Hai contract cần chốt tiếp theo, nhưng không được đưa vào queue frame:

- `CameraControl`: bật/tắt camera, cập nhật zone polygon, bật/tắt model, thay
  ngưỡng runtime, yêu cầu restart worker.
- `WorkerStatus`: heartbeat, camera online/offline, input FPS, AI FPS, latency
  Triton, queue depth, số frame/task drop và lỗi model.

Control là mệnh lệnh có thể thất bại; telemetry là trạng thái để
backend/dashboard giám sát. Cả hai khác với Safety event là một sự kiện an toàn
đã xảy ra.

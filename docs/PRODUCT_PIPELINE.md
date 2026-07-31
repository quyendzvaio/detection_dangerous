# Luồng sản phẩm AI và Event Contract

Tài liệu này là nguồn thống nhất cho luồng AI của sản phẩm. Nếu code và tài liệu mâu thuẫn, đội nhóm phải sửa cả hai trong cùng một pull request. Các tài liệu kiến trúc cũ đã được bỏ khỏi nhánh `develop` để tránh tồn tại nhiều mô tả khác nhau cho cùng một hệ thống.

## 1. Phạm vi hiện tại

Nhánh `develop` chứa đường chạy sản phẩm từ Layer 0 đến hết Layer 2, chưa nối database/backend:

- Layer 0: đọc USB, RTSP/HTTP hoặc video file; mỗi camera là một process độc lập.
- Layer 1: gọi YOLO Pose trên Triton và chạy BoT-SORT cục bộ để tạo ID theo từng camera.
- Layer 2: ba nhánh độc lập `zone`, `fall`, `ppe`, mỗi nhánh có queue hữu hạn và consumer thread riêng.
- Event contract: typed dataclass cho Safety Event và Camera Status Event.
- Preview: bbox, track ID, FPS/latency và bảng cảnh báo; không vẽ skeleton.

Chưa thuộc phạm vi đã hoàn thiện:

- Backend/database và API điều khiển camera/model.
- Upload bằng chứng trực tiếp lên R2.
- Re-ID: không có trong runtime hoặc model toggle của giai đoạn này.
- `FALL_SUSPECTED`: contract đã giữ theo quyết định sản phẩm, nhưng producer/policy phát event chưa được nối. Không được hiểu rằng hệ thống hiện đã phát loại event này.

## 2. Kiến thức nền cần thống nhất

**Process** có vùng nhớ riêng. Mỗi camera dùng một process nên camera chậm, mất kết nối hoặc tracker lỗi không chặn camera khác. Đây là ranh giới cô lập chính.

**Thread** chia sẻ vùng nhớ trong một process. Ba nhánh Layer 2 dùng thread để chạy độc lập và trao đổi qua queue. Thread không đồng nghĩa với queue: queue là bộ đệm truyền dữ liệu; thread là đơn vị thực thi lấy dữ liệu từ queue.

**Triton Inference Server** là dịch vụ GPU dùng chung. Nhiều process camera gửi gRPC request vào cùng Triton. Triton gom/lập lịch request và chạy model trên GPU; CPU process không cần sở hữu riêng một GPU hay model. YOLO Pose và fall model đang phục vụ qua Triton. BoT-SORT là stateful theo camera nên vẫn chạy cục bộ sau pose inference.

**Typed event** là message có field và kiểu dữ liệu cố định. Nó thay dict tự do để producer và consumer không tự đặt tên field khác nhau. Contract chính nằm tại `ai_engine/contracts/event_schema.py`.

**Backpressure** xảy ra khi producer nhanh hơn consumer. Queue Layer 2 có kích thước hữu hạn và dùng chính sách bỏ task cũ nhất để ưu tiên dữ liệu mới, tránh latency tăng vô hạn.

## 3. Luồng chạy tổng thể

```text
USB / RTSP / HTTP / video file
            │
            ▼
Layer 0 — một process cho mỗi camera
OpenCV capture thread → LatestFrameBuffer (chỉ giữ frame mới nhất)
            │ CapturedFrame
            ▼
Layer 1 — trong cùng camera process
Triton YOLO Pose → bbox + 17 keypoint → BoT-SORT → track_id
            │ TrackedFrame
            ▼
Layer 2 dispatcher (không block)
       ┌────┴───────────┬──────────────┐
       ▼                ▼              ▼
 zone queue          fall queue       ppe queue
 CPU checker         temporal buffer  crop + PPE detector
       │                │ Triton fall   │
       └────────────┬───┴──────────────┘
                    ▼
          typed SafetyEvent callback
                    ▼
       EventBus → HTTP transport → backend (bước kế tiếp)
```

Mỗi camera có toàn bộ Layer 0–2 riêng trên CPU. Triton là điểm GPU dùng chung. Vì queue của camera và state BoT-SORT/fall nằm trong process camera, track của hai camera không đè lên nhau. `track_id` được prefix bằng `camera_key`, ví dụ `gate_a-17`.

## 4. Layer 0: ingest và dữ liệu đầu ra

`CameraIngest` mở nguồn hình trong một capture thread. `LatestFrameBuffer` chỉ có một slot:

1. Capture đọc frame mới và publish.
2. Nếu frame cũ chưa được Layer 1 lấy, frame mới ghi đè frame cũ.
3. Layer 1 luôn lấy frame mới nhất đang có.

Cách này phù hợp giám sát realtime: mất một số frame tốt hơn xem sự kiện trễ nhiều giây. Fall detection vẫn giữ chuỗi thời gian vì Layer 2 lưu keypoint cùng `captured_at` và nội suy/resample theo thời gian thực, không giả định frame liên tiếp hay FPS cố định.

### `CapturedFrame`

| Field | Kiểu | Ý nghĩa |
|---|---|---|
| `camera_id` | `int` | ID camera trong hệ thống |
| `camera_key` | `str` | Tên ổn định dùng trong process/log/track prefix |
| `captured_at` | `float` | Epoch seconds UTC khi frame được lấy |
| `frame_bgr` | `numpy.ndarray` | Ảnh BGR trong RAM, không serialize ra backend |
| `frame_width`, `frame_height` | `int` | Kích thước ảnh |

Không có `sequence_id`. Hệ thống không có chức năng nghiệp vụ cần số thứ tự frame; bằng chứng dùng `event_id`, `camera_id` và thời điểm. Việc frame bị thay thế đã có metrics `accepted/overwritten/delivered`.

## 5. Layer 1: pose, tracking và dữ liệu đầu ra

Layer 1 gửi frame tới model `yolo_pose` bằng Triton gRPC. Kết quả pose gồm bbox, confidence và 17 COCO keypoint. BoT-SORT ghép detection qua thời gian để tạo ID cục bộ. Re-ID của BoT-SORT đang tắt.

### `TrackObservation`

Một người trong một frame:

| Field | Kiểu | Ý nghĩa |
|---|---|---|
| `track_id` | `str` | ID camera-prefixed, không phải danh tính nhân viên |
| `bbox_xyxy` | `numpy.ndarray` | `[x1, y1, x2, y2]` trên ảnh gốc |
| `keypoints` | `numpy.ndarray` | Shape `(17, 3)`: x, y, confidence |
| `detection_confidence` | `float` | Độ tin cậy detection người |

### `TrackedFrame`

Chứa metadata/frame của `CapturedFrame`, tuple `persons`, `pose_model` và `pose_model_version`. Mọi observation trong nó cùng thuộc một ảnh nên chỉ dùng `TrackedFrame.captured_at`; không lặp timestamp ở từng person.

Đây là aggregate message: một frame chứa nhiều observation. Layer 2 fan-out nó thành payload tối thiểu để không copy cả ảnh vào mọi queue.

## 6. Layer 2: ba nhánh phân tích

`Layer2Runtime.dispatch()` đọc `TrackedFrame` và tạo:

- `ZoneTask`: bbox + track + thời gian.
- `FallTask`: 17 keypoint + track + thời gian.
- `PpeTask`: crop người riêng + keypoint tương đối + thời gian.

Mỗi queue thuộc một nhánh và một camera process. Queue không tự tạo thread; `Layer2Runtime.start()` tạo một consumer thread cho từng nhánh. Queue hữu hạn ngăn RAM tăng vô hạn. Tách queue giúp PPE chậm không giữ fall/zone phía sau nó. Nếu dùng chung một FIFO queue, một tác vụ chậm ở đầu hàng sẽ gây head-of-line blocking cho mọi model.

### Zone

Lấy bottom-center của bbox làm vị trí chân, kiểm tra điểm trong polygon bằng OpenCV và debounce 5 frame liên tiếp để lọc rung tracker. Khi xác nhận đi vào, phát `RestrictedZoneEvent`. Trạng thái đi ra chỉ cập nhật realtime/preview; theo quyết định hiện tại không persist exit time và không tính duration.

Polygon đến từ cấu hình backend theo camera trong bước tích hợp sau. Preview có thể vẽ polygon từ cùng cấu hình, không đặt polygon vào Safety Event.

### Fall

Mỗi track có buffer keypoint theo thời gian. Tiền xử lý:

1. Chọn cửa sổ thời gian gần nhất.
2. Keypoint confidence thấp được xem là thiếu.
3. Tâm hóa theo midpoint hai hông và scale theo chiều dài torso để giảm ảnh hưởng vị trí/kích thước người.
4. Nội suy điểm thiếu và resample thành 60 mốc theo `captured_at`.
5. Thêm đặc trưng chuyển động, tạo tensor `(1, 60, 85)`.
6. Gửi tensor tới `fall_model` trên Triton, nhận probability.

Model là bộ phân loại chuỗi keypoint dùng quan hệ không gian giữa các keypoint và quan hệ thời gian giữa các frame. Chất lượng pose/keypoint đầu vào ảnh hưởng trực tiếp kết quả. Quyết định hiện tại dùng threshold trong `weights/fall_model/inference_config.json`, debounce 2 phiếu dương trong 3 lần dự đoán và cooldown trước khi phát lại. Khi phát `FALL_DETECTED`, overlay latch đỏ cho tới khi track biến mất đủ TTL hoặc được clear rõ ràng.

`FALL_SUSPECTED` có schema WARNING để làm lưới an toàn, nhưng chưa có rule producer được đội sản phẩm chốt. Không tự phát nó từ heuristic trước khi có threshold/debounce/test riêng.

### PPE

Theo chu kỳ cấu hình, Layer 2 crop người và chạy PPE detector. Kết quả nội bộ có bốn cờ: helmet, glasses, gloves và vest. Event chỉ phát khi có lỗi và trạng thái lỗi đổi, tránh spam cùng một lỗi ở mọi frame. Một kết quả sạch xóa cảnh báo PPE realtime và bbox trở lại xanh.

## 7. Event contract gửi backend

Mọi Safety Event dùng chung:

| Field | Ý nghĩa |
|---|---|
| `event_id` | UUID để idempotency/retry, không phải thứ tự frame |
| `camera_id` | Camera sinh sự kiện |
| `track_id` | ID tracker tạm thời, không phải person/worker identity |
| `violation_type` | Enum loại vi phạm |
| `severity_level` | `WARNING`, `DANGER` hoặc `CRITICAL` |
| `detected_time` | ISO-8601 UTC tạo từ `captured_at` |
| `evidence_status` | `PROCESSING`, `READY` hoặc `FAILED` |
| `image_storage_key` | Object key sau upload, có thể `null` lúc alert đầu tiên |
| `video_storage_key` | Object key sau upload, có thể `null` |

Không dùng `schema_version`, `sequence_id`, `ai_metadata_json`, `person_id`, `worker_code` trong contract hiện tại.

### Các Safety Event có kiểu riêng

| Event | Field riêng | Severity | Bằng chứng đã chọn |
|---|---|---|---|
| `PPEViolationEvent` | `violation_codes[]` | DANGER | Ảnh annotate |
| `FallDetectedEvent` | `confidence` | CRITICAL | Thumbnail + video pre/post |
| `FallSuspectedEvent` | `confidence` | WARNING | Chưa nối producer/policy |
| `RestrictedZoneEvent` | `zone_id` | DANGER | Ảnh annotate có polygon |

Ví dụ PPE:

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "camera_id": 1,
  "track_id": "gate_a-17",
  "violation_type": "PPE_VIOLATION",
  "severity_level": "DANGER",
  "detected_time": "2026-07-31T03:20:12.123+00:00",
  "evidence_status": "PROCESSING",
  "image_storage_key": null,
  "video_storage_key": null,
  "violation_codes": ["NO_HELMET", "NO_VEST"]
}
```

Ví dụ fall chỉ thêm `"confidence": 0.828`; không gửi tên/version model. Zone chỉ thêm `"zone_id": 12`; frontend/backend tra tên và polygon bằng ID.

### Camera Status Event

`CameraStatusEvent` tách khỏi Safety Event vì online/offline là trạng thái vận hành, không phải vi phạm. Nó có `event_category=CAMERA_STATUS`, `camera_id`, `status`, `observed_time`, `reason`, `source` và `event_id`.

Camera Status Event không dùng để bật/tắt model. Bật/tắt model là **control command** đi chiều backend → camera runtime. Trạng thái camera là telemetry đi chiều camera supervisor → backend. Hai chiều có thể dùng cùng HTTP/EventBus nhưng contract và handler phải riêng.

## 8. Bật/tắt model theo camera

`ModelToggles(zone, fall, ppe)` nằm trong config của từng `Layer2Runtime`. Vì mỗi camera có runtime riêng, backend sau này có thể gửi control command tới đúng `camera_id` rồi gọi `set_models()` mà không restart camera.

Re-ID cố ý không có trong `ModelToggles`. Nếu backend gửi key không thuộc `zone/fall/ppe`, runtime từ chối thay vì âm thầm nhận cấu hình không chạy.

## 9. Bằng chứng: upload trực tiếp R2, biến thể B

Luồng đã chọn cho bước backend tiếp theo:

1. AI phát alert ngay với `evidence_status=PROCESSING`; không chờ encode/upload.
2. AI yêu cầu backend cấp presigned upload URL và object key theo `event_id`.
3. AI upload bytes trực tiếp lên R2; backend không làm proxy file lớn.
4. AI báo hoàn tất `READY` cùng storage key, hoặc `FAILED` và lý do.
5. Backend cập nhật record rồi phát trạng thái mới tới dashboard.

Presigned URL là URL có chữ ký và thời hạn ngắn, chỉ cho phép upload object đã định. Nó giúp AI không giữ R2 secret và tránh đưa video qua RAM/băng thông backend. Backend vẫn kiểm soát bucket, key và thời hạn.

Phần handshake/presigned API chưa được implement trong nhánh này; cần chốt endpoint request/complete với đội backend trước khi nối. Safety alert không được phụ thuộc thành công của evidence upload.

## 10. File quan trọng

| File | Vai trò |
|---|---|
| `ai_engine/contracts/event_schema.py` | Nguồn chuẩn cho frame/task/event contract |
| `ai_engine/ingest/camera_stream.py` | OpenCV source và capture thread |
| `ai_engine/ingest/latest_frame.py` | Buffer chỉ giữ frame mới nhất |
| `ai_engine/pipeline/layer1_processor.py` | Pose + tracking → `TrackedFrame` |
| `ai_engine/pipeline/layer2_runtime.py` | Fan-out queue, model toggle, ba consumer |
| `ai_engine/analytics/fall.py` | Buffer, preprocess, Triton fall và debounce |
| `ai_engine/analytics/zone.py` | Point-in-polygon và debounce zone |
| `ai_engine/events.py` | EventBus và HTTP transport không block frame loop |
| `ai_engine/visualization/track_overlay.py` | Bbox/ID/alert compact, không skeleton |
| `triton_model_repo/yolo_pose/` | Triton repository cho pose |
| `triton_model_repo/fall_model/` | Triton repository cho fall |
| `run_pipeline_demo.sh` | Smoke test Layer 0–2 và khởi động Triton |

## 11. Chạy smoke test

Một USB camera:

```bash
./run_pipeline_demo.sh --camera 1:cam1:0 --show
```

Hai camera độc lập:

```bash
./run_pipeline_demo.sh \
  --camera 1:cam1:0 \
  --camera 2:cam2:2 \
  --show
```

Video file:

```bash
./run_pipeline_demo.sh --camera 1:test:/absolute/path/test.mp4 --show
```

Chọn model theo camera demo hiện dùng cùng toggle cho mọi camera trong một lần chạy:

```bash
LAYER2_MODELS=zone,fall,ppe ./run_pipeline_demo.sh --camera 1:cam1:0 --show
```

Trong sản phẩm, backend sẽ lưu và gửi toggle riêng cho từng `camera_id`; demo CLI chỉ là công cụ smoke test.

## 12. Quy tắc thay đổi contract

- Không thêm field “để phòng sau này” nếu chưa có consumer hoặc chức năng rõ ràng.
- Thêm/đổi/xóa field event phải sửa dataclass, serialization test, tài liệu và backend consumer trong cùng thay đổi tích hợp.
- Frame/task chứa `numpy.ndarray` chỉ dùng nội bộ, không JSON serialize.
- Safety Event là immutable (`frozen=True`) để thread khác không sửa event sau khi publish.
- `event_id` xử lý retry/idempotency; `captured_at` xử lý thời gian; hai field này không thay cho nhau.

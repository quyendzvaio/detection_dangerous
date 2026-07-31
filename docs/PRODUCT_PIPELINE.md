# Luồng sản phẩm AI và Event Contract

Tài liệu này là nguồn thống nhất cho luồng AI của sản phẩm. Nếu code và tài liệu mâu thuẫn, đội nhóm phải sửa cả hai trong cùng một pull request. Các tài liệu kiến trúc cũ đã được bỏ khỏi nhánh `develop` để tránh tồn tại nhiều mô tả khác nhau cho cùng một hệ thống.

## 1. Phạm vi hiện tại

Đường tích hợp hiện tại chạy từ Layer 0 đến Layer 4:

- Layer 0: đọc USB, RTSP/HTTP hoặc video file; mỗi camera là một process độc lập.
- Layer 1: gọi YOLO Pose trên Triton và chạy BoT-SORT cục bộ để tạo ID theo từng camera.
- Layer 2: ba nhánh độc lập `zone`, `fall`, `ppe`, mỗi nhánh có queue hữu hạn và consumer thread riêng.
- EventBus: mỗi camera process có buffer gửi sự kiện riêng, không block vòng xử lý frame; HTTP dùng Bearer service token và retry lỗi tạm thời.
- Layer 4: FastAPI kiểm tra typed event, chống ghi trùng bằng `event_id`, ghi PostgreSQL và phát WebSocket alert sau khi commit.
- Vận hành: Docker Compose chạy PostgreSQL, Adminer, backend và Triton trên máy local; Alembic tự chạy migration trước backend. Chỉ file evidence được lưu trên Azure Blob Cloud.
- Preview: bbox, track ID, FPS/latency và bảng cảnh báo; không vẽ skeleton.

Đã kiểm thử end-to-end thật với `FALL_DETECTED` và Camera Status: HTTP request đi qua backend và tạo đúng một dòng PostgreSQL khi gửi lặp cùng `event_id`.

Chưa thuộc phần hoàn thiện:

- Backend đẩy model toggle/zone config nóng xuống camera runtime. Database đã lưu toggle và polygon, nhưng runner demo vẫn nhận model toggle từ CLI và chưa tải polygon từ backend.
- Lifecycle/retention rule tự xóa blob Azure cũ và recovery tự động cho fall clip bị dừng giữa lúc đang thu hậu cảnh.
- Azure Blob Cloud thật đã được smoke test end-to-end: backend cấp SAS, PUT trả 201, blob properties được xác minh, database chuyển READY và SAS GET trả 200 với bytes khớp.
- Re-ID: không có trong runtime hoặc model toggle của giai đoạn này.
- `FALL_SUSPECTED`: contract đã giữ theo quyết định sản phẩm, nhưng producer/policy phát event chưa được nối.

## 2. Kiến thức nền cần thống nhất

**Process** có vùng nhớ riêng. Mỗi camera dùng một process nên camera chậm, mất kết nối hoặc tracker lỗi không chặn camera khác. Đây là ranh giới cô lập chính.

**Thread** chia sẻ vùng nhớ trong một process. Ba nhánh Layer 2 dùng thread để chạy độc lập và trao đổi qua queue. Thread không đồng nghĩa với queue: queue là bộ đệm truyền dữ liệu; thread là đơn vị thực thi lấy dữ liệu từ queue.

**Triton Inference Server** là dịch vụ GPU dùng chung. Nhiều process camera gửi gRPC request vào cùng Triton. Triton gom/lập lịch request và chạy model trên GPU; CPU process không cần sở hữu riêng một GPU hay model. YOLO Pose và fall model đang phục vụ qua Triton. BoT-SORT là stateful theo camera nên vẫn chạy cục bộ sau pose inference.

**Typed event** là message có field và kiểu dữ liệu cố định. Nó thay dict tự do để producer và consumer không tự đặt tên field khác nhau. Contract producer nằm tại `ai_engine/contracts/event_schema.py`; schema Pydantic phía nhận nằm tại `backend/models/schemas/event.py`.

**Idempotency** nghĩa là gửi lại cùng một thao tác không tạo kết quả lần hai. Backend đặt unique constraint lên `event_id`; vì vậy EventBus có thể retry mà không tạo hai violation.

**Migration** là lịch sử thay đổi cấu trúc database có thứ tự. Alembic chạy `upgrade head` trước khi backend mở cổng, thay cho việc tự tạo bảng ngầm lúc import ứng dụng.

**Backpressure** xảy ra khi producer nhanh hơn consumer. Queue Layer 2 và EventBus đều có kích thước hữu hạn. Layer 2 bỏ task cũ để ưu tiên dữ liệu mới; EventBus ưu tiên giữ CRITICAL event khi buffer đầy.

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
       EventBus hữu hạn trong camera process
                    ▼ Bearer HTTP
       FastAPI typed ingestion → PostgreSQL commit
                    ▼
          WebSocket `/ws/alerts`

Nhánh evidence chạy song song, không giữ alert:
Layer 2 event → frame spool → backend SAS upload lease → AI PUT trực tiếp Azure Blob
                                      → backend blob-properties verify → READY/FAILED
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

Backend đã có bảng/API lưu polygon normalized `[0, 1]` theo camera. Tuy nhiên runner demo chưa tải và đổi polygon sang pixel để truyền vào `CameraLayer2Config.zones`, nên zone branch hiện chỉ phát event khi caller đã cấp `zones` trực tiếp. Đây là khoảng nối cấu hình còn lại; polygon không đặt vào Safety Event.

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

### Layer 4 nhận và lưu event

| Endpoint nội bộ | Dữ liệu | Bảng đích |
|---|---|---|
| `PUT /api/v1/internal/cameras/{camera_id}` | Đăng ký/update camera cho launcher local | `cameras` |
| `POST /api/v1/internal/events` | Bốn typed Safety Event | `violations` |
| `POST /api/v1/internal/camera-status` | ONLINE/OFFLINE telemetry | `system_events` và `cameras.status` |

Ba endpoint này yêu cầu `Authorization: Bearer <AI_SERVICE_TOKEN>`. Backend dùng Pydantic discriminated union theo `violation_type`, nên field thừa/cũ như `schema_version` hoặc sai severity bị trả `422`. Camera/zone không tồn tại bị trả `404`; lỗi contract 4xx không retry. Lỗi mạng, `408/425/429` và 5xx mới retry exponential backoff.

Safety Event được commit PostgreSQL trước, sau đó mới broadcast WebSocket. Nếu database lỗi thì dashboard không nhận một alert “ảo” chưa được lưu. Bảng `violations` giữ các field chung và ba nhóm field riêng: `confidence`, `zone_id`, `violation_codes`.

## 8. Bật/tắt model theo camera

`ModelToggles(zone, fall, ppe)` nằm trong config của từng `Layer2Runtime`. Bảng `cameras` đã có ba cột toggle riêng; launcher local đăng ký giá trị CLI vào các cột này. Luồng control backend → process để áp dụng thay đổi runtime chưa được nối, nên sửa database lúc camera đang chạy chưa tự gọi `set_models()`.

Re-ID cố ý không có trong `ModelToggles`. Nếu control sau này gửi key không thuộc `zone/fall/ppe`, runtime từ chối thay vì âm thầm nhận cấu hình không chạy.

## 9. Bằng chứng Azure Blob: upload trực tiếp, biến thể B

Phần này đã được nối trong code. Nguyên tắc quan trọng nhất là **alert không chờ evidence**:

1. Layer 2 phát Safety Event ngay với `evidence_status=PROCESSING`.
2. EventBus gửi alert vào PostgreSQL trước.
3. Evidence thread lấy frame mẫu và ghi file vào `evidence_spool/<camera_key>/`.
4. AI gọi `POST /internal/events/{event_id}/evidence/presign` với kind, content type và size. Tên endpoint cũ được giữ để không phá client, nhưng kết quả hiện là Azure SAS upload lease.
5. Backend tự tạo object key và trả `upload_url`, `upload_headers`, thời gian hết hạn. Azure connection string chỉ tồn tại ở backend.
6. AI `PUT` file thẳng vào Azure Blob Cloud; file bytes không đi qua FastAPI. Uploader gửi đúng các header backend cấp, gồm `Content-Type`, `x-ms-blob-type: BlockBlob` và `x-ms-blob-content-type`.
7. AI gọi `complete`. Backend đọc blob properties, kiểm tra tồn tại, size và content type rồi mới chuyển `READY`.
8. Khi PUT/verify thất bại, AI gọi `fail`, database chuyển `FAILED` và file spool vẫn được giữ để retry sau.
9. Backend broadcast `EVIDENCE_STATUS` qua WebSocket sau khi commit.

SAS URL là bearer credential có quyền và thời hạn hẹp; ai có URL còn hiệu lực đều có thể dùng quyền trong URL, vì vậy không log toàn bộ URL. PostgreSQL vẫn nằm trong Docker volume local; chỉ bytes JPEG/MP4 đi lên Azure.

### Loại bằng chứng

| Event | File bắt buộc | Capture hiện tại |
|---|---|---|
| `PPE_VIOLATION` | IMAGE `image/jpeg` | Frame gần event, bbox + nhãn lỗi |
| `RESTRICTED_ZONE` | IMAGE `image/jpeg` | Frame gần event, bbox + nhãn zone; polygon chờ zone-config sync |
| `FALL_DETECTED` | IMAGE + VIDEO | Thumbnail và clip mặc định 5 giây trước + 5 giây sau |
| `FALL_SUSPECTED` | IMAGE | Contract sẵn; producer chưa bật |

Frame evidence được lấy mẫu mặc định 8 FPS, JPEG quality 82. Encode JPEG/MP4 chạy ngoài hot loop; frame queue chỉ có hai slot và bỏ frame evidence cũ khi chậm. Ring buffer giữ JPEG đã nén, không giữ hàng trăm raw BGR frame trong RAM. Fall MP4 hiện dùng codec `mp4v`; cần kiểm tra khả năng phát của frontend mục tiêu trước khi chốt codec production/H.264.

### Blob key và database

Backend không nhận blob key từ AI mà tự tạo:

```text
evidence/camera-<camera_id>/YYYY/MM/DD/<event_id>/image.jpg
evidence/camera-<camera_id>/YYYY/MM/DD/<event_id>/video.mp4
```

`violations` giữ trạng thái tổng hợp và `image_storage_key`/`video_storage_key`. `evidence_objects` giữ từng blob: kind, content type, declared/verified size, ETag, upload expiry, failure reason và timestamps. Unique `(violation_id, kind)` ngăn hai IMAGE hoặc hai VIDEO cho cùng event.

| Trạng thái | Ý nghĩa |
|---|---|
| `PROCESSING` | Alert đã có; đang capture, chờ SAS URL hoặc upload |
| `READY` | Mọi blob bắt buộc đã được Azure Blob properties xác nhận |
| `FAILED` | Ít nhất một blob upload/verify thất bại |

Manifest `*.job.json` nằm cạnh file spool. Uploader load lại manifest khi camera process khởi động lại. Sau `READY`, file và manifest local mới bị xóa. Nếu process chết trong lúc Fall vẫn đang thu phần post-event và chưa tạo manifest, recovery tự động cho clip dở dang chưa được implement.

### PostgreSQL local, evidence trên Azure Blob Cloud

`docker-compose.yml` giữ PostgreSQL và Adminer trên máy local. Compose không còn storage emulator hoặc fallback xuống ổ đĩa: khi evidence bật, `run_pipeline_demo.sh` yêu cầu Azure connection string và dừng với thông báo rõ ràng nếu thiếu.

Từ Azure Portal, cần lấy **Storage account connection string** tại Storage account → Security + networking → Access keys → Connection string. Container mặc định là `industrial-safety-evidence`; với `AZURE_STORAGE_CREATE_CONTAINER=true`, backend tự tạo container private nếu chưa tồn tại. `AZURE_STORAGE_PUBLIC_BLOB_ENDPOINT` không bắt buộc với Azure chuẩn vì SDK tự suy ra endpoint từ connection string.

Đặt trong `.env` và luôn bọc connection string bằng dấu nháy vì nó chứa dấu chấm phẩy:

```dotenv
AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"
AZURE_STORAGE_CONTAINER=industrial-safety-evidence
AZURE_STORAGE_PUBLIC_BLOB_ENDPOINT=
AZURE_STORAGE_CREATE_CONTAINER=true
AZURE_STORAGE_SAS_EXPIRES_SECONDS=900
EVIDENCE_ENABLED=auto
```

Không commit `.env` và không gửi connection string qua chat. Account key chỉ được cấp cho backend; trước khi tạo camera process, launcher xóa biến credential khỏi environment để AI process chỉ nhận SAS URL ngắn hạn. Chỉ đặt public endpoint khi dùng custom domain/proxy. Nếu hạ tầng đã tạo container và không muốn backend có quyền tạo container, đặt `AZURE_STORAGE_CREATE_CONTAINER=false`.

Có thể đặt `EVIDENCE_ENABLED=0` để chạy camera/detection/PostgreSQL local mà không capture hoặc upload chứng cứ.

AI uploader là Python HTTP nên không chịu CORS của browser. Dashboard dùng SAS GET từ browser thì Blob service cần CORS cho đúng frontend origin và method `GET`/`HEAD`. Không cần mở browser `PUT` nếu chỉ AI process upload.

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
| `ai_engine/events.py` | EventBus hữu hạn, Bearer HTTP, retry lỗi tạm thời |
| `ai_engine/evidence.py` | Frame sampler, JPEG/MP4 spool và direct-to-Blob uploader |
| `ai_engine/visualization/track_overlay.py` | Bbox/ID/alert compact, không skeleton |
| `backend/models/schemas/event.py` | Typed request schema và validation phía nhận |
| `backend/api/v1/endpoints/internal.py` | Machine API nhận camera/status/safety event |
| `backend/services/violation_service.py` | Idempotency, kiểm tra FK và ghi violation |
| `backend/services/evidence_service.py` | Presign/complete/fail và aggregate evidence status |
| `backend/services/storage_service.py` | Azure SAS GET/PUT và blob-properties verification |
| `backend/models/db/` | ORM camera, zone, violation, system event, evidence metadata |
| `backend/migrations/` | Alembic migration tạo cấu trúc PostgreSQL |
| `docker-compose.yml` | PostgreSQL, Adminer, backend và Triton local; Azure config cho evidence |
| `triton_model_repo/yolo_pose/` | Triton repository cho pose |
| `triton_model_repo/fall_model/` | Triton repository cho fall |
| `run_pipeline_demo.sh` | Smoke test camera → PostgreSQL local + Azure evidence |

## 11. Chạy và kiểm tra end-to-end

Script tự build/start PostgreSQL, Adminer, backend và Triton local; chờ backend database-ready và hai Triton model-ready; đăng ký camera bằng service token; sau đó mới tạo camera process.

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

Bật cả PPE:

```bash
LAYER2_MODELS=zone,fall,ppe ./run_pipeline_demo.sh --camera 1:cam1:0 --show
```

Evidence bật mặc định và yêu cầu `AZURE_STORAGE_CONNECTION_STRING` trong `.env`. Có thể chỉ rõ:

```bash
EVIDENCE_ENABLED=1 LAYER2_MODELS=zone,fall,ppe \
  ./run_pipeline_demo.sh --camera 1:cam1:0 --show
```

Log cuối mỗi camera có `evidence_capture` và `evidence_uploader` stats. `uploaded > 0` nghĩa là backend đã complete; `failed > 0` thì xem `evidence_spool/` và bảng `evidence_objects.failure_reason`.

Sau khi có alert, xem JSON tại `GET http://localhost:8080/api/v1/violations`, OpenAPI tại `http://localhost:8080/docs`, hoặc mở Adminer tại `http://localhost:8081` với:

| Ô Adminer | Giá trị local mặc định |
|---|---|
| System | PostgreSQL |
| Server | `postgres` |
| Username | `postgres` |
| Password | `industrial_safety_dev` |
| Database | `industrial_safety` |

Adminer chạy trong Docker network nên trường Server là `postgres`, không phải `localhost`. Có thể đổi mọi credential/port qua file `.env` dựa trên `.env.example`. Không dùng secret mặc định ở production.

Nếu chỉ chạy module Python mà không truyền `--backend-event-url`, preview Layer 0–2 vẫn chạy nhưng không publish database. `run_pipeline_demo.sh` luôn bật đường backend. Dùng `--skip-camera-registration` khi camera đã được quản trị sẵn và không muốn launcher update source/toggle.

## 12. Quy tắc thay đổi contract

- Không thêm field “để phòng sau này” nếu chưa có consumer hoặc chức năng rõ ràng.
- Thêm/đổi/xóa field event phải sửa dataclass, serialization test, tài liệu và backend consumer trong cùng thay đổi tích hợp.
- Frame/task chứa `numpy.ndarray` chỉ dùng nội bộ, không JSON serialize.
- Safety Event là immutable (`frozen=True`) để thread khác không sửa event sau khi publish.
- `event_id` xử lý retry/idempotency; `captured_at` xử lý thời gian; hai field này không thay cho nhau.

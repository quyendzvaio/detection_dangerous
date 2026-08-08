# Luồng chi tiết tổng quan hệ thống VisionGuard AI

> Tài liệu này mô tả luồng đang được triển khai trong source code. Sơ đồ chỉnh sửa trực quan nằm tại [docs/architecture/system-architecture.drawio](architecture/system-architecture.drawio).

## 1. Bức tranh tổng thể

VisionGuard AI nhận video từ camera USB, file video hoặc RTSP/HTTP; xử lý realtime theo từng camera; phát hiện người, theo dõi người và chạy các nhánh phân tích an toàn. Sự kiện an toàn được gửi về FastAPI, lưu vào PostgreSQL, phát realtime qua WebSocket cho React và có thể tạo evidence trong Azure Blob Storage.

Luồng runtime chính:

```text
Camera / video stream
  → Layer 0: OpenCV capture, reconnect, latest-frame buffer
  → Layer 1: YOLO pose inference + decode/NMS + BoT-SORT tracking
  → Layer 2: bounded queues theo camera
       ├─ Restricted Zone
       ├─ Fall
       └─ PPE (bật theo từng camera)
  → typed SafetyEvent
  → EventBus / HTTP internal endpoint của FastAPI
  → PostgreSQL, evidence workflow, WebSocket dashboard
```

Mỗi camera có runtime độc lập và bộ toggle `zone`, `fall`, `ppe`. Tắt một nhánh sẽ tăng epoch của nhánh, xóa queue tương ứng và bỏ qua task cũ; do đó việc bật/tắt model của camera này không làm thay đổi camera khác.

## 2. Client và API

1. Operator đăng nhập trên React 19 + React Router.
2. React gọi REST API của FastAPI để đọc camera, zone, violations, reports và cấu hình model.
3. Live view dùng WebSocket; frontend có REST snapshot fallback.
4. Hook `useAlertsRealtime` nhận alert/event mới và cập nhật dashboard, violation list và trạng thái camera.
5. Backend trả SAS URL hoặc metadata evidence để frontend hiển thị file riêng tư; secret không đưa vào tài liệu hay UI.

FastAPI chạy trên cổng nội bộ mặc định `8080`, frontend được phục vụ qua Nginx ở cổng mặc định `3000` của host.

## 3. Ingestion và Layer 0

`CameraStream`/Layer 0 đọc frame từ nguồn đã cấu hình. OpenCV chịu trách nhiệm mở thiết bị/URL, đọc frame, reconnect khi mất kết nối và giữ frame mới nhất để tránh backlog. Frame được gắn `camera_id`, `camera_key`, timestamp, kích thước và source metadata.

Bounded queue dùng chiến lược drop-oldest: khi consumer chậm, frame cũ bị bỏ để ưu tiên dữ liệu mới. Đây là lựa chọn realtime, không phải hàng đợi đảm bảo xử lý từng frame.

## 4. Layer 1: nhận diện và tracking

Mỗi frame được letterbox về `640×640`, chuyển BGR → RGB, đổi sang tensor `UINT8` dạng CHW và gửi gRPC đến Triton model `yolo_pose`. Output `(56, 8400)` được decode thành bbox, confidence và 17 keypoint COCO; sau đó áp dụng NMS và hoàn nguyên tọa độ về frame gốc.

BoT-SORT chạy ở phía Python/edge, không chạy trong Triton. Tracker tạo `track_id` theo camera và tạo `TrackedFrame` chứa danh sách người, bbox, keypoint, frame gốc và timestamp.

## 5. Layer 2 và fan-out theo camera

`Layer2Runtime.dispatch()` không chặn pipeline chính. Với mỗi person và model toggle đang bật, runtime đẩy task vào queue riêng:

- `ZoneTask`: bbox, camera, timestamp và kích thước frame để kiểm tra polygon zone.
- `FallTask`: 17 keypoint và track ID để đưa vào temporal fall pipeline.
- `PpeTask`: crop thân người, keypoint tương đối và timestamp. PPE được giới hạn bởi `ppe_interval_s` (mặc định 2 giây).

Mỗi branch có consumer thread riêng, queue giới hạn mặc định 32 phần tử, metric dispatched/dropped/processed và queue depth.

## 6. Sinh và vận chuyển sự kiện

Các branch không ghi database trực tiếp. Chúng phát các kiểu sự kiện trong `ai_engine/contracts/event_schema.py`:

- `RestrictedZoneEvent` khi track nằm trong zone.
- `FallSuspectedEvent` cho cảnh báo nghi ngờ ngã.
- `FallDetectedEvent` cho critical fall.
- `PPEViolationEvent` với các mã helmet, glasses, gloves, vest.

Callback của runtime đưa event vào EventBus/HTTP internal endpoint. Backend xác thực service token, chuẩn hóa schema, ghi violation/system event và phát alert tới WebSocket. Cơ chế retry nằm ở lớp gửi event; queue runtime vẫn ưu tiên frame mới.

## 7. Evidence và lưu trữ

Evidence workflow tách metadata và binary:

1. Event hoặc thao tác người dùng tạo yêu cầu presign.
2. Backend tạo SAS URL có thời hạn và metadata evidence trong PostgreSQL.
3. Worker/uploader gửi frame hoặc clip lên Azure Blob bằng SAS.
4. Backend verify/complete upload và đánh dấu trạng thái evidence.
5. Frontend nhận SAS URL khi có quyền và hiển thị evidence.

Azure có thể không cấu hình ở môi trường local; khi đó metadata/event vẫn có thể tồn tại nhưng upload sẽ không hoàn tất.

## 8. Retention, health và vận hành

Retention worker chạy theo chu kỳ cấu hình. Mặc định violations quá 3 ngày bị xóa; nếu tổng số đạt 1000 thì giữ lại 500 bản ghi mới nhất. Đây là cleanup dữ liệu vi phạm, không xóa model hoặc source evidence một cách tự động ngoài policy đã cấu hình.

Backend có health/readiness endpoint. Triton cung cấp HTTP/gRPC và metrics cổng `8002`. Docker Compose khởi chạy PostgreSQL, Adminer, backend, frontend và Triton; volume PostgreSQL giữ dữ liệu qua lần restart.

## 9. Luồng offline

Notebook và script export là luồng offline: huấn luyện fall model, export PyTorch/Keras sang ONNX, sau đó đặt model vào `triton_model_repo/`. Luồng này không nằm trên đường xử lý realtime và không được gọi bởi dashboard.

## 10. Các điểm cần hiểu đúng

- Tracking ID là local theo camera; không đồng nghĩa với định danh người bền vững giữa các camera.
- Queue bounded có thể bỏ frame cũ để giữ độ trễ thấp.
- Toggle model áp dụng theo từng camera.
- PPE mặc định tắt trong `ModelToggles`; fall và zone mặc định bật.
- Sự kiện cảnh báo đi qua backend trước khi được lưu và phát tới frontend.

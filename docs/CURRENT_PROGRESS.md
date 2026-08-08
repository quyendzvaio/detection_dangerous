# Báo cáo tiến độ hiện tại

Cập nhật: 2026-08-02  
Nhánh làm việc: `develop`

## Tổng quan

Luồng MVP từ camera/video đến giao diện đã kết nối end-to-end:

```text
Camera → Pose/Tracking → PPE/Fall/Zone → Backend → PostgreSQL/Azure → Web UI
```

## Đã hoàn thành

- Đọc USB camera, video file, RTSP/HTTP; hỗ trợ nhiều camera bằng process riêng và tự reconnect.
- YOLO Pose chạy trên Triton; BoT-SORT tạo local track ID.
- PPE, Fall Detection và Restricted Zone chạy độc lập theo từng camera.
- Bật/tắt nóng PPE/Fall/Zone; queue và overlay cũ được dọn khi tắt.
- Vẽ zone trên raw live frame; tắt model Zone chỉ ẩn/ngừng xử lý, không xóa dữ liệu.
- FastAPI, PostgreSQL, migration Alembic và internal event ingestion.
- Đăng ký/đăng nhập Gmail cơ bản, một loại tài khoản.
- Camera/video CRUD, dashboard, camera grid/fullscreen, overlay và telemetry.
- Trung tâm cảnh báo, chi tiết vi phạm và realtime notification.
- PPE/Zone evidence bằng ảnh; Fall evidence bằng ảnh + video H.264.
- Azure Blob private, upload trực tiếp bằng SAS; PostgreSQL chỉ lưu metadata/storage key.
- Frontend Reports đã tạm gỡ; API summary backend vẫn giữ cho phase sau.

## Trạng thái kiểm thử

- Python: **55 tests passed**.
- Frontend lint: pass.
- Frontend production build: pass.
- Backend/frontend/PostgreSQL Docker healthcheck: healthy.
- Luồng webcam + Triton GPU + live view đã được smoke test.

## Chưa làm / Phase 2

- Re-ID giữa nhiều camera.
- Báo cáo và phân tích nâng cao.
- Nhiều role/phân quyền chi tiết.
- Email/SMS và workflow xác nhận/xử lý cảnh báo.
- Retention policy cho database/evidence.
- HLS/WebRTC và scale backend nhiều replica.
- Browser E2E bằng Playwright/Cypress.

## Lưu ý bàn giao

- PostgreSQL chạy local bằng Docker; Azure chỉ lưu evidence.
- Camera preview hiện dùng JPEG qua WebSocket, phù hợp MVP nhưng chưa tối ưu cho quy mô lớn.
- ID hiện là local track ID trong từng camera; chưa phải danh tính xuyên camera.
- AI runner chạy trên host. Sau khi sửa Python runtime cần dừng và chạy lại `run_pipeline_demo.sh` một lần.
- Các thay đổi trong workspace hiện chưa được commit/push.

Hướng dẫn cài đặt và test sản phẩm xem tại [README](../README.md).

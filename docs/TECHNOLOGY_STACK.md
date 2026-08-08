# Công nghệ sử dụng trong toàn hệ thống

Tài liệu này liệt kê công nghệ đã xác nhận trong repository và vai trò thực tế của từng nhóm.

## 1. Runtime và triển khai

| Công nghệ | Vai trò |
|---|---|
| Python 3.12 | Ngôn ngữ của AI engine, FastAPI backend, worker và tooling. |
| Docker | Đóng gói backend/frontend và tạo môi trường chạy nhất quán. |
| Docker Compose | Điều phối PostgreSQL, Adminer, backend, frontend và Triton trong local/development. |
| Nginx | Serve static build frontend và làm web container ở cổng nội bộ 80/host mặc định 3000. |
| NVIDIA Triton Server 24.01 | Model serving qua HTTP `8000`, gRPC `8001`, metrics `8002`; mount `triton_model_repo`. |
| NVIDIA GPU runtime | Được Compose khai báo cho Triton khi máy có GPU; không phải dependency bắt buộc của UI. |

Compose healthcheck chờ PostgreSQL trước backend và chờ backend healthy trước frontend. Volume `industrial_safety_postgres_data` giữ dữ liệu database qua restart.

## 2. Camera và xử lý video

| Công nghệ | Vai trò |
|---|---|
| OpenCV | Mở camera USB, file, RTSP/HTTP; resize, màu, crop, reconnect và frame capture. |
| NumPy | Tensor, bbox/keypoint, NMS, normalize pose, interpolation, motion features và polygon math. |
| BoT-SORT/BoxMOT adapter | Theo dõi người qua frame, tạo track ID theo camera và duy trì state ngắn hạn. |
| Bounded queue + Python threads | Tách nhánh zone/fall/PPE; drop-oldest để giữ latency realtime khi consumer chậm. |

Frame không bị buộc phải xử lý hết. Thiết kế ưu tiên frame mới và độ trễ thấp hơn việc xử lý đầy đủ lịch sử.

## 3. AI và model serving

| Công nghệ/model | Vai trò |
|---|---|
| YOLO pose ONNX (`yolo_pose`) | Phát hiện người và 17 COCO keypoint trên toàn frame. |
| Triton gRPC client | Gửi tensor tới model server và nhận output có schema rõ ràng. |
| Compact Temporal Transformer ONNX (`fall_model`) | Phân tích chuỗi keypoint + vận tốc để suy luận ngã theo thời gian. |
| ONNX PPE classifiers | `ppe_head`, `ppe_face`, `ppe_hand`, `ppe_torso` phân loại trang bị đầu, mặt, tay, thân. |
| OSNet Re-ID ONNX | Hỗ trợ nối track/identity khi pipeline tracking sử dụng; không tự tạo safety event. |
| PyTorch/Keras → ONNX export scripts | Offline export model để Triton load; không nằm trên runtime path. |

Triton tách inference khỏi process API/AI. Python giữ preprocessing, decode, temporal state, tracking và quyết định event vì các phần này cần state theo camera/track.

## 4. Backend/API

| Công nghệ | Vai trò |
|---|---|
| FastAPI | REST API, internal event ingestion, auth endpoints, camera/zone/violation/report/evidence endpoints và health. |
| Uvicorn | ASGI server chạy FastAPI. |
| Pydantic v2 | Validate request/response và typed event/config schema. |
| SQLAlchemy 2 | ORM/session và truy vấn model database. |
| Alembic | Migration cho camera, zone, violation, evidence, telemetry và schema alignment. |
| psycopg2-binary | Driver PostgreSQL cho SQLAlchemy. |
| Python WebSocket | Phát alert/live status realtime cho frontend. |
| bcrypt + JWT/security helpers | Hash mật khẩu và xác thực phiên/token; secret lấy từ environment, không hard-code trong tài liệu. |

Backend nhận event từ AI qua contract typed và internal authentication, sau đó quyết định lưu violation, system event và evidence metadata. AI engine không kết nối trực tiếp tới bảng database trong runtime chính.

## 5. Database, evidence và cloud

| Công nghệ | Vai trò |
|---|---|
| PostgreSQL 16 | Lưu user, camera, zone, violation, system event, evidence metadata và telemetry liên quan. |
| Adminer | Giao diện quản trị database local/development, không nằm trên đường runtime chính. |
| Azure Blob Storage SDK | Tạo container, SAS/presign, upload/verify evidence và truy xuất blob private. |
| SAS URL | Cấp quyền upload/download có thời hạn mà không đưa storage credential cho browser. |
| Retention worker | Xóa violation cũ hơn policy hoặc cắt số lượng khi vượt ngưỡng; mặc định 3 ngày, 1000 → giữ 500. |

Binary evidence nằm ở Blob; PostgreSQL giữ record và trạng thái. Azure là tùy chọn theo environment, nên local không cấu hình Azure sẽ không thể hoàn tất upload thật.

## 6. Frontend

| Công nghệ | Vai trò |
|---|---|
| React 19 | Component UI cho dashboard, camera, violations, AI model toggle, settings, help và auth. |
| TypeScript | Kiểu hóa component, API types, state và event payload. |
| Vite | Dev server và production build/bundle frontend. |
| React Router 6 | Protected route, auth layout và điều hướng trang. |
| PostCSS/CSS Modules | Style component, layout responsive, theme và màn hình nghiệp vụ. |
| WebSocket hook `useAlertsRealtime` | Nhận alert/event realtime; REST snapshot là fallback khi WebSocket không dùng được. |
| Fetch/API service layer | Đóng gói gọi FastAPI, auth token, camera/zone/evidence/violation/report. |

Frontend không gọi Triton trực tiếp. Mọi quyền, dữ liệu vi phạm và SAS URL đều đi qua FastAPI.

## 7. Protocol và cổng chính

- Camera: USB, file video, RTSP/HTTP.
- Frontend → backend: HTTP REST và WebSocket.
- AI → Triton: gRPC `8001`; Triton cũng mở HTTP `8000`.
- Triton metrics: `8002`.
- Backend → PostgreSQL: PostgreSQL protocol `5432`.
- Backend/uploader → Azure: Azure Blob HTTPS/SAS.
- Frontend container: Nginx port 80, ánh xạ host mặc định `3000`.
- Backend host mặc định `8080`; Adminer host mặc định `8081`.

## 8. Những công nghệ không có trong runtime hiện tại

Repository không xác nhận Redis, Kafka, RabbitMQ, Prometheus, Grafana, email/SMS provider hoặc Kubernetes. Không nên đưa các thành phần này vào kiến trúc triển khai hiện tại nếu chưa có source/config tương ứng.

## 9. Cấu hình và bảo mật

Các giá trị môi trường như database URL, JWT secret, AI service token, Azure connection string, container name và retention policy được đọc từ environment/`.env`. Tài liệu chỉ mô tả tên và vai trò, không ghi giá trị bí mật. Khi triển khai thật cần thay toàn bộ default development secret và giới hạn các port chỉ trên interface phù hợp.

# VisionGuard AI

VisionGuard AI là hệ thống giám sát an toàn công nghiệp theo thời gian thực. Sản phẩm nhận video từ camera USB, file video hoặc RTSP, phát hiện người, theo dõi người và phân tích ba nhóm rủi ro:

- PPE: thiếu mũ, kính, găng tay hoặc áo bảo hộ.
- Fall Detection: cảnh báo nghi ngờ ngã, sau đó chuyển sang nghiêm trọng nếu người vẫn nằm.
- Restricted Zone: phát hiện người đi vào vùng cấm.

Cảnh báo được gửi về FastAPI và lưu trong PostgreSQL. Evidence được lưu trên Azure Blob Storage riêng tư và frontend xem qua SAS URL tạm thời.

## Kiến trúc

```text
Camera / Video / RTSP
        │
        ▼
Layer 0: đọc frame mới nhất, reconnect
        │
        ▼
Layer 1: YOLO Pose trên Triton + BoT-SORT tracking
        │
        ▼
Layer 2: PPE · Fall · Restricted Zone
        │
        ▼
EventBus HTTP + Evidence Uploader
        │
        ▼
FastAPI · PostgreSQL · Azure Blob Storage
        │
        ▼
React UI + WebSocket live view/alerts
```

Mỗi camera chạy trong một process AI riêng. Triton dùng chung các model ONNX; trạng thái tracker và các nhánh phân tích được tách theo camera.

## Tính năng hiện có

- Quản lý camera/video và xem nhiều camera.
- Live frame qua WebSocket, có REST snapshot fallback.
- Hiển thị bbox, track ID, FPS và latency.
- Bật/tắt PPE, Fall và Zone độc lập theo từng camera, áp dụng nóng.
- Vẽ, sửa, bật/tắt và xóa polygon vùng cấm.
- Danh sách cảnh báo, lọc và xem evidence.
- PostgreSQL lưu camera, zone, violation và metadata evidence.
- PPE/Zone tạo ảnh evidence; Fall tạo ảnh và video H.264.
- Retention tự động: xóa violation quá 3 ngày; khi đạt 1.000 violation thì giữ lại 500 bản ghi mới nhất.

Re-ID mạnh giữa nhiều camera và phân quyền nhiều role chưa thuộc luồng MVP hiện tại.

## Yêu cầu

Khuyến nghị Ubuntu/Linux vì camera USB sử dụng V4L2.

Cần có:

- Git.
- Python 3.12 và `venv`.
- Docker Engine và Docker Compose plugin.
- NVIDIA driver, NVIDIA Container Toolkit và GPU tương thích Triton.
- Node.js 22 chỉ cần khi phát triển frontend ngoài Docker.
- `v4l-utils` để kiểm tra camera USB.

Kiểm tra:

```bash
python3 --version
docker --version
docker compose version
nvidia-smi
```

Nếu chỉ chạy backend/frontend và không chạy Triton GPU, vẫn có thể khởi động Docker nhưng pipeline AI sẽ không sẵn sàng.

## Cài đặt

```bash
git clone https://github.com/AE-AI-HIT16/Real-Time-Industrial-Safety-AI-Analytics.git
cd Real-Time-Industrial-Safety-AI-Analytics

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt

cp .env.example .env
chmod +x run_pipeline_demo.sh
```

Các model runtime phải có trong repository:

```text
triton_model_repo/yolo_pose/1/model.onnx
triton_model_repo/fall_model/1/model.onnx
triton_model_repo/ppe_head/1/model.onnx
triton_model_repo/ppe_face/1/model.onnx
triton_model_repo/ppe_hand/1/model.onnx
triton_model_repo/ppe_torso/1/model.onnx
```

Không commit `.env`, connection string Azure hoặc mật khẩu thật.

## Cấu hình `.env`

`.env.example` đã có cấu hình local mặc định. Các giá trị quan trọng:

```dotenv
POSTGRES_USER=postgres
POSTGRES_PASSWORD=industrial_safety_dev
POSTGRES_DB=industrial_safety
BACKEND_PORT=8080
FRONTEND_PORT=3000
ADMINER_PORT=8081

AI_SERVICE_TOKEN=local-ai-service-token-change-me
JWT_SECRET=local-jwt-secret-change-me
BACKEND_EVENT_URL=http://localhost:8080/api/v1/internal/events

# Không dùng Azure khi test nhanh
EVIDENCE_ENABLED=0
LAYER2_MODELS=zone,fall

# Retention mặc định
VIOLATION_RETENTION_DAYS=3
VIOLATION_MAX_COUNT=1000
VIOLATION_KEEP_COUNT=500
VIOLATION_RETENTION_INTERVAL_SECONDS=3600
```

### Chạy không dùng Azure

Đặt `EVIDENCE_ENABLED=0`. Detection, live view và PostgreSQL vẫn hoạt động nhưng evidence sẽ không upload lên Azure.

### Chạy đầy đủ evidence Azure

Tạo Azure Storage Account, lấy connection string tại `Access keys`, rồi điền:

```dotenv
AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"
AZURE_STORAGE_CONTAINER=industrial-safety-evidence
AZURE_STORAGE_CREATE_CONTAINER=true
EVIDENCE_ENABLED=1
```

Container nên để private. Backend giữ connection string và chỉ cấp SAS URL ngắn hạn cho frontend.

## Chạy sản phẩm

Cú pháp camera:

```text
--camera CAMERA_ID:CAMERA_KEY:SOURCE
```

`CAMERA_ID` phải duy nhất; `CAMERA_KEY` không chứa dấu `:`; `SOURCE` là camera index, thiết bị V4L2, file video hoặc URL RTSP.

### Camera USB

```bash
v4l2-ctl --list-devices
ls -l /dev/video* /dev/v4l/by-id/ 2>/dev/null
```

Có thể chạy bằng index:

```bash
./run_pipeline_demo.sh --camera 1:usb-c920:0 --show
```

Nếu index camera thay đổi khi rút/cắm, dùng đường dẫn ổn định dưới `/dev/v4l/by-id/`.

### Hai camera

```bash
./run_pipeline_demo.sh \
  --camera 1:usb-c920:0 \
  --camera 2:laptop-cam:2 \
  --show
```

Bỏ `--show` nếu chỉ xem live view trên web:

```bash
./run_pipeline_demo.sh --camera 1:usb-c920:0
```

### File video

Dùng đường dẫn tuyệt đối:

```bash
./run_pipeline_demo.sh \
  --camera 1:fall-demo:/absolute/path/to/fall.mp4 \
  --show
```

### RTSP

```bash
./run_pipeline_demo.sh \
  --camera 1:gate:rtsp://user:password@host/stream \
  --show
```

Script sẽ build/start PostgreSQL, Adminer, backend, frontend và Triton; chờ backend/database/model sẵn sàng rồi mới khởi động process camera.

## Truy cập giao diện

| Thành phần | Địa chỉ |
|---|---|
| Product UI | http://localhost:3000 |
| Swagger API | http://localhost:8080/docs |
| Backend readiness | http://localhost:8080/health/ready |
| Adminer | http://localhost:8081 |
| Triton HTTP | http://localhost:8000 |
| Triton metrics | http://localhost:8002/metrics |

Lần đầu sử dụng:

1. Mở `http://localhost:3000/register`.
2. Tạo tài khoản và đăng nhập.
3. Vào Cameras để xem live view.
4. Bật/tắt PPE, Fall hoặc Zone trên đúng camera.
5. Vào Violations để xem cảnh báo và evidence.

## Luồng cảnh báo Fall

- Model fall xác nhận bước đầu bằng debounce 2/3 lần dự đoán → tạo `FALL_SUSPECTED` với mức `WARNING`.
- Nếu cùng track có tư thế nằm hợp lệ liên tục 5 giây → tạo thêm `FALL_DETECTED` với mức `CRITICAL`.
- Người đứng lại ổn định 2 giây → incident trở về bình thường.
- Warning và critical là hai event/evidence riêng; critical không sửa đè record warning.
- Nếu tracker mất ID hoặc keypoint bị che khuất quá nhiều, việc chuyển critical có thể bị trì hoãn.

## Kiểm tra model theo camera

Trên giao diện, trạng thái toggle sẽ chuyển `PENDING` rồi `APPLIED` sau khi process camera nhận cấu hình. Tắt model chỉ tắt nhánh phân tích tương ứng; pose/tracking Layer 1 vẫn có thể còn bbox và track ID.

## Kiểm tra database và evidence

Trong Adminer dùng:

```text
System: PostgreSQL
Server: postgres
Username: POSTGRES_USER
Password: POSTGRES_PASSWORD
Database: POSTGRES_DB
```

Các bảng chính:

- `cameras`
- `zones`
- `violations`
- `evidence_objects`
- `system_events`
- `users`

PPE/Zone thường có ảnh; Fall warning có ảnh, Fall critical có ảnh và video. Evidence cần có trạng thái `READY` mới xem được.

## Kiểm thử code

```bash
PYTHONPATH=. .venv/bin/pytest -q
docker compose config --quiet
```

Frontend:

```bash
cd frontend
npm ci
npm run lint
npm run build
cd ..
```

## Dừng và reset

Dừng process camera bằng `Ctrl+C` hoặc phím `q` trong cửa sổ OpenCV. Dừng container nhưng giữ database:

```bash
docker compose down
```

Không dùng `docker compose down -v` nếu muốn giữ PostgreSQL; tùy chọn `-v` xóa volume database.

Nếu chỉ muốn chạy các container đã build sẵn khi Docker Hub đang lỗi:

```bash
docker compose up -d --no-build postgres adminer backend frontend triton-server
```

## Lỗi thường gặp

### Docker không tải được base image

Lỗi `lookup auth.docker.io ... i/o timeout` là lỗi DNS/mạng của Docker, không phải lỗi camera. Kiểm tra mạng Docker, thử lại hoặc dùng `--no-build` nếu image đã có local.

### Backend không ready

```bash
docker compose logs --tail=200 backend postgres
curl http://localhost:8080/health/ready
```

### Triton không ready

```bash
docker compose logs --tail=200 triton-server
nvidia-smi
curl http://localhost:8000/v2/health/ready
```

Kiểm tra NVIDIA Container Toolkit và model trong `triton_model_repo/`.

### Không mở được camera

```bash
v4l2-ctl --list-devices
fuser /dev/video0
```

Đóng ứng dụng đang giữ camera như OBS/Chrome/Cheese và thử đường dẫn `/dev/v4l/by-id/`.

### Evidence không upload

Kiểm tra connection string Azure, `EVIDENCE_ENABLED`, log backend và bảng `evidence_objects`:

```bash
docker compose logs --tail=200 backend
```

## Tài liệu liên quan

- [Tiến độ hiện tại](docs/CURRENT_PROGRESS.md)
- [Pipeline và event contract](docs/PRODUCT_PIPELINE.md)
- [Backend product contract](docs/BACKEND_PRODUCT_CONTRACT.md)
- [Phân rã chức năng AI](docs/AI_PRODUCT_FEATURE_DECOMPOSITION.md)
- [Onboarding Layer 5–6](docs/TEAM_ONBOARDING_LAYER5_6.md)
- [API specification](specs/001-industrial-safety-api/spec.md)

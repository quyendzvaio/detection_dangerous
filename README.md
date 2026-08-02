# VisionGuard AI — Industrial Safety Monitoring

VisionGuard AI là hệ thống giám sát an toàn từ camera/video. Hệ thống nhận frame, phát hiện và theo dõi người, phân tích PPE/ngã/vùng cấm, lưu cảnh báo vào PostgreSQL và lưu bằng chứng lên Azure Blob Storage.

Luồng sản phẩm hiện tại:

```text
Camera / Video / RTSP
        │
        ▼
Layer 0: đọc nguồn, giữ frame mới nhất, tự reconnect
        │
        ▼
Layer 1: YOLO Pose trên Triton + BoT-SORT tracking
        │
        ▼
Layer 2: PPE ─ Fall Detection ─ Restricted Zone
        │
        ▼
EventBus HTTP + evidence uploader
        │
        ▼
FastAPI ─ PostgreSQL local ─ Azure Blob Storage
        │
        ▼
React UI + WebSocket live view/alerts
```

Mỗi camera chạy trong một process Python độc lập. Các process dùng chung Triton Inference Server trên GPU nhưng có queue, tracker và trạng thái phân tích riêng.

## 1. Chức năng đang có

- Đăng ký/đăng nhập cơ bản bằng Gmail và mật khẩu; một loại tài khoản.
- Camera/video CRUD, xem một camera, grid nhiều camera và phóng to.
- Live frame qua WebSocket, có REST snapshot fallback.
- Hiển thị bbox, local track ID, FPS, pose/tracker latency và end-to-end latency.
- Bật/tắt toàn bộ overlay trên giao diện.
- Bật/tắt PPE, Fall và Zone độc lập theo từng camera, áp dụng nóng khoảng 1 giây.
- Vẽ/sửa/bật/tắt/xóa polygon vùng cấm trên hình camera trực tiếp.
- Phát hiện vi phạm PPE: mũ, kính, găng tay và áo bảo hộ.
- Phát hiện ngã theo chuỗi keypoint thời gian.
- Phát hiện người đi vào vùng cấm.
- Danh sách cảnh báo, lọc và xem chi tiết evidence.
- PPE/Zone lưu ảnh; Fall lưu ảnh và video H.264 tương thích trình duyệt.
- PostgreSQL lưu camera, zone, cảnh báo, trạng thái và metadata evidence.
- Azure Blob Storage lưu file evidence bằng container private và SAS URL ngắn hạn.

Chưa thuộc MVP: Re-ID giữa nhiều camera, phân quyền nhiều role, báo cáo nâng cao, email/SMS, workflow xác nhận cảnh báo và retention policy.

## 2. Yêu cầu môi trường

Khuyến nghị Ubuntu/Linux vì camera USB dùng V4L2.

Cần cài:

- Git.
- Python 3.12 và module `venv`.
- Docker Engine và Docker Compose plugin.
- NVIDIA GPU, NVIDIA driver và NVIDIA Container Toolkit.
- Node.js 22 chỉ cần khi phát triển/test frontend ngoài Docker.
- `v4l-utils` được khuyến nghị để tìm camera USB.

Kiểm tra nhanh:

```bash
python3 --version
docker --version
docker compose version
nvidia-smi
```

Triton trong `docker-compose.yml` yêu cầu GPU. Nếu `nvidia-smi` hoặc Docker GPU chưa hoạt động, Triton sẽ không khởi động được.

## 3. Chuẩn bị source code

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

Các model runtime phải tồn tại tại:

```text
triton_model_repo/yolo_pose/1/model.onnx
triton_model_repo/fall_model/1/model.onnx
triton_model_repo/ppe_head/1/model.onnx
triton_model_repo/ppe_face/1/model.onnx
triton_model_repo/ppe_hand/1/model.onnx
triton_model_repo/ppe_torso/1/model.onnx
```

Nếu repository sau này dùng Git LFS cho model, chạy `git lfs pull` sau khi clone.

## 4. Cấu hình `.env`

Không commit file `.env`. Các giá trị tối thiểu cho local development đã có trong `.env.example`.

### Test nhanh không dùng Azure

Mở `.env` và đặt:

```dotenv
EVIDENCE_ENABLED=0
LAYER2_MODELS=zone,fall,ppe
```

Detection, live view và lưu cảnh báo PostgreSQL vẫn chạy. Evidence sẽ không được upload và cảnh báo có thể giữ trạng thái `PROCESSING`.

### Test đầy đủ với Azure evidence

Tạo Azure Storage Account và lấy connection string tại:

```text
Azure Portal
→ Storage accounts
→ chọn storage account
→ Security + networking
→ Access keys
→ Connection string
```

Điền vào `.env`:

```dotenv
AZURE_STORAGE_CONNECTION_STRING="DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...;EndpointSuffix=core.windows.net"
AZURE_STORAGE_CONTAINER=industrial-safety-evidence
AZURE_STORAGE_CREATE_CONTAINER=true
EVIDENCE_ENABLED=1
LAYER2_MODELS=zone,fall,ppe
```

Container Azure được để private. Frontend không nhận connection string; backend chỉ sinh SAS URL tạm thời khi người dùng mở evidence.

## 5. Chọn nguồn camera/video

Cú pháp mỗi nguồn:

```text
--camera CAMERA_ID:CAMERA_KEY:SOURCE
```

- `CAMERA_ID`: số nguyên duy nhất, đồng thời là ID trong PostgreSQL.
- `CAMERA_KEY`: tên kỹ thuật duy nhất, không chứa dấu `:`.
- `SOURCE`: index USB, đường dẫn thiết bị, file video tuyệt đối hoặc URL RTSP/HTTP.

### Camera USB

Liệt kê thiết bị:

```bash
v4l2-ctl --list-devices
ls -l /dev/video*
ls -l /dev/v4l/by-id/ /dev/v4l/by-path/
```

Ưu tiên `/dev/v4l/by-id/...-video-index0` thay vì số `0`, `2`, `4` vì Linux có thể đổi index sau khi rút/cắm camera.

Ví dụ một camera USB:

```bash
./run_pipeline_demo.sh --camera 1:gate:0 --show
```

Ví dụ camera laptop và camera USB chạy đồng thời:

```bash
./run_pipeline_demo.sh \
  --camera 1:usb-c920:0 \
  --camera 2:laptop-cam:2 \
  --show
```

### Video file

Dùng đường dẫn tuyệt đối:

```bash
./run_pipeline_demo.sh \
  --camera 1:fall-demo:/absolute/path/to/fall.mp4 \
  --show
```

Video file chạy theo FPS gốc và kết thúc ở EOF.

### RTSP/HTTP

```bash
./run_pipeline_demo.sh \
  --camera 1:gate:rtsp://user:password@host/stream \
  --show
```

Không đưa URL chứa tài khoản/mật khẩu thật vào Git hoặc tài liệu chia sẻ.

## 6. Chạy toàn bộ sản phẩm

Lệnh sau sẽ:

1. Đọc `.env`.
2. Build/start PostgreSQL, Adminer, backend, frontend và Triton.
3. Chờ backend/database và model Triton sẵn sàng.
4. Tạo một process AI riêng cho mỗi `--camera`.

```bash
./run_pipeline_demo.sh --camera 1:cam1:0 --show
```

Bỏ `--show` nếu chỉ muốn xem camera trên web:

```bash
./run_pipeline_demo.sh --camera 1:cam1:0
```

Các địa chỉ sau sẽ khả dụng:

| Thành phần | Địa chỉ |
|---|---|
| Product UI | <http://localhost:3000> |
| Swagger API | <http://localhost:8080/docs> |
| Backend readiness | <http://localhost:8080/health/ready> |
| Adminer | <http://localhost:8081> |
| Triton HTTP | <http://localhost:8000> |
| Triton metrics | <http://localhost:8002/metrics> |

Lần đầu truy cập UI:

1. Mở `http://localhost:3000/register`.
2. Đăng ký Gmail hợp lệ và mật khẩu tối thiểu 6 ký tự.
3. Đăng nhập.
4. Mở Cameras để xem live view và trạng thái runtime.

## 7. Checklist test sản phẩm

### Camera và overlay

- Camera chuyển sang `ONLINE` và có hình trực tiếp.
- Dashboard/Cameras hiển thị FPS và latency.
- Nút bật/tắt overlay chỉ ẩn/hiện phần vẽ, không dừng model.
- Khi chạy nhiều camera, mỗi camera có card/process riêng.

### Bật/tắt model theo camera

- Bấm PPE/FALL/ZONE trên đúng card camera.
- `Config` chuyển `PENDING`, sau đó thành `APPLIED` trong khoảng 1 giây.
- Tắt Fall/PPE phải xóa cảnh báo tương ứng khỏi overlay.
- Tắt Zone phải ẩn polygon và ngừng cảnh báo zone nhưng không xóa polygon khỏi database.
- Bật lại model không yêu cầu restart pipeline.

Lưu ý: bbox và ID vẫn còn khi tắt cả ba model vì pose/tracking thuộc Layer 1 luôn chạy.

### Zone

1. Mở `Vẽ và quản lý zone`.
2. Kiểm tra raw live frame xuất hiện làm nền.
3. Nhấp ít nhất ba điểm và lưu.
4. Bật Zone và đi vào polygon để tạo cảnh báo.

### Alert, database và evidence

- Mở Violations để xem cảnh báo mới.
- PPE/Zone có ảnh evidence.
- Fall có ảnh và video H.264.
- Evidence mới tạo phải có trạng thái `READY` trước khi xem.
- `image_storage_key`/`video_storage_key` bằng `None` trong log event ban đầu là bình thường; key được backend cập nhật sau upload.

Xem PostgreSQL bằng Adminer:

```text
System: PostgreSQL
Server: postgres
Username: giá trị POSTGRES_USER
Password: giá trị POSTGRES_PASSWORD
Database: giá trị POSTGRES_DB
```

Các bảng thường kiểm tra: `cameras`, `zones`, `violations`, `evidence_objects`, `system_events`, `users`.

## 8. Chạy từng phần

Chỉ khởi động web/database/Triton, chưa chạy camera process:

```bash
docker compose up -d --build
docker compose ps
```

Các demo tầng thấp:

```bash
./run_layer0_demo.sh --source 0 --show
./run_layer0_multi.sh --camera 1:cam1:0 --camera 2:cam2:2 --show
./run_layer1_demo.sh --camera 1:cam1:0 --camera 2:cam2:2 --show
```

Các script tầng thấp dùng cho debug, không thay thế `run_pipeline_demo.sh` khi test sản phẩm end-to-end.

## 9. Kiểm thử code

Python:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
```

Frontend:

```bash
cd frontend
npm ci
npm run lint
npm run build
cd ..
```

Docker Compose:

```bash
docker compose config --quiet
```

Trạng thái test gần nhất được ghi trong [docs/CURRENT_PROGRESS.md](docs/CURRENT_PROGRESS.md).

## 10. Dừng hệ thống

- Nhấn `q` trong cửa sổ OpenCV hoặc `Ctrl+C` tại terminal để dừng AI camera processes.
- Các container Docker vẫn tiếp tục chạy sau khi AI process dừng.
- Dừng container nhưng giữ dữ liệu PostgreSQL:

```bash
docker compose down
```

Không dùng `docker compose down -v` nếu muốn giữ database; tùy chọn `-v` sẽ xóa volume PostgreSQL.

## 11. Lỗi thường gặp

### `Cannot open camera source` hoặc `No such device`

```bash
v4l2-ctl --list-devices
ls -l /dev/video*
fuser /dev/video0
```

Rút/cắm lại camera, đóng OBS/Chrome/Cheese đang giữ thiết bị và ưu tiên đường dẫn `/dev/v4l/by-id/`.

### Triton không ready

```bash
docker compose logs --tail=200 triton-server
nvidia-smi
curl http://localhost:8000/v2/health/ready
```

Kiểm tra NVIDIA Container Toolkit và file model trong `triton_model_repo/`.

### Backend không ready

```bash
docker compose logs --tail=200 backend postgres
curl http://localhost:8080/health/ready
```

### Không thấy code frontend mới

```bash
docker compose up -d --build frontend
```

Sau đó hard-refresh trình duyệt bằng `Ctrl+Shift+R`.

### Evidence không upload hoặc không phát

```bash
docker compose logs --tail=200 backend
```

Kiểm tra Azure connection string, bảng `evidence_objects`, `evidence_status` và file còn lại trong `evidence_spool/`. Chỉ video Fall tạo sau bản H.264 mới chắc chắn phát được trên trình duyệt; clip `mp4v` cũ cần chuyển mã.

## 12. Tài liệu dành cho đội nhóm

- [Tiến độ hiện tại](docs/CURRENT_PROGRESS.md)
- [Pipeline và event contract](docs/PRODUCT_PIPELINE.md)
- [Backend product contract](docs/BACKEND_PRODUCT_CONTRACT.md)
- [Phân rã chức năng AI](docs/AI_PRODUCT_FEATURE_DECOMPOSITION.md)
- [Onboarding Layer 5–6](docs/TEAM_ONBOARDING_LAYER5_6.md)
- [API specification MVP](specs/001-industrial-safety-api/spec.md)

Khi thay đổi contract, cần cập nhật đồng thời schema, producer, consumer, migration, test và tài liệu liên quan trong cùng pull request.

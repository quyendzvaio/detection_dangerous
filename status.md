# Trạng thái bàn giao VisionGuard

> Tài liệu này là điểm bắt đầu cho agent tiếp theo. Đọc toàn bộ file trước khi sửa code.

- Cập nhật lần cuối: **2026-08-02**, múi giờ `Asia/Bangkok`
- Thư mục dự án: `/home/trantung/LearnAI/HITproduct/final_product`
- Nhánh hiện tại: `develop`
- Trạng thái Git: worktree có nhiều thay đổi chưa commit và file mới chưa track. Đây là công việc hiện tại của người dùng, không reset, checkout hoặc ghi đè hàng loạt.
- `status.md` hiện cũng chưa được track. Chỉ commit hoặc push khi người dùng yêu cầu rõ ràng.

## 1. Kết luận nhanh

MVP đã có đường chạy sử dụng được từ camera/video đến giao diện web:

```text
Camera/Video
  -> Layer 0 ingest
  -> Layer 1 pose + tracking qua Triton
  -> Layer 2 zone/fall/PPE
  -> FastAPI internal API
  -> PostgreSQL + Azure Blob evidence
  -> REST/WebSocket
  -> React dashboard
```

Sản phẩm hiện cung cấp:

- Đăng ký/đăng nhập Gmail và password thật; JWT bảo vệ Product API và WebSocket.
- CRUD camera/video, nhận USB, RTSP, HTTP hoặc video file.
- Bật/tắt PPE, fall và zone; cấu hình có revision, desired/applied state, runtime poll và ACK.
- Tạo/sửa/bật/tắt/xóa vùng giám sát bằng polygon normalized trên giao diện.
- Telemetry camera thật gồm trạng thái, processing FPS, latency và thời điểm frame cuối.
- Dashboard có **lưới camera trực tiếp**, không còn chỉ là danh sách trạng thái.
- Trang Camera có grid, phóng toàn màn hình và bật/tắt overlay.
- Alert realtime qua WebSocket; vi phạm, evidence, report, settings và help dùng dữ liệu backend thật.
- Evidence JPEG/MP4 có quy trình presign/upload/complete/fail với Azure Blob khi được cấu hình.
- Frontend production chạy bằng Nginx và proxy REST/WebSocket sang backend.

## 2. Thay đổi gần nhất: grid và độ trễ live view

Người dùng báo hai lỗi:

1. Dashboard không có chế độ xem camera dạng lưới.
2. Xem trực tiếp bằng OpenCV mượt nhưng xem qua web bị giật/lag.

Nguyên nhân đã xác định:

- Dashboard cũ chỉ render danh sách trạng thái camera.
- Frontend cũ gọi REST để tải một JPEG mới mỗi `1000 ms`, nên hình trên web thực tế chỉ khoảng 1 FPS.
- AI runtime trước đó chỉ publish preview mỗi `200 ms`, tối đa 5 FPS.

Giải pháp đã triển khai:

- Thêm grid live camera responsive vào Dashboard.
- Thêm component dùng chung `CameraLiveFrame` cho Dashboard và trang Camera.
- Backend giữ REST snapshot làm fallback nhưng phát frame mới bằng **binary WebSocket** ngay sau khi nhận JPEG từ AI runtime.
- Browser giữ một WebSocket cho mỗi camera/chế độ overlay, nhận Blob JPEG, thay object URL và tự reconnect sau khi mất kết nối.
- JWT của WebSocket được gửi bằng subprotocol `['bearer', token]`, không đặt token trong query string.
- Preview mặc định của AI runtime được nâng lên **10 FPS** và có thể chỉnh bằng `WEB_PREVIEW_FPS` hoặc `--preview-fps` trong khoảng `(0, 30]`.
- Upload frame vẫn chạy trong worker riêng, không chặn vòng xử lý inference. Nếu lần upload trước chưa xong, preview mới bị drop có chủ đích để tránh tích backlog và tăng latency.

Các file chính của thay đổi này:

- `frontend/src/components/CameraLiveFrame.tsx`
- `frontend/src/pages/Dashboard/DashboardPage.tsx`
- `frontend/src/pages/Dashboard/DashboardPage.module.css`
- `frontend/src/pages/Cameras/CamerasPage.tsx`
- `backend/ws.py`
- `backend/main.py`
- `backend/api/v1/endpoints/internal.py`
- `ai_engine/pipeline/runner.py`
- `tests/test_product_api.py`

Luồng live frame hiện tại:

```text
AI runner
  -> POST /api/v1/internal/cameras/{camera_id}/frame?overlay=true|false
  -> latest_frames lưu JPEG cuối để REST fallback
  -> camera_frames_manager.broadcast(...)
  -> WS /ws/cameras/{camera_id}?overlay=true|false
  -> CameraLiveFrame hiển thị Blob JPEG
```

Lưu ý: AI gửi cả raw (`overlay=false`) và annotated (`overlay=true`). Mỗi lựa chọn overlay trên UI mở đúng channel tương ứng.

## 3. Dịch vụ và địa chỉ local

Tại thời điểm cập nhật, các container sau đang chạy:

| Service | Địa chỉ | Trạng thái đã kiểm tra |
|---|---|---|
| Frontend/Nginx | `http://localhost:3000` | healthy |
| Backend/FastAPI | `http://localhost:8080` | healthy |
| API docs | `http://localhost:8080/docs` | truy cập qua backend |
| Readiness | `http://localhost:8080/health/ready` | database ready |
| PostgreSQL | `127.0.0.1:5432` | healthy |
| Adminer | `http://localhost:8081` | running |
| Triton HTTP | `http://localhost:8000` | running |
| Triton gRPC | `localhost:8001` | running |
| Triton metrics | `http://localhost:8002` | running |

Kiểm tra nhanh:

```bash
docker compose ps
curl -fsS http://localhost:8080/health/ready
curl -fsSI http://localhost:3000/
docker compose logs --tail=100 backend frontend
```

Backend và frontend đã được rebuild sau thay đổi live WebSocket. Nếu container không còn chạy, dùng:

```bash
docker compose up -d --build postgres adminer backend frontend triton-server
```

## 4. Cách chạy sản phẩm với camera thật

Chuẩn bị `.env` từ `.env.example`. Không hiển thị hoặc ghi connection string Azure ra terminal/log.

Nếu chưa cần evidence cloud:

```bash
EVIDENCE_ENABLED=0 ./run_pipeline_demo.sh --camera 1:cam1:0 --show
```

Nếu `.env` đã có Azure Storage hợp lệ:

```bash
./run_pipeline_demo.sh --camera 1:cam1:0 --show
```

Có thể bỏ `--show` để chỉ xem trên web:

```bash
EVIDENCE_ENABLED=0 ./run_pipeline_demo.sh --camera 1:cam1:0
```

Ví dụ nguồn khác:

```bash
./run_pipeline_demo.sh --camera 2:demo:/absolute/path/video.mp4 --show
./run_pipeline_demo.sh --camera 3:gate:rtsp://user:password@host/stream --show
```

Điều chỉnh preview web:

```bash
WEB_PREVIEW_FPS=15 EVIDENCE_ENABLED=0 ./run_pipeline_demo.sh --camera 1:cam1:0
```

Hoặc:

```bash
./run_pipeline_demo.sh --camera 1:cam1:0 --preview-fps 15
```

Sau khi pipeline chạy, mở `http://localhost:3000`, đăng ký tài khoản Gmail/password nếu chưa có, rồi xem Dashboard hoặc trang Camera. Nếu trình duyệt còn giữ bundle cũ, dùng `Ctrl+Shift+R`.

## 5. API và WebSocket quan trọng

Product API có prefix `/api/v1` và cần JWT người dùng, trừ auth endpoints.

Internal API dành cho AI runtime dùng `Authorization: Bearer <AI_SERVICE_TOKEN>`:

- `PUT /api/v1/internal/cameras/{id}`: đăng ký/cập nhật camera runtime.
- `GET /api/v1/internal/cameras/{id}/runtime-config`: lấy revision và model/zone config.
- `POST /api/v1/internal/cameras/{id}/runtime-config/ack`: ACK config đã áp dụng hoặc thất bại.
- `POST /api/v1/internal/cameras/{id}/telemetry`: gửi FPS, latency và last frame time.
- `POST /api/v1/internal/cameras/{id}/frame?overlay=true|false`: gửi JPEG preview.
- `POST /api/v1/internal/events`: ingest safety event.
- `POST /api/v1/internal/camera-status`: ingest ONLINE/OFFLINE event.

Kênh realtime:

- `/ws/alerts`: event JSON có envelope `message_id`, `event_category`, `occurred_at`, `data`.
- `/ws/cameras/{id}?overlay=true|false`: binary JPEG frames.

REST fallback ảnh cuối:

- `GET /api/v1/cameras/{id}/stream?overlay=true|false`

`backend/frame_store.py` chỉ lưu frame mới nhất trong memory. Restart backend sẽ mất snapshot cho đến khi AI runtime gửi frame kế tiếp; đây là hành vi mong đợi hiện tại.

## 6. Database và migration

- PostgreSQL local dùng volume Docker `industrial_safety_postgres_data`.
- Alembic revision hiện tại đã xác nhận: `20260802_0004`.
- Migration mới đáng chú ý:
  - `20260801_0003_mvp_schema_alignment.py`
  - `20260802_0004_camera_telemetry.py`
- Migration đã được kiểm tra upgrade/downgrade/upgrade trên database tạm ở phiên trước.
- Xóa camera là soft delete để giữ lịch sử cảnh báo.
- Smoke camera ID `990010` đã soft-delete; tài khoản smoke đã xóa khỏi database.

Không xóa volume database hoặc chạy migration phá dữ liệu nếu người dùng chưa yêu cầu.

## 7. Kiểm thử đã hoàn thành

Trạng thái gần nhất:

- Python: **52 passed**.
- Có 1 warning cũ về Starlette `TestClient`/`httpx`; không phải test failure.
- Frontend `oxlint`: pass.
- Frontend TypeScript + Vite production build: pass.
- `git diff --check`: pass.
- Backend Docker build: pass.
- Frontend Docker build: pass.
- Backend, frontend và PostgreSQL healthcheck: healthy.
- Test WebSocket mới xác minh POST frame nội bộ được nhận nguyên bytes tại client camera WebSocket.
- Smoke webcam + GPU/Triton thật ở phiên trước: khoảng **9.2 processing FPS**, **40.8 ms end-to-end**; ONLINE/OFFLINE, telemetry và live JPEG đều tới backend.

Lệnh test chuẩn từ project root:

```bash
PYTHONPATH=. .venv/bin/pytest -q
cd frontend && npm run lint && npm run build
cd .. && docker compose config --quiet
```

Không gọi trực tiếp `.venv/bin/pytest -q` trong môi trường hiện tại mà thiếu `PYTHONPATH=.` vì test collection sẽ không import được `backend` và `ai_engine`. Đây là vấn đề cách gọi lệnh, không phải lỗi code.

## 8. Cấu trúc code cần biết

- `ai_engine/ingest/`: đọc camera/video và latest-frame buffer.
- `ai_engine/inference/`: client gọi model Triton.
- `ai_engine/tracking/`: tracking adapter.
- `ai_engine/pipeline/layer2_runtime.py`: orchestration zone/fall/PPE và hot config.
- `ai_engine/pipeline/runner.py`: CLI/runtime đa camera, telemetry, frame publishing và evidence.
- `backend/api/v1/endpoints/`: Product API và internal runtime API.
- `backend/services/`: business logic.
- `backend/ws.py`: alert fan-out, camera frame fan-out và WebSocket authentication.
- `backend/frame_store.py`: in-memory latest JPEG snapshot.
- `frontend/src/services/`: auth/API/product clients.
- `frontend/src/hooks/useAlertsRealtime.ts`: realtime alert + REST resync.
- `frontend/src/components/CameraLiveFrame.tsx`: realtime camera WebSocket + snapshot fallback.
- `frontend/src/pages/Cameras/ZoneEditor.tsx`: UI chỉnh polygon zone.
- `specs/001-industrial-safety-api/spec.md`: contract MVP và Definition of Done.

Các tài liệu domain/contract quan trọng:

- `docs/PRODUCT_PIPELINE.md`
- `docs/TEAM_ONBOARDING_LAYER5_6.md`
- `docs/BACKEND_PRODUCT_CONTRACT.md`
- `docs/AI_PRODUCT_FEATURE_DECOMPOSITION.md`

## 9. Giới hạn và việc nên kiểm tra tiếp

MVP dùng được, nhưng agent tiếp theo cần biết các giới hạn sau:

- Camera preview là chuỗi JPEG qua WebSocket, chưa phải HLS/WebRTC. Cách này có latency thấp và đủ cho MVP nhưng băng thông tăng theo số camera, số viewer và độ phân giải.
- AI runtime encode và upload cả raw lẫn annotated frame. Với nhiều camera, cần benchmark CPU/network; có thể cần quality/resolution động hoặc chỉ publish mode đang có subscriber.
- `camera_frames_manager` là in-process. Nếu scale backend thành nhiều worker/replica thì internal POST và WebSocket client có thể vào hai process khác nhau. Khi scale cần Redis pub/sub, NATS hoặc broker tương đương, hoặc sticky routing.
- Frontend Dashboard tải tất cả camera vào grid. Với số lượng camera lớn nên thêm paging, virtualisation hoặc lựa chọn layout 2x2/3x3.
- Dashboard refresh telemetry chủ yếu khi load và khi alert/config event tới; trang Camera poll metadata mỗi 3 giây. Nếu cần telemetry realtime hoàn toàn, phát thêm telemetry event hoặc polling riêng cho Dashboard.
- Preview 10 FPS là giá trị mặc định, không bảo đảm 10 FPS thực tế. Worker có chủ đích bỏ frame nếu upload cũ chưa xong; tốc độ cuối phụ thuộc inference FPS, JPEG encoding, mạng và kích thước frame.
- Chưa có browser E2E bằng Playwright/Cypress. Hiện có API/WebSocket integration test, build và kiểm tra HTTP production.
- Nginx có thể log warning `upstream sent duplicate header line: date` trên WebSocket handshake. Kết nối vẫn được accept và hoạt động; đây chưa phải lỗi chức năng.
- Azure evidence phụ thuộc credential thật trong `.env`; không đưa credential vào frontend, tài liệu, Git hoặc output terminal.

## 10. Quy tắc an toàn khi tiếp tục

- Không reset hoặc dọn worktree; thay đổi chưa commit thuộc về người dùng.
- Trước khi sửa file, xem `git diff` của chính file đó để tránh ghi đè công việc đang có.
- Dùng `rg` để tìm code và `apply_patch` để sửa file.
- Không đọc/in `AZURE_STORAGE_CONNECTION_STRING`, JWT secret hay token ra terminal.
- Không commit/push, xóa database/volume, hoặc xóa evidence nếu người dùng chưa yêu cầu.
- Sau thay đổi frontend/backend, chạy test/build rồi rebuild đúng container để UI tại port 3000 nhận code mới.
- Nếu sửa event contract, cập nhật đồng bộ schema, ingestion, serialization tests và `docs/PRODUCT_PIPELINE.md`.

## 11. Checklist tiếp tục phiên làm việc

```text
[ ] Đọc status.md và spec MVP.
[ ] Chạy git status; bảo toàn worktree hiện có.
[ ] Chạy docker compose ps và health endpoints.
[ ] Xác nhận pipeline camera có đang chạy hay chỉ có web stack.
[ ] Nếu kiểm tra live view, bảo đảm AI runner đang gửi frame cho đúng camera ID.
[ ] Sau sửa: PYTHONPATH=. .venv/bin/pytest -q.
[ ] Sau sửa frontend: npm run lint && npm run build.
[ ] Rebuild service bị ảnh hưởng và kiểm tra logs/health.
[ ] Chỉ commit/push khi được người dùng yêu cầu.
```

## 12. Sửa video fall evidence cho trình duyệt (2026-08-02)

Đã hoàn thành ở code:

- Nguyên nhân chính được xác nhận tại `ai_engine/evidence.py`: clip fall trước đây dùng OpenCV `mp4v` (MPEG-4 Part 2), không được Chrome/Edge hỗ trợ ổn định dù file có đuôi `.mp4`.
- Bộ tạo evidence mới dùng FFmpeg đi kèm package `imageio-ffmpeg` để encode H.264 (`libx264`), pixel format `yuv420p` và `faststart`.
- Encode ghi vào file tạm rồi mới atomic replace sang file chính. Nếu FFmpeg lỗi hoặc tạo file rỗng thì file hỏng bị xóa và job không được gửi lên Azure dưới trạng thái thành công.
- Encoder tự pad chiều rộng/chiều cao lẻ sang số chẵn để H.264 `yuv420p` vẫn hoạt động với nguồn video kích thước bất kỳ.
- Đã thêm `imageio-ffmpeg>=0.5,<1` vào `requirements.txt`; package cũng đã được cài vào `.venv` hiện tại.
- Test fall evidence giờ dùng FFmpeg giải mã lại clip và xác nhận codec `h264` cùng pixel format `yuv420p`, thay vì chỉ kiểm tra file có kích thước lớn hơn 0.
- UI Violations ưu tiên video đối với fall evidence, dùng `preload="metadata"`, `playsInline`, hiển thị lỗi phát video và có nút xin lại presigned URL. Ảnh snapshot được đặt trong phần mở rộng bên dưới video để màn hình bớt rối.

Kết quả xác minh:

- Toàn bộ Python test: **52 passed**.
- Frontend TypeScript/Vite build: pass.
- Frontend lint: pass.

Lưu ý vận hành:

- Thay đổi codec chỉ áp dụng cho evidence fall được tạo mới sau bản sửa này.
- Các blob cũ đã encode bằng `mp4v` vẫn không tự chuyển thành H.264. Muốn giữ và xem các clip cũ phải thực hiện một lần transcode rồi upload thay thế; còn để test luồng mới, hãy tạo một sự kiện ngã mới.
- Backend đã có API sinh SAS URL và frontend đã sử dụng API đó; không lưu SAS URL lâu dài trong PostgreSQL.
- Sau khi lấy code ở máy/môi trường khác phải chạy lại `pip install -r requirements.txt` trước khi bật AI runner.

## 13. Sửa hot toggle model và Zone Editor (2026-08-02)

Nguyên nhân đã xác định:

- Frontend từng gửi cả `ppe_enabled`, `fall_enabled`, `zone_enabled` trong mỗi lần bấm một switch. Nếu người dùng bấm liên tiếp, request sau có thể mang hai giá trị cũ và vô tình hoàn tác request trước.
- Polling danh sách camera có thể trả về sau PATCH và ghi đè UI bằng snapshot cũ.
- Layer 2 ngừng dispatch task mới khi model tắt nhưng queue cũ chưa được dọn; một task đang chờ/đang inference vẫn có thể cập nhật overlay hoặc phát event.
- Overlay fall/PPE/zone đã sinh trước đó không được xóa khi nhánh tương ứng bị tắt.
- Polygon zone được renderer vẽ từ cấu hình zone mà không kiểm tra `zone_enabled`.
- Zone Editor trước đây chỉ đặt SVG lên nền đen; nó chưa render `CameraLiveFrame`.

Thay đổi đã hoàn thành:

- UI chỉ PATCH đúng một field mà người dùng vừa bấm; từng switch có trạng thái pending và bị khóa trong lúc request đang chạy.
- Thêm mutation version để response GET cũ không thể ghi đè kết quả toggle mới.
- Runtime config poll mặc định giảm từ 3 giây xuống 1 giây.
- Khi một model bị tắt, Layer 2 xóa queue của nhánh đó và tăng branch epoch. Fall/PPE bỏ kết quả inference cũ nếu config đổi giữa lúc xử lý; fall temporal processor được tạo lại khi bật lại để không trộn chuỗi keypoint trước và sau thời gian tắt.
- Callback đổi model xóa ngay state overlay của đúng nhánh, không phụ thuộc runtime-config ACK thành công. Tắt fall chỉ xóa fall state; không làm mất PPE/zone và ngược lại.
- Polygon chỉ được vẽ khi model Zone của camera đang bật. Dữ liệu zone vẫn giữ nguyên trong PostgreSQL và xuất hiện lại khi bật Zone.
- Zone Editor dùng raw live frame (`overlay=false`) làm nền và đặt SVG polygon lên trên để người dùng chọn tọa độ chính xác. Camera object trong editor cũng được refresh theo polling.

Xác minh:

- Python: **55 passed**.
- Frontend build và lint: pass.
- `git diff --check`: pass.
- Frontend/backend container đã rebuild và backend healthy; frontend image mới đã được triển khai.

Lưu ý kiểm tra thủ công:

- AI pipeline đang chạy là process Python trên host, không nằm trong frontend/backend container. Cần dừng phiên runner cũ và chạy lại `run_pipeline_demo.sh` một lần để nạp code mới. Sau đó toggle sẽ hoạt động nóng, không cần restart cho mỗi lần bật/tắt.
- Khi bấm switch, UI thể hiện desired state ngay; `Config` chuyển `PENDING` rồi `APPLIED` sau tối đa khoảng 1 giây khi camera process ACK.

## 14. Tạm gỡ Reports khỏi frontend (2026-08-02)

- Đã bỏ mục `Reports` khỏi sidebar, page title và router frontend.
- Đã xóa module `frontend/src/pages/Reports/` và export liên quan.
- Route `/reports` không còn là chức năng của UI MVP hiện tại.
- Không xóa endpoint reports phía backend để giữ khả năng tái sử dụng ở phase 2.
- Dashboard vẫn giữ chỉ số vận hành nhanh `Tổng cảnh báo`; đây không phải màn hình báo cáo/phân tích riêng.
- Frontend build và lint: pass; container frontend đã rebuild.

## 15. Tài liệu chạy thử và báo cáo tiến độ (2026-08-02)

- `README.md` đã được viết lại theo luồng clone/cài dependency/cấu hình `.env`/chạy/test/dừng/xử lý lỗi.
- README có hai chế độ: test nhanh không Azure và test đầy đủ có Azure evidence.
- README có ví dụ USB, multi-camera, video file, RTSP, hot model toggle, Zone Editor, Adminer và kiểm tra evidence.
- Tạo `docs/CURRENT_PROGRESS.md` làm báo cáo ngắn cho đội nhóm: phần đã hoàn thành, trạng thái test, Phase 2 và lưu ý bàn giao.
- `.env.example` bổ sung `LAYER2_MODELS`, `RUNTIME_CONFIG_POLL_SECONDS` và `WEB_PREVIEW_FPS`.
- `docs/PRODUCT_PIPELINE.md` đã sửa thông tin codec Fall evidence từ `mp4v` cũ sang H.264 hiện tại.

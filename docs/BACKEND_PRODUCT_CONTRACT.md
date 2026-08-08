# Backend Product Contract và danh mục chức năng sản phẩm

> Trạng thái: **BẢN THẢO ĐỂ THỐNG NHẤT TRƯỚC KHI CODE TIẾP**  
> Phạm vi: Backend/API Layer 5, UI/UX Layer 6 và điểm nối với AI pipeline Layer 0–4  
> Pipeline kỹ thuật: [PRODUCT_PIPELINE.md](PRODUCT_PIPELINE.md)  
> Cấu trúc dự án: [TEAM_ONBOARDING_LAYER5_6.md](TEAM_ONBOARDING_LAYER5_6.md)

## 1. Mục đích

Tài liệu này thống nhất bốn nội dung giữa Backend, AI và UI/UX:

1. Toàn bộ chức năng sản phẩm, từ đăng nhập đến xử lý cảnh báo.
2. Phân biệt phần đã có thật, phần cần hoàn thiện và phần mới dự kiến.
3. Dữ liệu/API Backend cần cung cấp để UI hoạt động.
4. Các quyết định phải chốt trước khi tiếp tục code.

Đây là **product contract**. Nó không thay thế OpenAPI, migration hay event schema. Sau khi chốt, thay đổi contract phải cập nhật đồng thời code, test, OpenAPI và tài liệu.

## 2. Quy ước trạng thái

| Nhãn | Ý nghĩa |
|---|---|
| **ĐÃ CÓ** | Có code và đã có đường chạy kiểm thử trong nhánh develop |
| **CẦN HOÀN THIỆN** | Đã có nền tảng nhưng chưa đủ an toàn hoặc chưa nối hết |
| **DỰ KIẾN MVP** | Nên có trong phiên bản đầu tiên, chưa triển khai đầy đủ |
| **GIAI ĐOẠN SAU** | Không chặn MVP |
| **CẦN CHỐT** | Chưa phải yêu cầu chính thức |

Không được hiểu một mục **DỰ KIẾN** là API đã tồn tại.

## 3. Mục tiêu và giới hạn MVP

Một người vận hành phải có thể:

1. Đăng nhập và chỉ thấy/thực hiện đúng chức năng theo quyền.
2. Xem trạng thái và live view của camera.
3. Nhận cảnh báo PPE, ngã, xâm nhập vùng cấm gần thời gian thực.
4. Xem ảnh/video bằng chứng trên Azure Blob.
5. Review, dismiss hoặc resolve vi phạm.
6. Quản lý camera, toggle model riêng từng camera.
7. Vẽ/sửa zone và đồng bộ xuống pipeline mà không restart toàn hệ thống.
8. Xem báo cáo theo thời gian, camera và loại vi phạm.

Ngoài MVP hiện tại:

- Re-ID, nhận diện khuôn mặt và quản lý danh tính người: **tạm hoãn**.
- SMS/email/cuộc gọi tự động và ứng dụng mobile.
- PostgreSQL cloud; hiện PostgreSQL local.
- Multi-tenant phức tạp.
- Huấn luyện model từ UI và lưu audio.

## 4. Vai trò và quyền đề xuất

| Chức năng | Admin | Operator | Viewer |
|---|:---:|:---:|:---:|
| Login, dashboard, camera/live view | Có | Có | Có |
| Xem violation/evidence/report | Có | Có | Có |
| Review/dismiss/resolve violation | Có | Có | Không |
| Thêm/sửa/xóa camera | Có | Không | Không |
| Toggle model từng camera | Có | Không | Không |
| Tạo/sửa/xóa zone | Có | Không | Không |
| Quản lý user/role/system | Có | Không | Không |

Ma trận này **cần chốt**. Database đã lưu admin, operator, viewer nhưng backend chưa cưỡng chế RBAC theo role.

## 5. Luồng tổng thể

~~~text
User → Login → JWT/RBAC
  │
  ├─ Dashboard / Camera / Violation / Report
  │                              └─ SAS GET → Azure evidence
  │
  └─ Sửa camera/model/zone
          └─ Backend lưu desired config + revision
                    └─ camera process lấy config
                              └─ ACK applied config

Camera/Video → Layer 0 → Layer 1 → Layer 2 → EventBus
                                              │
                                              ▼
                                    FastAPI internal API
                                     │        │
                                     ▼        └─ WebSocket → UI
                                  PostgreSQL
                                     │
                                     └─ presign/verify → Azure Blob
~~~

Desired config là điều người dùng muốn. Applied config là điều camera xác nhận đã áp dụng. UI không được báo “đã bật” chỉ vì database vừa đổi nếu camera offline hoặc chưa ACK.

## 6. Danh mục chức năng từ đăng nhập đến vận hành

### 6.1 Tài khoản và đăng nhập

| Chức năng | Trạng thái | Lưu ý |
|---|---|---|
| Register | **ĐÃ CÓ nhưng cần khóa** | Public và caller hiện có thể chọn role |
| Login | **ĐÃ CÓ** | Username/password trả JWT access token |
| Thông tin user hiện tại | **ĐÃ CÓ** | GET auth/me |
| Logout | **DỰ KIẾN MVP** | Xóa session client; revoke nếu có refresh token |
| Route guard UI | **DỰ KIẾN MVP** | Chưa login chuyển về Login |
| RBAC | **DỰ KIẾN MVP** | Phải kiểm tra ở backend |
| Admin tạo/khóa user | **DỰ KIẾN MVP** | Thay public register |
| Đổi mật khẩu | **DỰ KIẾN MVP** | Xác minh mật khẩu cũ |
| Reset mật khẩu | **GIAI ĐOẠN SAU** | Email hoặc admin reset |
| Refresh token | **CẦN CHỐT** | Khuyến nghị access ngắn + refresh an toàn |
| Audit login | **GIAI ĐOẠN SAU** | Không log password/token |

Khoảng trống bảo mật hiện tại:

- Password hashing chưa dùng Argon2/bcrypt.
- Public register cho phép chọn role.
- Nhiều API đọc, evidence URL và WebSocket chưa yêu cầu JWT.
- Chưa có RBAC đầy đủ, rate limit, refresh/logout server-side.

### 6.2 Dashboard

| Chức năng | Trạng thái | Lưu ý |
|---|---|---|
| Tổng camera/violation/user | **ĐÃ CÓ API summary** | Cần time filter |
| Violation theo type/camera | **ĐÃ CÓ API summary** | Aggregate cơ bản |
| Online/offline count | **DỰ KIẾN MVP** | Dựa vào heartbeat/last seen |
| Alert realtime | **CẦN HOÀN THIỆN** | Có WS broadcast, UI chưa nối, WS chưa auth |
| Bộ lọc thời gian | **DỰ KIẾN MVP** | Today, 7/30 ngày, custom range |
| Biểu đồ xu hướng/top camera | **DỰ KIẾN MVP** | Backend aggregate |

### 6.3 Camera

| Chức năng | Trạng thái | Lưu ý |
|---|---|---|
| List/detail/create/update | **ĐÃ CÓ API** | Read đang public; write chưa admin-only |
| Delete camera | **ĐÃ CÓ** | Soft delete |
| Runtime registration | **ĐÃ CÓ** | Internal AI_SERVICE_TOKEN |
| Online/offline event | **ĐÃ CÓ nền tảng** | Cần heartbeat + timeout |
| Toggle PPE/Fall/Zone | **CÓ field DB** | Chưa hot-sync xuống camera |
| Re-ID toggle | **KHÔNG LÀM HIỆN TẠI** | Hoãn phase sau |
| Test source | **DỰ KIẾN MVP** | Trả kết nối/lỗi/time |
| FPS, latency, last seen | **DỰ KIẾN MVP** | Telemetry thật từ process |
| Nhiều camera | **ĐÃ CÓ ở AI pipeline** | Mỗi camera một process |

Nguồn có thể là USB index, video file hoặc RTSP. Backend không trả credential RTSP nguyên văn cho user không đủ quyền.

### 6.4 Live view và overlay

| Chức năng | Trạng thái | Lưu ý |
|---|---|---|
| Camera UI | **Prototype** | Dữ liệu mock |
| MJPEG generator | **Skeleton** | Chưa route và chưa nhận frame thật |
| Stream MVP | **DỰ KIẾN MVP** | Có thể MJPEG 5–10 FPS; cần auth/topology |
| Stream production | **GIAI ĐOẠN SAU** | WebRTC/HLS/MediaMTX tùy tải |
| Bounding box + track ID | **ĐÃ CÓ ở AI demo** | Chưa có trên web |
| Màu vi phạm | **ĐÃ CHỐT hướng** | Normal xanh; violation đỏ ổn định tới khi hết lỗi |
| PPE label | **ĐÃ CHỐT hướng** | Gom lỗi ngắn trên một nhãn, tránh màn hình rối |
| Skeleton | **ĐÃ BỎ khỏi view** | Keypoint vẫn dùng nội bộ |
| Zone polygon | **ĐÃ CÓ ở AI demo** | Web cần overlay |
| Toggle overlay | **DỰ KIẾN MVP** | Chỉ tắt hình vẽ, không tắt model |

### 6.5 Runtime model config theo camera

AI hiện có:

- PPE: NO_HELMET, NO_GLASSES, NO_GLOVES, NO_VEST.
- Fall: runtime phát FALL_SUSPECTED WARNING ban đầu và FALL_DETECTED CRITICAL nếu vẫn nằm sau 5 giây.
- Zone: track đi vào polygon, event dùng zone_id.

State cần bổ sung:

| Field khái niệm | Ý nghĩa |
|---|---|
| desired_*_enabled | User/backend muốn bật/tắt |
| applied_*_enabled | Camera xác nhận trạng thái thật |
| config_revision | Tăng mỗi lần sửa config |
| applied_revision | Revision camera đã áp dụng |
| config_status | PENDING, APPLIED, FAILED, OFFLINE |
| config_error | Lý do áp dụng thất bại |

Luồng đề xuất:

1. Admin toggle model.
2. Backend ghi desired state, tăng revision.
3. Camera poll mỗi 3–5 giây.
4. Camera áp dụng trong đúng process.
5. Camera ACK revision/applied state/error.
6. UI cập nhật trạng thái thật.

Backend đã có desired/applied toggle, config revision, runtime-config endpoint và ACK; runner polling sẽ áp dụng riêng cho từng camera.

### 6.6 Zone

| Chức năng | Trạng thái | Lưu ý |
|---|---|---|
| List/detail/create/update | **ĐÃ CÓ API** | Polygon ≥3 điểm, normalized [0,1] |
| Delete | **ĐÃ CÓ nhưng cần đổi** | Hiện hard delete; đề xuất soft delete |
| Active toggle | **ĐÃ CÓ field** | Chưa hot-sync |
| Vẽ polygon trên frame | **DỰ KIẾN MVP** | UI đổi pixel sang normalized |
| Nhiều zone/camera | **DB hỗ trợ** | Layer 2 cần nhận danh sách động |
| Zone revision/history | **CẦN CHỐT** | Nên có snapshot để truy vết evidence |

Event chỉ cần zone_id, không cần zone_name. Evidence cũ là snapshot lịch sử; không dùng polygon mới để diễn giải lại sự kiện cũ.

### 6.7 Violation và alert

| Loại | Severity | Dữ liệu riêng | Evidence |
|---|---|---|---|
| PPE_VIOLATION | DANGER | violation_codes[] | JPEG |
| FALL_SUSPECTED | WARNING | confidence | JPEG |
| FALL_DETECTED | CRITICAL | confidence | JPEG + MP4 |
| RESTRICTED_ZONE | DANGER | zone_id | JPEG |

Mọi event có event_id, camera_id, track_id, detected_time. Không dùng schema_version và đã thống nhất bỏ sequence_id. Event_id vẫn bắt buộc để idempotency khi retry.

| Chức năng | Trạng thái | Lưu ý |
|---|---|---|
| Typed event ingest | **ĐÃ CÓ** | Internal token, idempotent bằng event_id |
| Lưu PostgreSQL | **ĐÃ CÓ** | Violation + evidence metadata |
| List/detail | **ĐÃ CÓ API** | Chưa pagination total/time/status filter |
| Update status | **ĐÃ CÓ API** | Chưa enforce transition |
| WebSocket alert | **Có nền tảng** | Chưa JWT/replay/envelope chuẩn |
| Chống alert lặp | **Có một phần ở AI** | Cần test đông người |
| Dismiss reason | **DỰ KIẾN MVP** | Nên bắt buộc |
| Gán người/ghi chú | **GIAI ĐOẠN SAU** | Cần audit |

Workflow đề xuất:

~~~text
NEW ──► REVIEWED ──► RESOLVED
 │          │
 └──────────┴──────► DISMISSED (false alarm + reason)
~~~

Cần chốt transition, quyền và reopen. API hiện có thể đặt thẳng REVIEWED, DISMISSED hoặc RESOLVED.

### 6.8 Evidence và Azure Blob

Luồng **ĐÃ CÓ**:

1. Layer 2 tạo event và evidence spool local.
2. Backend ghi violation.
3. AI client xin SAS upload theo event_id.
4. Upload JPEG/MP4 trực tiếp lên Azure.
5. AI client báo complete.
6. Backend verify blob rồi đổi evidence thành READY.
7. UI xin SAS GET để xem.

| Chức năng | Trạng thái | Lưu ý |
|---|---|---|
| PPE/zone JPEG | **ĐÃ CÓ** | Azure + PostgreSQL metadata |
| Fall JPEG+MP4 | **ĐÃ CÓ** | Đã test Azure thật |
| PROCESSING/READY/FAILED | **ĐÃ CÓ** | Evidence lifecycle |
| Upload presign/complete/fail | **ĐÃ CÓ** | Internal token |
| SAS GET cho UI | **ĐÃ CÓ nhưng public** | Phải thêm JWT/RBAC |
| Retry/spool cleanup | **CẦN HOÀN THIỆN** | Có giới hạn retry/disk |
| Loading/error UI | **DỰ KIẾN MVP** | Chỉ lấy URL khi READY |
| Retention | **CẦN CHỐT** | Xóa Blob/DB nhất quán |
| Audit lượt xem | **GIAI ĐOẠN SAU** | Nếu evidence nhạy cảm |

Không lưu SAS URL vì có hạn. PostgreSQL chỉ lưu object key và metadata. Khuyến nghị SAS GET production 5–15 phút.

### 6.9 Báo cáo

| Chức năng | Trạng thái | Lưu ý |
|---|---|---|
| Summary tổng/type/camera | **ĐÃ CÓ cơ bản** | Chưa time range |
| Filter time/status | **DỰ KIẾN MVP** | Backend aggregate |
| Trend theo giờ/ngày | **DỰ KIẾN MVP** | Không tính toàn bộ ở browser |
| False-positive rate | **GIAI ĐOẠN SAU** | Từ DISMISSED sau khi chốt semantics |
| Export CSV/PDF | **GIAI ĐOẠN SAU** | RBAC/range limit/template |

### 6.10 Realtime/WebSocket

Envelope đề xuất, không có schema_version:

~~~json
{
  "message_id": "uuid",
  "event_category": "SAFETY_EVENT",
  "occurred_at": "2026-08-01T08:00:00Z",
  "data": {}
}
~~~

Category MVP:

- SAFETY_EVENT
- CAMERA_STATUS
- EVIDENCE_STATUS
- CONFIG_STATUS

Cần JWT, reconnect backoff và REST resync. WebSocket chỉ là notification; PostgreSQL/REST là source of truth. Connection manager in-memory hiện phù hợp một backend instance; scale nhiều instance cần Redis pub/sub hoặc broker tương đương.

### 6.11 Vận hành, Settings và Help

| Chức năng | Trạng thái | Lưu ý |
|---|---|---|
| Health/readiness | **ĐÃ CÓ** | /health, /health/ready |
| Swagger/OpenAPI | **ĐÃ CÓ** | /docs, /api/v1/openapi.json |
| PostgreSQL/Adminer local | **ĐÃ CÓ** | Docker Compose |
| Azure Blob cloud | **ĐÃ CÓ** | Secret chỉ trong .env |
| Triton | **ĐÃ CÓ** | Model server |
| Structured log | **CẦN HOÀN THIỆN** | request/camera/event id; không log secret |
| Audit config/status | **DỰ KIẾN MVP** | Ghi user/time/before/after |
| Metrics | **GIAI ĐOẠN SAU** | FPS, latency, drop, error |
| Backup/restore | **CẦN CHỐT** | Lịch và kiểm thử restore |
| Azure lifecycle | **CẦN CHỐT** | Theo retention |
| Settings page | **Prototype** | Không đưa cloud secret lên UI |
| Help page | **Prototype** | Nội dung model cũ cần cập nhật |
| AI Models page | **Có file, chưa route** | Hoãn; toggle tại camera |
| Threshold từ UI | **CẦN CHỐT/SAU** | Chỉ admin, validate/audit/version |

## 7. API hiện có

### 7.1 Client-facing

| Method | Endpoint | Auth hiện tại | Gap |
|---|---|---:|---|
| POST | /api/v1/auth/register | Không | Cần hạn chế |
| POST | /api/v1/auth/login | Không | Có |
| GET | /api/v1/auth/me | JWT | Có |
| GET/POST | /api/v1/cameras | GET public, POST JWT | JWT/RBAC |
| GET/PUT/DELETE | /api/v1/cameras/{id} | GET public, còn lại JWT | RBAC/hot-sync |
| GET/POST | /api/v1/zones | GET public, POST JWT | JWT/RBAC |
| GET/PUT/DELETE | /api/v1/zones/{id} | GET public, còn lại JWT | Delete hard |
| GET | /api/v1/violations | Không | JWT/pagination/filter |
| GET | /api/v1/violations/{id} | Không | JWT |
| PUT | /api/v1/violations/{id}/status | JWT | Workflow/audit |
| GET | /api/v1/violations/{id}/presigned-url | Không | Bắt buộc JWT |
| GET | /api/v1/reports/summary | Không | JWT/time filter |
| WS | /ws/alerts | Không | JWT/envelope/reconnect |

### 7.2 Internal AI API

Đã có, dùng AI_SERVICE_TOKEN:

- Upsert runtime camera.
- Nhận typed safety event.
- Nhận camera status.
- Presign upload evidence.
- Complete/fail evidence.

### 7.3 API MVP cần bổ sung

| Nhóm | Nhu cầu |
|---|---|
| User admin | List/create/update/disable user |
| Auth | Logout/refresh hoặc chốt access-only |
| Dashboard | from/to/timezone/online/offline |
| Camera | Telemetry, last_seen, test connection, desired/applied |
| Runtime config | Get config, ACK revision, apply error |
| Zone | Soft delete, revision, runtime sync |
| Violation | Time/status filter, total, dismissal reason |
| Audit | Lịch sử thao tác |
| Stream | Endpoint/token sau khi chốt transport |

## 8. Chuẩn API chung đề xuất

- Backend/database dùng UTC.
- JSON dùng ISO 8601 có timezone.
- UI đổi sang timezone người dùng.
- Phân trang trả items, page, page_size, total.
- Error thống nhất: code, message, details, request_id.
- Event retry không tạo bản ghi trùng.
- Config dùng revision/optimistic concurrency để tránh ghi đè.

Ví dụ lỗi:

~~~json
{
  "code": "CAMERA_NOT_FOUND",
  "message": "Camera not found",
  "details": null,
  "request_id": "uuid"
}
~~~

## 9. Mười hai quyết định bắt buộc trước khi code

### 1. Màn hình MVP

Khuyến nghị: Login, Dashboard, Cameras, Camera detail/live view, Zone editor, Violations, Violation detail, Reports cơ bản. Hoãn AI Models riêng, Re-ID, SMS/email và Settings nâng cao.

**Cần chốt:** màn hình và chức năng bắt buộc từng màn.

### 2. Role và quyền

Khuyến nghị admin/operator/viewer theo Mục 4; backend enforce RBAC.

**Cần chốt:** operator có sửa zone, toggle model hoặc dismiss không?

### 3. Ai tạo tài khoản

Khuyến nghị không public register production; admin tạo user, admin đầu tiên bootstrap một lần.

**Cần chốt:** admin-only, invite hay tự đăng ký?

### 4. API cần đăng nhập

Khuyến nghị mọi client API chứa camera/violation/report/evidence và WS cần JWT; chỉ login và health public. Internal API dùng AI credential.

**Cần chốt:** có monitor public read-only riêng không?

### 5. Violation workflow

Khuyến nghị NEW → REVIEWED → RESOLVED hoặc NEW/REVIEWED → DISMISSED; dismiss có reason, mọi đổi trạng thái có audit.

**Cần chốt:** transition, role và reopen.

### 6. Evidence access và retention

Khuyến nghị JWT + SAS GET 5–15 phút; PPE/zone JPEG, fall JPEG+MP4; Azure lifecycle theo retention.

**Cần chốt:** giữ bao nhiêu ngày, ai xem/download, có audit không?

### 7. Model toggle

Khuyến nghị desired/applied + revision + ACK; camera offline hiển thị pending/offline.

**Cần chốt:** toggle chỉ camera hay theo zone/lịch; ai được toggle?

### 8. Runtime config transport

Khuyến nghị MVP camera poll 3–5 giây, nhận revision mới rồi ACK.

**Cần chốt:** poll/push, timeout, mất backend thì giữ config cuối hay default?

### 9. Zone lifecycle/history

Khuyến nghị nhiều zone/camera, normalized [0,1], soft delete, revision + ACK; evidence là snapshot.

**Cần chốt:** lưu version polygon không; sửa zone khi event dở dang thế nào?

### 10. WebSocket contract

Khuyến nghị envelope ở Mục 6.10, JWT, bốn category, REST resync; không schema_version.

**Cần chốt:** field, duplicate/order guarantee và auth socket.

### 11. Live stream MVP

Khuyến nghị MJPEG 5–10 FPS cho ít viewer; chuyển WebRTC/MediaMTX khi cần scale/latency thấp.

**Cần chốt:** số camera/viewer, latency, audio, ngoài LAN.

### 12. Definition of Done

Khuyến nghị dùng Mục 11.

**Cần chốt:** môi trường demo, số camera, test và người nghiệm thu.

## 10. Câu hỏi chi tiết sau 12 quyết định

### User/bảo mật

1. Token sống bao lâu, có refresh không?
2. Khóa user có ngắt phiên/socket cũ không?
3. Chính sách mật khẩu?
4. Một site hay nhiều site/tenant?
5. Viewer có được download evidence?

### Camera/AI

6. Camera ID do backend cấp hay cấu hình trước?
7. USB index đổi sau reboot thì nhận diện lại bằng gì?
8. Heartbeat/offline timeout? Khuyến nghị 5 giây và 15–20 giây.
9. Một model lỗi có làm toàn camera offline?
10. Có chỉnh threshold từ UI?
11. FPS/latency tức thời hay trung bình?
12. RTSP credential lưu và che thế nào?

### Violation

13. Nhiều PPE code là một record hay nhiều? Hiện là một record + list.
14. PPE giảm từ bốn lỗi còn một thì khi nào hết đỏ?
15. FALL_SUSPECTED được lưu/hiện như WARNING và có JPEG evidence.
16. Cooldown theo track/type bao lâu?
17. Có gộp event thành incident?
18. Severity cố định hay cấu hình?

### Evidence/dữ liệu

19. Fall clip có bao nhiêu giây trước/sau?
20. Upload fail retry mấy lần, giữ spool bao lâu?
21. Xóa camera/user/zone có giữ violation?
22. Hết retention giữ metadata hay xóa record?
23. Có watermark camera/time?

### UI/UX

24. Grid tối đa bao nhiêu camera?
25. Nhiều alert cùng lúc ưu tiên gì?
26. Có âm thanh cảnh báo, ai được tắt?
27. Yêu cầu accessibility/color-blind?
28. Desktop hay responsive?
29. Tiếng Việt hay song ngữ?

### Vận hành

30. Ai nhận lỗi camera/model/backend/storage?
31. Dung lượng Azure/PostgreSQL dự kiến?
32. Có dev/staging/production?
33. Backup và RPO/RTO?
34. Giữ log/metrics bao lâu?

## 11. Definition of Done đề xuất cho MVP

1. Khởi động PostgreSQL, Backend, Triton và pipeline bằng tài liệu chuẩn.
2. Ít nhất hai camera/video chạy đồng thời bằng process riêng.
3. Admin login và thấy online/offline đúng.
4. Zone sửa trên UI được camera nhận revision và ACK, không restart.
5. Toggle PPE/Fall/Zone từng camera; UI phân biệt pending/applied.
6. PPE/fall/zone event đúng schema; retry không ghi trùng.
7. Alert lên UI realtime; reconnect REST resync không mất lịch sử.
8. Violation lưu DB, lọc/phân trang/mở chi tiết được.
9. PPE/zone có JPEG; fall có JPEG+MP4; evidence READY xem bằng JWT + SAS.
10. Operator xử lý đúng workflow; có reviewer/time/audit.
11. Live view có bbox/ID/zone rõ, đỏ ổn định khi vi phạm, không skeleton.
12. Viewer không sửa config; người chưa login không đọc dữ liệu/evidence/WS.
13. Mất camera/backend/Azure có retry/offline/error rõ; RAM/disk không tăng vô hạn.
14. Migration, backend test, event ingest và E2E smoke pass.
15. Secret không vào Git, log hay response.

## 12. Thứ tự triển khai

### A — Security và API contract

- Chốt 12 quyết định.
- RBAC, password hashing, account policy.
- Bảo vệ API đọc/evidence/WS.
- Chuẩn error, pagination, time filter, OpenAPI.

### B — UI dùng dữ liệu thật

- API client, types, auth store, route guard.
- Dashboard/camera/violation/report dùng API.
- WS reconnect + REST resync.

### C — Runtime control

- Desired/applied, revision, polling, ACK.
- Hot toggle model, hot sync zone, telemetry.

### D — Live view

- Chốt MJPEG/WebRTC/topology.
- Auth stream, viewer limit, reconnect.
- Overlay theo quy tắc đã thống nhất.

### E — Vận hành

- Retention/Azure lifecycle.
- Audit, backup/restore, logging, metrics.
- E2E/acceptance theo DoD.

## 13. Source of truth

| Dữ liệu | Source of truth |
|---|---|
| User, role, camera metadata | PostgreSQL |
| Violation/workflow | PostgreSQL |
| Evidence metadata/object key | PostgreSQL |
| JPEG/MP4 | Azure Blob |
| Desired config | PostgreSQL/backend |
| Applied model state | ACK gần nhất từ camera |
| Realtime notification | WebSocket, không phải lịch sử |
| Lịch sử alert | PostgreSQL/REST |
| Frame/live stream | Camera/streaming service |
| Inference | Triton + AI pipeline |

## 14. Nguyên tắc thay đổi

- Đổi request/response/event phải cập nhật schema, OpenAPI, test và docs.
- Đổi database phải có migration.
- Đổi evidence phải test cả PostgreSQL và Azure.
- Đổi quyền phải test từng role; ẩn nút UI không thay authorization backend.
- Không tự thêm lại schema_version, sequence_id, Re-ID hoặc R2 nếu chưa có quyết định mới.
- Nếu docs mâu thuẫn code, ghi rõ gap; không gọi phần chưa chạy là **ĐÃ CÓ**.

## 15. Bảng chốt quyết định

| # | Quyết định | Trạng thái | Kết luận cuối | Người chốt/ngày |
|---:|---|---|---|---|
| 1 | Màn hình MVP | Chưa chốt |  |  |
| 2 | Role và quyền | Chưa chốt |  |  |
| 3 | Tạo tài khoản | Chưa chốt |  |  |
| 4 | API cần auth | Chưa chốt |  |  |
| 5 | Violation workflow | Chưa chốt |  |  |
| 6 | Evidence access/retention | Chưa chốt |  |  |
| 7 | Model desired/applied | Chưa chốt |  |  |
| 8 | Runtime config transport | Chưa chốt |  |  |
| 9 | Zone lifecycle/history | Chưa chốt |  |  |
| 10 | WebSocket contract | Chưa chốt |  |  |
| 11 | Live stream MVP | Chưa chốt |  |  |
| 12 | End-to-end Definition of Done | Chưa chốt |  |  |

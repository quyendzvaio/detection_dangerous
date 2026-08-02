# Đặc tả MVP: Industrial Safety Product API

**Feature**: 001-industrial-safety-api  
**Ngày cập nhật**: 2026-08-01  
**Trạng thái**: Đã chốt MVP; database/ORM đã căn chỉnh bước đầu, các API sản phẩm còn đang triển khai  
**Phạm vi**: API nối AI pipeline hiện tại với Web UI; không phân quyền

## 1. Đọc nhanh: MVP đã đủ chức năng chưa?

Có. Với phạm vi nhóm vừa thống nhất, MVP gồm đủ các khối cần thiết để chạy một sản phẩm demo hoàn chỉnh:

| Khối chức năng | MVP cung cấp |
|---|---|
| Tài khoản | Đăng ký và đăng nhập đơn giản bằng Gmail + password |
| Nguồn video | CRUD camera USB/RTSP và video file |
| Live Monitoring | Xem một camera, grid nhiều camera và phóng to |
| Overlay | Bật tất cả hoặc tắt tất cả; không bật/tắt từng lớp |
| Người được theo dõi | Bbox, track ID và trạng thái an toàn |
| PPE | Thiếu mũ, kính, găng, áo; giữ trạng thái ổn định; tạo alert |
| Fall | Phân tích chuỗi pose; khi xác nhận ngã thì cảnh báo và lưu DB |
| Zone | Vẽ/sửa zone; phát cảnh báo khi track vào vùng cấm |
| Alert Center | Danh sách, filter, ưu tiên và chi tiết alert |
| Evidence | PPE/Zone có ảnh; Fall có ảnh + video; lưu Azure |
| Model Control | Bật/tắt PPE, Fall và Zone riêng từng camera/video |
| Realtime | WebSocket báo alert/status; REST dùng để tải lại dữ liệu |
| Metrics | FPS, latency và thời điểm frame cuối hiển thị ở góc live view |

MVP **không cần** báo cáo nâng cao, Re-ID, workflow review/resolve, nhiều role hoặc các state sau khi người đã ngã.

## 2. Các quyết định đã chốt

### 2.1 Tài khoản

- Chỉ có **một loại người dùng**.
- Có thể giữ một role cố định là USER trong database, nhưng UI và API không có logic phân quyền.
- Đăng ký bằng Gmail và password.
- Đăng nhập bằng Gmail và password.
- Không Google OAuth.
- Không xác minh email.
- Không refresh token, quên mật khẩu hoặc quản trị tài khoản trong MVP.
- Password không được lưu plaintext.

### 2.2 Overlay

Overlay chỉ có một công tắc:

~~~text
overlay_enabled = true  → hiện toàn bộ bbox, ID, trạng thái, zone, metrics
overlay_enabled = false → chỉ hiện hình camera/video
~~~

Tắt overlay chỉ tắt phần vẽ. PPE, Fall, Zone, lưu DB và evidence vẫn chạy.

### 2.3 Track Safety State

Mỗi track có một trạng thái tổng hợp:

| State | Ý nghĩa | Hiển thị |
|---|---|---|
| NORMAL | Không có vi phạm | Bbox xanh |
| WARNING | Đang phân tích hoặc cần chú ý | Bbox vàng |
| DANGER | PPE hoặc Zone | Bbox cam/đỏ |
| CRITICAL | Fall detected | Bbox đỏ đậm |

Ưu tiên:

~~~text
FALL > ZONE > PPE > WARNING > NORMAL
~~~

Nếu một track có nhiều lỗi, live view chỉ hiện lý do quan trọng nhất; Alert Detail vẫn giữ đầy đủ dữ liệu.

## 3. Kiến trúc API

~~~text
Web UI
  ├─ REST: account, camera/video, zone, alert, evidence, model toggle
  ├─ WebSocket: alert và camera/evidence status
  └─ Live stream: hình có hoặc không có toàn bộ overlay
                 │
                 ▼
              FastAPI
             ┌───┴──────────┐
             ▼              ▼
         PostgreSQL      Azure Blob
         metadata        JPEG / MP4
             ▲
             │ AI service token
Camera/Video pipeline → EventBus → Internal API
~~~

Quy tắc:

- PostgreSQL/REST là nguồn lịch sử.
- WebSocket chỉ thông báo, không bảo đảm replay.
- Azure chỉ lưu file evidence.
- AI service token tách user token.
- Event phải commit DB trước khi gửi WebSocket.
- Không dùng schema_version, sequence_id hoặc ai_metadata_json.
- Track ID không phải danh tính người.

## 4. User Stories

### US-01 — Đăng ký và đăng nhập (P1)

Người dùng đăng ký bằng Gmail/password, sau đó đăng nhập để dùng sản phẩm.

**Acceptance**:

1. Gmail chưa tồn tại và password hợp lệ thì đăng ký thành công.
2. Gmail trùng thì trả lỗi rõ ràng.
3. Gmail/password đúng thì login trả access token.
4. Password sai hoặc token sai thì API trả 401.
5. API không bao giờ trả password hoặc password hash.

### US-02 — Quản lý camera và video (P1)

Người dùng thêm, xem, sửa và xóa nguồn giám sát.

Nguồn hỗ trợ:

- Camera USB.
- Camera RTSP/HTTP.
- Video file dùng để test/demo.

**Acceptance**:

1. Danh sách hiển thị tên, vị trí, loại nguồn và online/offline.
2. Thêm/sửa/xóa một nguồn không ảnh hưởng nguồn khác.
3. Xóa nguồn không xóa violation/evidence lịch sử.
4. Credential nằm trong RTSP URL không được trả nguyên văn cho UI.

### US-03 — Xem live monitoring (P1)

Người dùng xem một nguồn, xem grid nhiều nguồn và phóng to một nguồn.

**Acceptance**:

1. Live view hiện tên, vị trí và trạng thái nguồn.
2. Bbox và ID được vẽ cho từng track.
3. Nhãn hiện Safety State quan trọng nhất.
4. FPS, latency và last-frame time nằm ở góc màn hình.
5. Overlay ON hiện toàn bộ thông tin.
6. Overlay OFF tắt toàn bộ phần vẽ nhưng AI vẫn chạy.
7. Không vẽ skeleton.
8. Không cần đếm người, thời gian track hoặc track-detail card.

### US-04 — Phát hiện PPE (P1)

Hệ thống kiểm tra bốn lỗi:

- NO_HELMET
- NO_GLASSES
- NO_GLOVES
- NO_VEST

**Acceptance**:

1. Có ít nhất một lỗi PPE ổn định thì track chuyển DANGER.
2. Nhiều lỗi được gom trên một nhãn ngắn.
3. Kết quả dao động một frame không làm bbox nhấp nháy.
4. Khi PPE hợp lệ ổn định, track trở lại NORMAL.
5. Khi bắt đầu vi phạm hoặc bộ PPE code thay đổi, hệ thống tạo alert phù hợp.
6. Khi hết lỗi, realtime state được xóa nhưng violation lịch sử không bị xóa.
7. PPE alert lưu một ảnh evidence.

### US-05 — Phát hiện ngã (P1)

Hệ thống thu chuỗi keypoint của từng track và phân tích Fall.

**Acceptance**:

1. Khi chưa đủ chuỗi, state có thể là ANALYZING/WARNING nhưng không tạo Fall alert.
2. Khi logic Fall xác nhận ngã, track chuyển CRITICAL.
3. Hệ thống tạo đúng một FALL_DETECTED event theo debounce/cooldown hiện tại.
4. Event được lưu PostgreSQL kèm confidence.
5. Hệ thống lưu ảnh và video evidence.
6. Không cần STILL_DOWN, RECOVERED hoặc Fall report trong MVP.

### US-06 — Quản lý và phát hiện Zone (P1)

Người dùng vẽ polygon cho từng camera/video và nhận alert khi một track vào vùng cấm.

**Acceptance**:

1. Zone có tên và ít nhất ba điểm normalized trong khoảng 0–1.
2. Có thể tạo, xem, sửa, bật/tắt và xóa Zone.
3. Zone active được vẽ khi overlay ON.
4. Track phải nằm trong polygon đủ debounce trước khi phát alert.
5. Khi xác nhận, track chuyển DANGER và tạo RESTRICTED_ZONE event.
6. Alert lưu zone_id và ảnh evidence có polygon.
7. Không cần Zone EXITED, dwell time hoặc occupancy trong MVP.

### US-07 — Trung tâm cảnh báo và bằng chứng (P1)

Người dùng xem danh sách alert, lọc, mở chi tiết và xem evidence.

**Acceptance**:

1. Alert list lọc được theo camera, type, severity và time range.
2. Alert CRITICAL được ưu tiên trước DANGER/WARNING.
3. Alert detail có camera, track ID, thời gian, type, severity và evidence status.
4. PPE detail có violation_codes.
5. Fall detail có confidence.
6. Zone detail có zone_id.
7. Evidence PROCESSING hiển thị đang xử lý.
8. Evidence READY cho xem ảnh/video bằng URL ngắn hạn.
9. Evidence FAILED hiển thị lỗi.
10. Không có workflow REVIEWED, DISMISSED hoặc RESOLVED trong MVP.

### US-08 — Bật/tắt model (P1)

Người dùng bật/tắt PPE, Fall và Zone riêng cho từng nguồn.

**Acceptance**:

1. Tắt PPE chỉ dừng nhánh PPE của nguồn đó.
2. Tắt Fall chỉ dừng nhánh Fall.
3. Tắt Zone chỉ dừng nhánh Zone.
4. Nguồn khác không bị ảnh hưởng.
5. UI phân biệt trạng thái mong muốn và trạng thái runtime đã áp dụng.
6. Re-ID không xuất hiện trong model toggle.

## 5. API mục tiêu

Mọi API dưới /api/v1 yêu cầu access token, trừ register/login. Internal API dùng AI service token.

### 5.1 Authentication

| Method | Path | Mục đích |
|---|---|---|
| POST | /api/v1/auth/register | Đăng ký Gmail/password |
| POST | /api/v1/auth/login | Login và lấy token |
| GET | /api/v1/auth/me | Lấy tài khoản hiện tại |

Register request:

~~~json
{
  "gmail": "user@gmail.com",
  "password": "secret"
}
~~~

Không có field role trong request. Role nếu còn trong database luôn là USER.

### 5.2 Camera và video source

Camera resource đại diện chung cho camera thật hoặc video test.

| Method | Path | Mục đích |
|---|---|---|
| GET | /api/v1/cameras | Danh sách nguồn |
| POST | /api/v1/cameras | Tạo nguồn |
| GET | /api/v1/cameras/{camera_id} | Chi tiết nguồn |
| PATCH | /api/v1/cameras/{camera_id} | Sửa nguồn |
| DELETE | /api/v1/cameras/{camera_id} | Soft delete nguồn |
| GET | /api/v1/cameras/{camera_id}/stream | Live stream |
| GET | /api/v1/cameras/{camera_id}/telemetry | FPS/latency/last frame |
| PATCH | /api/v1/cameras/{camera_id}/models | Toggle model |

Camera fields mục tiêu:

~~~json
{
  "id": 1,
  "camera_key": "gate-a",
  "name": "Cổng A",
  "source_type": "USB",
  "source": "0",
  "location_desc": "Cổng chính",
  "status": "ONLINE",
  "ppe_enabled": true,
  "fall_enabled": true,
  "zone_enabled": true
}
~~~

source_type hỗ trợ USB, RTSP, HTTP và VIDEO_FILE.

Model request:

~~~json
{
  "ppe_enabled": true,
  "fall_enabled": true,
  "zone_enabled": false
}
~~~

### 5.3 Zone

| Method | Path | Mục đích |
|---|---|---|
| GET | /api/v1/zones?camera_id=1 | Danh sách Zone |
| POST | /api/v1/zones | Tạo Zone |
| GET | /api/v1/zones/{zone_id} | Chi tiết |
| PATCH | /api/v1/zones/{zone_id} | Sửa polygon/active |
| DELETE | /api/v1/zones/{zone_id} | Xóa nhưng giữ lịch sử |

~~~json
{
  "camera_id": 1,
  "name": "Khu vực cấm",
  "polygon_json": [[0.1, 0.2], [0.8, 0.2], [0.8, 0.9]],
  "is_active": true
}
~~~

### 5.4 Alerts/Violations

UI gọi là Alert Center; backend tiếp tục dùng resource /violations.

| Method | Path | Mục đích |
|---|---|---|
| GET | /api/v1/violations | List/filter/pagination |
| GET | /api/v1/violations/{violation_id} | Alert detail |
| GET | /api/v1/violations/{violation_id}/presigned-url | URL evidence ngắn hạn |

Không có API update workflow status trong MVP.

List filter:

- camera_id
- violation_type
- severity_level
- evidence_status
- from
- to
- page
- page_size

Pagination:

~~~json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0
}
~~~

### 5.5 Realtime

| Transport | Path | Dữ liệu |
|---|---|---|
| WebSocket | /ws/alerts | SAFETY_EVENT, CAMERA_STATUS, EVIDENCE_STATUS, CONFIG_STATUS |

~~~json
{
  "message_id": "uuid",
  "event_category": "SAFETY_EVENT",
  "occurred_at": "2026-08-01T08:00:00Z",
  "data": {
    "event_id": "uuid",
    "record_id": 123
  }
}
~~~

WebSocket không replay. UI reconnect xong phải gọi REST để lấy lại alert bị bỏ lỡ.

### 5.6 Internal AI API

| Method | Path | Mục đích |
|---|---|---|
| PUT | /api/v1/internal/cameras/{camera_id} | Đăng ký runtime source |
| POST | /api/v1/internal/events | Ingest Safety Event |
| POST | /api/v1/internal/camera-status | ONLINE/OFFLINE |
| POST | /api/v1/internal/events/{event_id}/evidence/presign | Xin SAS upload |
| POST | /api/v1/internal/events/{event_id}/evidence/complete | Verify và READY |
| POST | /api/v1/internal/events/{event_id}/evidence/fail | FAILED |
| GET | /api/v1/internal/cameras/{camera_id}/runtime-config | Lấy model/zone config |
| POST | /api/v1/internal/cameras/{camera_id}/runtime-config/ack | Báo đã áp dụng |
| POST | /api/v1/internal/cameras/{camera_id}/telemetry | Gửi FPS/latency/last frame |

## 6. Safety Event Contract giữ nguyên

| Event | Field riêng | Severity | Evidence |
|---|---|---|---|
| PPE_VIOLATION | violation_codes[] | DANGER | JPEG |
| FALL_DETECTED | confidence | CRITICAL | JPEG + MP4 |
| FALL_SUSPECTED | confidence | WARNING | Phase 2, chưa có producer |
| RESTRICTED_ZONE | zone_id | DANGER | JPEG |

Field chung:

- event_id
- camera_id
- track_id
- detected_time
- violation_type
- severity_level
- evidence_status
- image_storage_key
- video_storage_key

event_id dùng chống duplicate khi EventBus retry.

## 7. Evidence Lifecycle

~~~text
PROCESSING → READY
      └────→ FAILED
~~~

- PPE/Zone: JPEG.
- Fall: JPEG + MP4.
- AI upload trực tiếp lên Azure bằng SAS PUT.
- Backend verify blob trước READY.
- PostgreSQL chỉ lưu object key/metadata, không lưu SAS URL.
- UI chỉ xin view URL khi READY.

## 8. Functional Requirements

- **FR-001**: Hệ thống MUST có public register/login bằng Gmail/password.
- **FR-002**: Register request MUST không cho chọn role.
- **FR-003**: Hệ thống MUST chỉ có một role cố định và MUST không có RBAC trong MVP.
- **FR-004**: Password MUST không lưu plaintext và không được trả qua API.
- **FR-005**: Camera resource MUST hỗ trợ camera thật và video file.
- **FR-006**: Camera CRUD MUST giữ violation/evidence lịch sử khi xóa.
- **FR-007**: Live Monitoring MUST hỗ trợ single view, grid và fullscreen.
- **FR-008**: Overlay MUST chỉ có chế độ all-on/all-off.
- **FR-009**: Overlay OFF MUST không dừng inference hoặc event.
- **FR-010**: Live view MUST có bbox, ID, Safety State và metrics; MUST không vẽ skeleton.
- **FR-011**: PPE MUST hỗ trợ đúng bốn violation code hiện tại.
- **FR-012**: PPE state MUST chống nhấp nháy và trở lại NORMAL sau chuỗi kết quả sạch ổn định.
- **FR-013**: FALL_DETECTED MUST tạo alert, DB record và JPEG+MP4.
- **FR-014**: MVP MUST không yêu cầu STILL_DOWN hoặc RECOVERED.
- **FR-015**: Zone MUST lưu normalized polygon và debounce trước alert.
- **FR-016**: MVP MUST không yêu cầu Zone exit, dwell time hoặc occupancy.
- **FR-017**: Alert list MUST filter và paginate.
- **FR-018**: Alert detail MUST trả field typed và evidence status.
- **FR-019**: MVP MUST không có review/dismiss/resolve workflow.
- **FR-020**: Alert priority MUST là Fall trước Zone/PPE.
- **FR-021**: Evidence MUST chỉ cho xem khi READY.
- **FR-022**: Model toggle MUST độc lập theo source và theo PPE/Fall/Zone.
- **FR-023**: UI MUST phân biệt desired/applied model state.
- **FR-024**: Internal event ingest MUST idempotent bằng event_id.
- **FR-025**: Database commit MUST xảy ra trước WebSocket notification.
- **FR-026**: WebSocket reconnect MUST resync bằng REST.
- **FR-027**: Timestamp MUST là UTC ISO-8601.
- **FR-028**: API MUST dùng một error shape ổn định.
- **FR-029**: API MUST không thêm schema_version, sequence_id hoặc ai_metadata_json.
- **FR-030**: Re-ID MUST không xuất hiện trong MVP.

Error mục tiêu:

~~~json
{
  "code": "CAMERA_NOT_FOUND",
  "message": "Camera not found",
  "details": null,
  "request_id": "uuid"
}
~~~

## 9. Phase 2

- Đếm số người.
- Thời gian tồn tại của track.
- Track detail card.
- Báo cáo PPE.
- FALL_SUSPECTED trên UI.
- STILL_DOWN và RECOVERED.
- Báo cáo Fall.
- Zone ENTERED/INSIDE/EXITED.
- Zone dwell time và occupancy.
- Toàn bộ Reporting/Analytics nâng cao.
- Export CSV/PDF.
- Re-ID nếu có quyết định mới.

## 10. Bỏ khỏi sản phẩm hiện tại

- Nhiều role và phân quyền.
- Google OAuth.
- Email verification.
- Alert workflow REVIEWED/DISMISSED/RESOLVED.
- Gán người xử lý và ghi chú workflow.
- Xác định người có quyền vào Zone.
- Danh tính công nhân.
- Phát hiện phương tiện/máy móc.
- Skeleton trên live view.

## 11. Trạng thái triển khai

| Hạng mục | Trạng thái |
|---|---|
| Gmail/password, role USER và bcrypt | Hoàn thành |
| Desired/applied model config, revision, poll và ACK | Hoàn thành |
| Zone soft delete và hot-sync polygon | Hoàn thành |
| JWT cho Product API, evidence và WebSocket | Hoàn thành |
| PPE state stabilization | Hoàn thành với hai quan sát liên tiếp |
| Live frame raw/annotated và overlay all-on/all-off | Hoàn thành |
| Alert workflow cũ | Đã bỏ khỏi API/UI MVP |
| WebSocket envelope, reconnect và REST resync | Hoàn thành |
| FPS, latency và last-frame telemetry | Hoàn thành |
| Common server-side pagination | Chưa bắt buộc cho quy mô MVP; list hiện giới hạn tối đa 200 bản ghi |

## 12. Definition of Done

MVP hoàn thành khi:

1. Người dùng đăng ký và login bằng Gmail/password.
2. Có thể CRUD cả camera và video file.
3. Hai nguồn chạy đồng thời và hiển thị dạng grid.
4. Có thể mở một nguồn và phóng to.
5. Bật/tắt toàn bộ overlay mà AI vẫn tiếp tục chạy.
6. Bbox, ID, Safety State, FPS, latency và last frame hiển thị đúng.
7. PPE, Fall, Zone đều tạo alert và lưu PostgreSQL.
8. PPE/Zone xem được JPEG; Fall xem được JPEG+MP4 từ Azure.
9. Alert Center list/filter/detail dùng dữ liệu thật.
10. Toggle model riêng từng nguồn được runtime ACK.
11. Zone tạo/sửa/bật/tắt được đồng bộ không cần restart toàn hệ thống.
12. WebSocket hiển thị alert mới và REST resync sau reconnect.
13. Không có mock data trong các màn MVP.
14. Không lộ password, RTSP secret, Azure credential hoặc SAS URL trong log.
15. Contract test, integration test và E2E cho luồng chính đều pass.

## 13. Bước tiếp theo sau khi duyệt

Sau khi nhóm xác nhận bản spec ngắn gọn này là đúng:

1. Sinh contracts/openapi.yaml.
2. Viết data-model delta.
3. Viết plan.md.
4. Sinh tasks.md.
5. Viết contract test trước khi sửa implementation.

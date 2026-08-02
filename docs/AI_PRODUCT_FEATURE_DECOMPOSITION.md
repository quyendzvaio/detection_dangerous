# Phân rã đầu ra AI thành chức năng sản phẩm

> Trạng thái: **BẢN THẢO ĐỂ TRAO ĐỔI CHỨC NĂNG**  
> Phạm vi: chức năng người dùng nhận được từ Pose, Tracking, PPE, Fall và Zone hiện tại  
> Tài liệu này chủ động không bàn về phân quyền

## 1. Mục tiêu

Một model không tự tạo thành chức năng sản phẩm. Luồng thiết kế đúng là:

~~~text
Đầu ra AI
   ↓
Trạng thái nghiệp vụ có ý nghĩa
   ↓
Chức năng người dùng nhìn thấy và thao tác
~~~

Ví dụ, NO_HELMET = 1 chỉ là tín hiệu AI. Chức năng sản phẩm phải nói được: track nào đang thiếu mũ, bắt đầu lúc nào, còn vi phạm hay đã hết, cảnh báo và bằng chứng đã sẵn sàng chưa.

## 2. Những tín hiệu nền tảng hiện có

| Nguồn | Đầu ra | Ý nghĩa |
|---|---|---|
| YOLO11n-Pose | Bbox, confidence, 17 keypoint | Phát hiện người và tư thế |
| BoT-SORT | Track ID theo camera | Nối cùng một người qua nhiều frame |
| PPE classifiers | Bốn cờ vi phạm | Thiếu mũ, kính, găng, áo phản quang |
| Fall Transformer | Fall probability | Khả năng chuỗi pose thể hiện cú ngã |
| Zone checker | Track + zone ID | Điểm chân của track vào polygon |
| Camera runtime | Frame, time, status | Live view và tình trạng nguồn |

BoT-SORT và zone checker là thuật toán hệ thống, không phải model AI. Track ID chỉ là ID tạm thời trong một camera, không phải danh tính thật và không theo người xuyên camera.

## 3. Chức năng giám sát trực tiếp

### 3.1 Live camera

Người dùng có thể hướng tới:

- Xem một camera hoặc grid nhiều camera.
- Phóng to một camera.
- Xem tên, vị trí và online/offline.
- Xem FPS, latency và thời điểm frame cuối.
- Bật/tắt overlay để giảm rối hình.

### 3.2 Hiển thị người đang được theo dõi

Từ bbox và track ID có thể tạo:

- Bbox và ID tạm thời cho từng người.
- Đếm số người trong frame.
- Trạng thái an toàn tổng hợp của từng track.
- Thời gian track đã xuất hiện.
- Bảng thông tin ngắn khi chọn một track.

Ví dụ:

~~~text
ID 07
Trạng thái: Nguy hiểm
PPE: Thiếu mũ, thiếu áo
Zone: Bình thường
Fall: Không phát hiện
Đã xuất hiện: 14 giây
~~~

### 3.3 Trạng thái an toàn tổng hợp

Thay vì vẽ mọi kết quả riêng, sản phẩm nên tổng hợp một trạng thái chính:

| Trạng thái | Ý nghĩa |
|---|---|
| NORMAL | Không có vi phạm hiện hành |
| WARNING | Có dấu hiệu cần chú ý |
| DANGER | PPE hoặc vùng cấm |
| CRITICAL | Phát hiện ngã |

Ưu tiên hiển thị:

~~~text
FALL_DETECTED
    cao hơn
PPE_VIOLATION / RESTRICTED_ZONE
    cao hơn
WARNING
    cao hơn
NORMAL
~~~

Live view chỉ cần một nhãn ngắn như ID 07 | CRITICAL | FALL.

## 4. Chức năng PPE

### 4.1 Kiểm tra PPE hiện thời

Hệ thống có thể cho biết một track đang:

- Thiếu mũ.
- Thiếu kính.
- Thiếu găng tay.
- Thiếu áo phản quang.
- Thiếu đồng thời nhiều PPE.

Nhãn nên gom gọn như ID 07 | PPE: MŨ, ÁO, không vẽ bốn dòng mã kỹ thuật.

### 4.2 State PPE ổn định

Kết quả model có thể dao động theo frame, nên cần state nghiệp vụ:

~~~text
NORMAL
   ↓ phát hiện lỗi đủ ổn định
VIOLATING
   ↓ PPE hợp lệ đủ lâu
NORMAL
~~~

Chức năng người dùng nhận được:

- Bbox chuyển đỏ khi vi phạm được xác nhận.
- Không nhấp nháy do một frame dự đoán sai.
- Chỉ trở về xanh khi hợp lệ liên tiếp đủ lâu.
- Nhãn được cập nhật khi danh sách lỗi thay đổi.

Ví dụ:

~~~text
T0: thiếu mũ + thiếu áo → đỏ
T1: mất kết quả một frame → vẫn đỏ
T2: chỉ còn thiếu mũ → vẫn đỏ, nhãn đổi thành MŨ
T3: PPE hợp lệ ổn định → trở về xanh
~~~

### 4.3 Cảnh báo PPE

Không nên tạo event ở mọi frame. Có thể tạo hoặc cập nhật khi:

- Track bắt đầu vi phạm.
- Danh sách lỗi thay đổi đáng kể.
- Vi phạm kéo dài quá một khoảng thời gian.
- Track hết vi phạm.

Thông tin có thể cung cấp:

- Camera, track và thời gian bắt đầu.
- Những PPE bị thiếu.
- Thời gian vi phạm.
- Vi phạm còn tiếp diễn hay đã hết.
- Ảnh bằng chứng.

### 4.4 Báo cáo PPE

Có thể xây:

- Số lượt vi phạm theo từng PPE.
- Camera và khung giờ có nhiều vi phạm.
- PPE bị thiếu phổ biến nhất.
- Số vi phạm mới, đã xem, bác bỏ, đã xử lý.

Tỷ lệ tuân thủ chỉ đúng khi định nghĩa mẫu số, ví dụ số lượt người được quan sát đủ lâu. Không được coi số event là tổng số người.

## 5. Chức năng phát hiện ngã

### 5.1 Trạng thái phân tích

Từ chuỗi keypoint và fall probability:

~~~text
NORMAL → ANALYZING → FALL_DETECTED
~~~

Không cần hiện xác suất liên tục trên live view. Confidence nên đặt trong chi tiết sự kiện.

### 5.2 Cảnh báo ngã khẩn cấp

Khi logic hai trong ba dự đoán vượt ngưỡng xác nhận ngã:

- Bbox chuyển đỏ ổn định.
- Hiện nhãn FALL DETECTED.
- Camera được làm nổi bật.
- Alert CRITICAL lên đầu danh sách.
- Lưu ảnh và video.
- Hiện camera, track, thời gian và confidence.

### 5.3 State sau khi phát hiện

Để hữu ích hơn một thời điểm phát hiện, cần thêm:

~~~text
NORMAL
  ↓
FALL_DETECTED
  ↓
STILL_DOWN
  ↓
RECOVERED hoặc NEEDS_REVIEW
~~~

Từ đó có thể tạo:

- Người vẫn nằm sau 5/10/30 giây.
- Người đã tự đứng dậy.
- Thời gian nằm liên tục.
- Nhắc lại nếu chưa có phản hồi.
- Phân biệt đã hồi phục và chưa xác định.

STILL_DOWN và RECOVERED chưa phải đầu ra model; cần logic pose theo thời gian.

### 5.4 Fall suspected

Có thể dùng làm cảnh báo sớm khi tư thế bất thường nhưng chưa đủ điều kiện FALL_DETECTED. Schema đã có FALL_SUSPECTED nhưng producer chưa nối runtime, nên đây là chức năng dự kiến.

### 5.5 Báo cáo ngã

Có thể cung cấp:

- Số fall detected theo thời gian/camera.
- Thời gian từ phát hiện đến xử lý.
- Số cảnh báo bị đánh dấu false positive.
- Confidence trung bình.
- Khung giờ hoặc khu vực nhiều cảnh báo.

Không nên gọi số FALL_DETECTED là số tai nạn thật khi chưa có xác nhận nghiệp vụ.

## 6. Chức năng vùng cấm

### 6.1 Vẽ và quản lý zone

Người dùng có thể:

- Chọn camera và frame nền.
- Vẽ polygon bằng chuột.
- Đặt tên, lưu, sửa, bật/tắt hoặc xóa zone.
- Hiển thị polygon trên live view.

### 6.2 Cảnh báo đi vào vùng

Khi điểm chân của track nằm trong polygon đủ số frame debounce:

- Bbox chuyển đỏ.
- Hiện zone đang bị xâm nhập.
- Tạo RESTRICTED_ZONE event.
- Lưu ảnh người cùng polygon.
- Ghi camera, track, zone ID và thời gian.

### 6.3 Vòng đời trong zone

Có thể mở rộng từ chỉ phát hiện lúc vào thành:

~~~text
OUTSIDE → ENTERED → INSIDE → EXITED
~~~

Khi có state này, người dùng có thể xem:

- Số người đang ở trong từng zone.
- Thời điểm vào và rời.
- Thời gian ở trong zone.
- Cảnh báo ở quá lâu.
- Zone đang có người hay trống.

INSIDE, EXITED, dwell time và occupancy chưa có contract đầy đủ, nhưng có thể xây từ tracking mà không cần model mới.

### 6.4 Điều zone hiện chưa biết

- Người có được phép vào zone hay không.
- Danh tính hoặc chức vụ.
- Người có giấy phép làm việc hay không.
- Phương tiện/máy móc có vào zone không.

Các chức năng này cần badge, danh tính, lịch làm việc hoặc model khác.

## 7. Trung tâm cảnh báo

### 7.1 Danh sách

- Cảnh báo mới nhất.
- Lọc camera, loại, severity, thời gian và trạng thái.
- Đưa CRITICAL lên trước.
- Tìm theo track ID.
- Badge số cảnh báo chưa xem.

### 7.2 Chi tiết

- Loại vi phạm và severity.
- Camera, vị trí, track ID và thời điểm.
- Confidence nếu có.
- PPE codes hoặc zone ID.
- Ảnh/video và trạng thái evidence.
- Trạng thái xử lý.
- Ghi chú và lịch sử.

### 7.3 Workflow

~~~text
NEW
 ├─► REVIEWED
 │      ├─► RESOLVED
 │      └─► DISMISSED
 └────────► DISMISSED
~~~

Người dùng có thể:

- Xác nhận đã xem.
- Đánh dấu false alarm và nhập lý do.
- Đánh dấu đã xử lý.
- Thêm ghi chú.
- Mở lại nếu sản phẩm cho phép.
- Xem lịch sử thao tác.

### 7.4 Ưu tiên alert đề xuất

1. Fall detected.
2. Người vẫn nằm lâu.
3. Xâm nhập vùng cấm.
4. PPE violation.
5. Camera/model/storage lỗi.

Tắt âm thanh cảnh báo không được làm mất event.

## 8. Bằng chứng

Người dùng có thể:

- Xem ảnh PPE.
- Xem ảnh zone có polygon.
- Xem ảnh và video fall.
- Phóng to ảnh, phát/tạm dừng video.
- Biết evidence đang xử lý, sẵn sàng hay thất bại.
- Yêu cầu retry nếu sản phẩm hỗ trợ.

| Status | UI |
|---|---|
| PROCESSING | Đang xử lý |
| READY | Cho xem ảnh/video |
| FAILED | Báo lỗi và hướng retry |

## 9. Báo cáo và phân tích

### 9.1 Có thể xây từ event hiện tại

- Tổng số violation.
- Theo PPE/fall/zone.
- Theo camera và thời gian.
- Theo severity và trạng thái.
- Camera nhiều alert nhất.
- PPE bị thiếu nhiều nhất.
- Số false positive.
- Thời gian xử lý trung bình khi workflow đầy đủ.

### 9.2 Cần bổ sung state hoặc dữ liệu

- Số người đi qua camera.
- Số người hiện có trong zone.
- Dwell time trung bình.
- Tỷ lệ tuân thủ PPE thực sự.
- Tỷ lệ đứng dậy sau fall.
- Tỷ lệ frame thiếu keypoint.
- Chất lượng model theo camera.

### 9.3 Không nên kết luận

- Số tai nạn lao động thật.
- Danh tính người vi phạm.
- Năng suất công nhân.
- Người cố tình vi phạm hay không.
- Mức độ chấn thương.

## 10. Vận hành camera và model

Người dùng có thể hướng tới:

- Thêm/sửa/xóa và test camera.
- Xem online/offline, last frame, FPS, latency.
- Toggle PPE/Fall/Zone từng camera.
- Phân biệt cấu hình mong muốn và đã áp dụng.
- Xem model lỗi, queue/frame drop.
- Restart riêng camera process.
- Xem Triton, Backend, PostgreSQL và Azure.

Model toggle chỉ đáng tin khi đủ luồng:

~~~text
Desired state → Camera áp dụng → ACK → Applied state
~~~

## 11. Màn hình đề xuất

### Dashboard

- Tổng quan camera và alert.
- Camera offline.
- Biểu đồ sự kiện.
- Top khu vực rủi ro.

### Live Monitoring

- Grid camera.
- Bbox, ID và safety state.
- Polygon zone.
- Alert trực tiếp.
- FPS/latency.

### Cameras

- Danh sách và nguồn.
- Toggle model.
- Telemetry.
- Zone editor.

### Violations

- Danh sách/filter.
- Chi tiết và evidence.
- Review/dismiss/resolve.
- Ghi chú/lịch sử.

### Reports

- Theo thời gian, loại và camera.
- Thời gian xử lý.
- Export ở giai đoạn sau.

### System Status

- Camera process.
- Triton/model.
- Backend/PostgreSQL.
- Azure evidence.
- Queue/drop/error.

## 12. Phân nhóm khả năng triển khai

### 12.1 Có thể cung cấp từ logic hiện tại

- Detect và track nhiều người mỗi camera.
- Bbox, ID, keypoint.
- Bốn lỗi PPE.
- Fall detected + confidence.
- Restricted-zone entry.
- Alert/severity.
- Ảnh/video evidence.
- List/detail violation.
- Báo cáo số lượng cơ bản.
- Online/offline cơ bản.

### 12.2 Cần state nghiệp vụ, không cần model mới

- Giữ bbox đỏ ổn định.
- Thời gian vi phạm PPE.
- Zone entered/inside/exited.
- Zone dwell time/occupancy.
- Fall still-down/recovered.
- Dismiss reason/audit.
- Alert priority.
- Desired/applied config.
- Report time range.
- WebSocket reconnect/resync.

### 12.3 Cần model hoặc dữ liệu mới

- Re-ID giữa camera và danh tính.
- Quyền vào zone theo từng người.
- Phân biệt hoàn hảo ngã với nằm/ngồi/cúi.
- Detect phương tiện/máy móc.
- PPE ngoài bốn loại.
- Đánh giá chấn thương.
- Compliance rate nếu chưa định nghĩa lượt quan sát.

## 13. Sáu năng lực sản phẩm chính

~~~text
1. Live safety monitoring
2. PPE compliance monitoring
3. Fall emergency monitoring
4. Restricted-zone monitoring
5. Violation and evidence management
6. Safety reporting and system operations
~~~

Lớp cần thiết kế tiếp không phải model mới mà là **state nghiệp vụ theo từng track**: bình thường, bắt đầu vi phạm, còn vi phạm, hết vi phạm, vào zone, rời zone, vừa ngã hoặc vẫn nằm.

## 14. Các câu hỏi để trao đổi

| # | Câu hỏi | Trạng thái | Kết luận |
|---:|---|---|---|
| 1 | Live view tối đa bao nhiêu camera? | Chưa chốt |  |
| 2 | Có cần click track để xem chi tiết? | Chưa chốt |  |
| 3 | PPE hợp lệ bao lâu mới từ đỏ về xanh? | Chưa chốt |  |
| 4 | PPE codes thay đổi có tạo event mới? | Chưa chốt |  |
| 5 | Có cần event PPE resolved? | Chưa chốt |  |
| 6 | Có cần still-down/recovered sau fall? | Chưa chốt |  |
| 7 | Có dùng FALL_SUSPECTED trên UI? | Chưa chốt |  |
| 8 | Fall clip lấy bao nhiêu giây trước/sau? | Chưa chốt |  |
| 9 | Có cần zone exit/dwell/occupancy? | Chưa chốt |  |
| 10 | Dùng thứ tự ưu tiên alert đề xuất? | Chưa chốt |  |
| 11 | Có âm thanh cho fall? | Chưa chốt |  |
| 12 | Có cho mở lại violation đã đóng? | Chưa chốt |  |
| 13 | Định nghĩa một lượt quan sát PPE thế nào? | Chưa chốt |  |
| 14 | MVP dùng MJPEG hay WebRTC? | Chưa chốt |  |
| 15 | System Status có thuộc MVP? | Chưa chốt |  |

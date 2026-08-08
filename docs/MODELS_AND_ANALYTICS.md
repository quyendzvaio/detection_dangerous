# Hoạt động chi tiết của các model và logic phân tích

Tài liệu này mô tả ba nhóm model an toàn đang được dùng trong runtime: `yolo_pose`, `fall_model` và nhóm PPE (`ppe_head`, `ppe_face`, `ppe_hand`, `ppe_torso`). OSNet Re-ID là model hỗ trợ tracking/identity, không phải một nhánh safety event độc lập.

## 1. Model 1 — `yolo_pose`

### Vai trò

`yolo_pose` là model đầu vào chung của pipeline. Nó phát hiện người và 17 keypoint COCO trên toàn frame. Model chạy trên Triton qua gRPC, còn tiền xử lý, decode, NMS và tracking chạy ở Python.

### Input và tiền xử lý

- Frame BGR từ Layer 0.
- Letterbox giữ tỷ lệ, padding thành `640×640`.
- Chuyển BGR sang RGB.
- Đổi HWC → CHW và gửi `UINT8` batch `(1, 3, 640, 640)`.
- ONNX graph đã có phép chia/chuẩn hóa cần thiết.

### Output và hậu xử lý

Triton trả tensor dạng `(56, 8400)`: bbox center/size, confidence và 17 bộ `(x, y, visibility/confidence)`. Client lọc confidence mặc định `0.25`, áp dụng NumPy NMS với IoU mặc định `0.45`, bỏ padding letterbox và đưa tọa độ về frame gốc.

Kết quả được BoT-SORT gán `track_id`. `TrackedFrame` là hợp đồng đầu vào cho cả ba nhánh phân tích bên dưới.

## 2. Model 2 — `fall_model`

### Vai trò

`fall_model` là Compact Temporal Transformer cho phân loại chuỗi tư thế theo thời gian. Nó không nhận ảnh thô; nó nhận chuỗi keypoint của cùng một track.

### Tạo tensor đầu vào

Với từng track, `TrackKeypointBuffer` giữ keypoint theo timestamp trong cửa sổ realtime khoảng 1 giây và retention ngắn khoảng 3 giây. Preprocessor thực hiện đúng contract notebook:

1. Chuẩn hóa 17 keypoint quanh hip (fallback shoulder), scale theo torso.
2. Keypoint không hợp lệ trở thành NaN và được nội suy theo thời gian.
3. Resample về `max_frames` của `inference_config.json` (model hiện tại dùng cửa sổ 60 frame).
4. Ghép 51 giá trị pose (`17 × x,y,confidence`) với 34 vận tốc xy.
5. Kết quả là tensor `(60, 85)`; nếu ít hơn `min_real_points` thì bỏ qua dự đoán thay vì đoán.

### Quyết định warning/critical

`TritonFallDetector` gửi tensor qua gRPC đến model `fall_model`, nhận probability và áp dụng threshold trong `weights/fall_model/inference_config.json`. `FallDecision` kết hợp threshold, M-of-N debounce, trạng thái theo track và cooldown.

- Lần đầu xác định tư thế ngã ổn định: phát `FallSuspectedEvent` (warning).
- Nếu người vẫn ở trạng thái nằm đủ `still_down_confirmation_seconds` (hiện cấu hình 5 giây): phát `FallDetectedEvent` (critical).
- Nếu phát hiện hồi phục ổn định đủ `recovery_confirmation_seconds` (hiện khoảng 2 giây), trạng thái trở về normal.
- Mỗi track có state riêng; cảnh báo không nên reset chỉ vì một frame lỗi. Tuy nhiên nếu tracker mất track và tạo ID mới, state temporal của ID cũ không thể tiếp tục.

Có thêm `HeuristicFallDetector` như safety net độc lập cho warning. Nó tồn tại vì recall của model tại threshold hiện hành chưa đủ để chỉ dựa vào một nguồn.

## 3. Model 3 — PPE models

Đây là một nhóm bốn classifier ONNX cùng phục vụ một nhánh PPE:

| Model | Crop | Quy ước output | Vi phạm |
|---|---|---|---|
| `ppe_head` | vùng đầu | class 0 helmet, class 1 no-helmet | `NO_HELMET` |
| `ppe_face` | vùng mặt | class 0 glasses, class 1 no-glasses | `NO_GLASSES` |
| `ppe_hand` | vùng tay | class 0 gloves, class 1 no-gloves | `NO_GLOVES` |
| `ppe_torso` | vùng thân | class 0 no-vest, class 1 vest | `NO_VEST` |

Mỗi crop được resize `128×128`, đổi RGB, chuẩn hóa float32 `/255`, chuyển CHW rồi gửi tới Triton qua gRPC. `PPEDetector` gọi bốn model và tổng hợp thành bốn cờ boolean.

### Tần suất và ổn định

PPE không chạy trên mọi frame. Runtime giới hạn mỗi track theo `ppe_interval_s` (mặc định 2 giây), sau đó đưa crop vào queue PPE. `PPEStateStabilizer` yêu cầu hai quan sát liên tiếp cùng state trước khi hiển thị/phát event, giảm nhấp nháy do crop hoặc che khuất.

Chỉ khi state ổn định thay đổi và có ít nhất một vi phạm, runtime phát `PPEViolationEvent`. Khi state trở về không vi phạm, state track được xóa để lần vi phạm sau có thể phát lại.

## 4. Zone analytics không phải model

Restricted Zone dùng polygon và bbox/track ID, không gọi Triton. Polygon normalized được đổi sang pixel theo kích thước frame. `ZoneChecker` phát `RestrictedZoneEvent` khi track đi vào vùng; debounce theo cấu hình giúp tránh event do một frame nhiễu.

## 5. Re-ID và tracking hỗ trợ

`osnet_reid` cùng BoT-SORT là lớp hỗ trợ identity/tracking. Nó giúp nối track trong điều kiện phù hợp, nhưng ID vẫn có phạm vi camera/runtime và có thể mất khi người bị che khuất lâu hoặc tracker reset. Không nên coi Re-ID hiện tại là định danh toàn hệ thống hoặc là model safety thứ tư.

## 6. Model toggle theo camera

`Layer2Control` chỉ cho phép `zone`, `fall`, `ppe`. Khi toggle thay đổi:

1. Runtime cập nhật cấu hình trong lock.
2. Tăng epoch của branch bị thay đổi.
3. Nếu tắt branch, queue branch được clear.
4. Consumer bỏ qua task thuộc epoch cũ.
5. PPE reset cache state khi bị tắt.

Vì control nằm trong runtime của từng camera, bật fall/PPE/zone ở một camera không bật nó ở camera khác.

## 7. Failure handling

Nếu Triton timeout hoặc crop không hợp lệ, branch không được phép biến lỗi thành một vi phạm giả. Queue bounded tiếp tục ưu tiên frame mới; metric `dropped` cho biết tải vượt khả năng consumer. Cấu hình model, threshold và cửa sổ phải được thay đổi đồng bộ với model export; preprocessing fall không được tự ý đổi nếu chưa retrain.

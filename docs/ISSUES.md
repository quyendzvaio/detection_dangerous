# Vấn Đề Tồn Đọng & Hướng Xử Lý

> Ghi nhận 25–26/07/2026 · Kiến trúc: [ARCHITECTURE.md](ARCHITECTURE.md) · Schema: [SCHEMA.md](SCHEMA.md)

Sáu vấn đề ghi lại trong quá trình rà soát kiến trúc. Mỗi mục gồm: **hiện trạng thực tế trong code → vì sao là vấn đề → cách giải quyết → cách kiểm chứng**.

| # | Vấn đề | Loại | Mức độ | Ai |
|---|---|---|---|---|
| 1 | Hai worker có thật sự chạy song song không | Cần kiểm chứng | 🟡 Theo dõi | AIE #1 |
| 2 | NMS viết bằng vòng lặp Python | Hiệu năng | 🟠 Sửa sớm | AIE #1 |
| 3 | Gom lô request vào Triton | Hiệu năng | 🔴 Sửa ngay | AIE #2 |
| 4 | Vẽ và sửa vùng cấm | Tính năng thiếu | 🔴 Xây mới | Data #2 |
| 5 | Event Bus và MQTT | Kiến trúc | 🟢 Đã chốt | AIE #1 |
| 6 | Cảnh đông người | **Xuyên suốt** | 🔴 Thiết kế | cả team |

---

## 1. Hai worker có thật sự chạy song song không?

### Hiện trạng

Thiết kế dùng `multiprocessing` — mỗi camera một tiến trình hệ điều hành riêng, nên **về nguyên tắc là song song thật** (khác thread: thread bị GIL của Python khóa, chỉ một cái chạy tính toán tại một thời điểm).

### Nhưng có ba điều kiện chưa được kiểm chứng

**① CPU của máy là loại lai (hybrid) — đây là phát hiện quan trọng**

Máy đang dùng **Intel i7-1255U**: 10 lõi vật lý gồm **2 lõi Performance + 8 lõi Efficient**, tổng 12 luồng. Hai loại lõi này **không ngang sức nhau** — lõi E chỉ đạt khoảng 40–60% hiệu năng lõi P cho tác vụ đơn luồng.

Hệ điều hành tự quyết định đặt tiến trình vào lõi nào. Nên hoàn toàn có khả năng:

```
worker cam1  →  lõi P  →  22 FPS
worker cam2  →  lõi E  →  12 FPS     ← chậm hơn mà không rõ lý do
```

Hai camera giống hệt nhau nhưng FPS lệch nhau — người ta sẽ đi tìm lỗi trong code, trong khi nguyên nhân nằm ở bộ lập lịch của hệ điều hành.

**② Song song ở tầng tiến trình, nhưng vẫn tranh nhau tài nguyên dùng chung**

| Tài nguyên | Có chia sẻ không |
|---|---|
| Lõi CPU | Riêng (nếu đủ lõi rảnh) |
| **GPU qua Triton** | **Dùng chung — tranh nhau** |
| Băng thông bộ nhớ | Dùng chung |
| Đĩa (ghi ảnh bằng chứng) | Dùng chung |

Nên **FPS không nhân đôi tuyến tính**. Thêm camera thứ hai có thể làm camera thứ nhất chậm đi.

**③ Bên trong mỗi worker vẫn là tuần tự**

Bốn nhánh phân tích chạy nối tiếp nhau trong cùng một tiến trình. Nghĩa là mỗi worker chỉ dùng hết **một lõi**, không tận dụng được 12 luồng của máy.

### Cách kiểm chứng

```bash
# Xem tải từng lõi khi chạy 2 camera
htop            # bật "Detailed CPU time", quan sát lõi nào bận

# Hoặc trong Python
python3 -c "import psutil,time; [print(psutil.cpu_percent(percpu=True)) or time.sleep(1) for _ in range(10)]"
```

**Phép đo quyết định:** chạy 1 camera đo FPS → chạy 2 camera đo FPS của từng cái.

| Kết quả | Kết luận |
|---|---|
| 2 cam ≈ FPS của 1 cam | Song song tốt, không nghẽn |
| 2 cam ≈ 60–80% | Có tranh chấp GPU — bình thường, chấp nhận được |
| Hai cam lệch nhau nhiều | **Nghi lõi P/E** — kiểm tra ngay |

### Cách giải quyết nếu lệch lõi

Ghim tiến trình vào lõi cụ thể:

```python
import psutil, os
psutil.Process(os.getpid()).cpu_affinity([0, 1])   # worker 1 → lõi P
psutil.Process(os.getpid()).cpu_affinity([2, 3])   # worker 2 → lõi P khác
```

Hoặc từ dòng lệnh: `taskset -c 0,1 python worker1.py`

> **Chưa cần làm ngay.** Chỉ ghim lõi khi đã đo và thấy lệch thật — ghim sai còn tệ hơn để hệ điều hành tự lo.

---

## 2. NMS viết bằng vòng lặp Python

### Hiện trạng

Hàm `_nms()` trong [`ai_engine/inference/pose_client.py`](../ai_engine/inference/pose_client.py) tự viết tay: mỗi vòng lặp giữ lại một box có điểm cao nhất, rồi loại bỏ những box chồng lên nó.

```python
while order.size > 0:
    i = order[0]
    keep.append(i)
    # ... tính IoU với toàn bộ box còn lại (vector hóa bằng numpy)
    order = order[1:][iou <= iou_thresh]
```

### Vì sao là vấn đề

Phần tính IoU đã được vector hóa bằng numpy (nhanh), **nhưng vòng `while` chạy trong Python**. Số vòng lặp bằng số box được giữ lại.

| Cảnh | Số ứng viên sau lọc conf | Số vòng lặp | Thời gian ước tính |
|---|---|---|---|
| 3 người | ~10–30 | ~3 | **< 1ms** — vô hại |
| 20 người (đổi ca) | ~100–300 | ~20 | ~3–8ms |
| Rất đông + nhiễu | ~500+ | ~50 | **10–20ms** |

Độ phức tạp là **O(K × N)** với K là số box giữ lại — khi cảnh đông thì cả K lẫn N cùng tăng, chi phí tăng theo kiểu bình phương.

> Đây **chưa phải nghẽn cổ chai đã được chứng minh** — chưa ai đo trên cảnh đông người. Nhưng nó nằm ngay trong vòng lặp frame nên đáng để mắt.

### Cách giải quyết — xếp theo thứ tự nên làm

**① Nhét NMS vào đồ thị ONNX (tốt nhất — giải quyết luôn hai vấn đề)**

```python
model.export(format='onnx', nms=True, imgsz=640, ...)
```

GPU tự lọc, Python không phải làm gì. Đồng thời **giảm luôn kích thước dữ liệu trả về**:

| | Hiện tại | Sau khi nhét NMS |
|---|---|---|
| Triton trả về | `(56, 8400)` = **1.88 MB** | ~`(300, 57)` = **~68 KB** |
| NMS chạy ở đâu | Vòng lặp Python | GPU |

Với 2 camera × 25fps, đây là giảm từ **~94 MB/giây xuống ~3.4 MB/giây** chảy ngược về worker.

*Cần thử nghiệm trước:* NMS-in-graph đôi khi vướng với dynamic batching — phải xác nhận Triton nạp được và batch 2 vẫn chạy.

**② Dùng NMS của OpenCV (phương án tạm, thay 3 dòng)**

```python
idx = cv2.dnn.NMSBoxes(boxes_xywh, scores, conf_thresh, iou_thresh)
```

Cài đặt bằng C++, nhanh hơn vòng lặp Python khoảng 10 lần. Dùng khi cách ① gặp trục trặc.

**③ Chặn trần số ứng viên (nên làm dù chọn cách nào)**

```python
TOP_K = 300
if len(scores) > TOP_K:
    top = np.argpartition(scores, -TOP_K)[-TOP_K:]
    boxes, scores, kpts = boxes[top], scores[top], kpts[top]
```

Giới hạn trường hợp xấu nhất. 300 người trong một khung hình là điều không bao giờ xảy ra ở nhà máy — nhưng nhiễu thì có thể tạo ra hàng trăm ứng viên giả.

### Cách kiểm chứng

Đo trực tiếp trên cảnh đông: quay một đoạn video lúc đổi ca, chạy qua pipeline, in thời gian NMS mỗi frame. Nếu vượt 5ms thì sửa ngay.

---

## 3. Gom lô request vào Triton

### Hiện trạng — đây là nghẽn rõ ràng nhất

Hàm `detect_violations()` trong [`ppe_detection.py`](../ai_engine/analytics/ppe_detection.py) gọi Triton **bốn lần liên tiếp cho mỗi người**:

```
người 1: [đầu] → chờ → [mặt] → chờ → [tay] → chờ → [thân] → chờ
người 2: (lặp lại 4 lần nữa)
```

**10 người = 40 lượt đi-về mạng**, mỗi lượt gửi đúng 1 ảnh — trong khi `config.pbtxt` đã cho phép `max_batch_size: 16`.

### Vấn đề kép: thời gian chờ gom lô phản tác dụng

Triton được cấu hình chờ tối đa 5ms để gom thêm request thành lô. Nhưng vì client gọi **tuần tự và đồng bộ** (gọi xong mới chờ, chờ xong mới gọi tiếp), **không bao giờ có request thứ hai đến trong lúc chờ**.

Kết quả: mỗi lượt gọi cõng thêm tới 5ms lãng phí. **40 lượt × 5ms = tới 200ms bốc hơi** mỗi chu kỳ PPE, thuần túy do chờ một người bạn không thể tới.

### Cách giải quyết: đổi trục gom nhóm

Thay vì "mỗi người gọi 4 model", đổi thành "**mỗi model gọi 1 lần cho tất cả mọi người**":

```
TRƯỚC — gom theo NGƯỜI (10 người = 40 lượt)
  người 1: [đầu] [mặt] [tay] [thân]
  người 2: [đầu] [mặt] [tay] [thân] ...

SAU — gom theo MODEL (10 người = 4 lượt)
  ppe_head : [đầu ×10 người]   ← 1 lượt, batch 10
  ppe_face : [mặt ×10 người]   ← 1 lượt
  ppe_hand : [tay ×10 người]   ← 1 lượt
  ppe_torso: [thân ×10 người]  ← 1 lượt
```

Bốn model là bốn model khác nhau nên không gộp chéo được — nhưng **cùng một model thì gộp được nhiều người**.

```python
def predict_batch(self, model_name, indexed_crops):
    """indexed_crops: [(chỉ_số_người, ảnh), ...] → {chỉ_số_người: class_id}"""
    valid = [(i, c) for i, c in indexed_crops if c is not None and c.size > 0]
    if not valid:
        return {}
    results = {}
    for start in range(0, len(valid), 16):            # trần max_batch_size
        chunk = valid[start:start + 16]
        batch = np.stack([self._preprocess(c) for _, c in chunk])
        inputs = [grpcclient.InferInput("images", batch.shape, "FP32")]
        inputs[0].set_data_from_numpy(batch)
        resp = self.client.infer(model_name=model_name, inputs=inputs,
                                 outputs=[grpcclient.InferRequestedOutput("output0")])
        for (person_idx, _), row in zip(chunk, resp.as_numpy("output0")):
            results[person_idx] = int(np.argmax(row))
    return results
```

### Ba chỗ phải cẩn thận

**① Tuyệt đối không để lẫn kết quả giữa người này với người kia** — rủi ro lớn nhất: báo anh A không đội mũ trong khi thực ra là anh B. Vì thế luôn mang theo **cặp `(chỉ số người, ảnh)`**, không dựa vào thứ tự mảng.

**② Người thiếu ảnh bộ phận** — có người quay lưng nên không cắt được mặt. Không nhét ảnh rỗng vào lô (model đoán bừa), cũng không bỏ qua kiểu ngây thơ (lệch chỉ số toàn bộ). Cách xử lý: lọc bỏ trước khi gom, giữ chỉ số đi kèm, cuối cùng ai không có ảnh thì mặc định không vi phạm.

**③ Giữ nguyên quy ước nhãn của `torso`** — ba model kia: class 1 = vi phạm. Riêng torso: **class 0 = không mặc áo**. Đây là bẫy dễ sai khi viết lại.

### Kết quả kỳ vọng

| | Trước | Sau |
|---|---|---|
| Số lượt gọi (10 người) | 40 | **4** |
| Phí chờ gom lô | tới 200ms | tới 20ms |
| Thời gian ước tính | ~280ms | **~30–50ms** |

Quan trọng hơn con số: khi lô có nhiều ảnh thật, **cấu hình chờ 5ms mới phát huy đúng tác dụng**.

### Việc kèm theo

Sửa `ppe_detection.py` thôi là chưa đủ — [`ppe_pipeline.py`](../ai_engine/analytics/ppe_pipeline.py) hiện lấy **từng người một** ra khỏi hàng đợi rồi xử lý ngay. Phải sửa thành: gom hết những người đến hạn kiểm tra trong chu kỳ này rồi mới gọi một lần.

**Model fall cũng vậy** — `config.pbtxt` cho `max_batch_size: 8` nhưng client gửi từng track một.

### Cách kiểm chứng

Viết test đối chiếu: chạy bản gom lô và bản tuần tự trên cùng bộ ảnh, **kết quả phải giống hệt nhau**. Sau đó đo bằng `perf_analyzer` và đọc tỷ lệ batch thực tế từ Triton metrics `:8002`.

---

## 4. Vẽ và sửa vùng cấm

### Hiện trạng

| Thành phần | Trạng thái |
|---|---|
| Logic kiểm tra điểm trong vùng | ✅ Có — [`zone.py`](../ai_engine/analytics/zone.py) |
| Bảng `zones` trong database | ❌ Chưa có (đã thiết kế trong [SCHEMA.md](SCHEMA.md)) |
| API thêm/sửa/xóa vùng | ❌ Chưa có router |
| Giao diện vẽ trên khung hình | ❌ Chưa có |
| Worker nạp vùng từ database | ❌ Chưa nối |

Tức là **đã có bộ não nhưng chưa có tay chân**.

### Bốn phần cần xây

**① Bảng `zones`** — đã thiết kế sẵn:

```
id · camera_id · name · zone_type · polygon(json) · is_active
created_by · created_at · updated_at · deleted_at
```

**② API** theo hợp đồng ③:

```
GET    /api/v1/zones?camera_id=1     → danh sách vùng của camera
POST   /api/v1/zones                 → tạo vùng mới
PUT    /api/v1/zones/{id}            → sửa polygon hoặc tên
DELETE /api/v1/zones/{id}            → xóa mềm
```

**③ Trình vẽ trên giao diện** — canvas phủ lên khung hình camera:

| Thao tác | Hành vi |
|---|---|
| Bấm chuột | Thêm một đỉnh |
| Kéo đỉnh | Di chuyển đỉnh |
| Bấm vào đỉnh đầu tiên | Đóng đa giác |
| Chuột phải lên đỉnh | Xóa đỉnh |
| Phím Esc | Hủy vùng đang vẽ |

**④ Worker nạp lại khi có thay đổi** — chi tiết dễ quên nhất, xem bên dưới.

### 🔴 Hai cái bẫy kỹ thuật

**① Hệ tọa độ — bẫy nghiêm trọng nhất**

Frontend vẽ trên canvas kích thước tùy màn hình (ví dụ 800×450), còn worker xử lý frame 1280×720. Nếu lưu **tọa độ pixel** thì vùng cấm sẽ **lệch chỗ** khi:
- Người dùng mở dashboard trên màn hình khác
- Đổi độ phân giải camera
- Thu phóng cửa sổ trình duyệt

**Bắt buộc lưu tọa độ chuẩn hóa 0–1:**

```javascript
// Frontend — khi lưu
const point = [clickX / canvas.width, clickY / canvas.height];

// Worker — khi kiểm tra
px = int(norm_x * frame_width)
py = int(norm_y * frame_height)
```

Đồng thời **canvas phải giữ đúng tỉ lệ khung hình** của camera (16:9), nếu không thì dù chuẩn hóa vẫn lệch theo chiều bị bóp.

**② Worker biết vùng đã đổi bằng cách nào**

Người dùng sửa vùng cấm trên dashboard → worker đang chạy phải cập nhật. Ba cách:

| Cách | Ưu | Nhược |
|---|---|---|
| **Worker hỏi database mỗi 5 giây** | Đơn giản nhất, không cần kênh riêng | Trễ tối đa 5 giây |
| Backend đẩy tin qua WebSocket | Tức thì | Cần kênh hai chiều worker ↔ backend |
| Khởi động lại worker | Không phải code gì | Mất hình vài giây |

**Đề xuất: cách 1.** Trễ 5 giây khi sửa vùng cấm là hoàn toàn chấp nhận được, đổi lại không phải xây thêm hạ tầng.

### Các trường hợp cần xử lý

- Đa giác dưới 3 đỉnh → chặn ngay ở frontend
- Đa giác tự cắt chính nó (hình số 8) → cảnh báo, vì `pointPolygonTest` cho kết quả khó đoán
- Vùng cấm của camera đang offline → vẫn lưu bình thường, kích hoạt khi camera lên
- Xóa vùng đã có vi phạm liên quan → **xóa mềm** (`deleted_at`), giữ lịch sử

---

## 5. Event Bus và MQTT

### Hiện trạng — đã chốt

**Event Bus** không phải một công nghệ, mà là **mô hình thiết kế**: bốn nhánh phân tích chỉ gọi `publish(event)`, không cần biết tin đi đâu.

Đã xây và kiểm thử xong ([`ai_engine/events.py`](../ai_engine/events.py)):

| Thành phần | Chi tiết |
|---|---|
| Buffer | 200 chỗ trong RAM |
| Thread nền | Nhặt tin từ buffer đem gửi |
| Cách vận chuyển | **HTTP POST** — thay thế được |
| Đo được | `publish()` mất **0.05ms** — không chặn vòng lặp frame |
| Khi buffer đầy | Bỏ tin thường; tin **CRITICAL vứt tin cũ nhất để chen vào** |

### Vì sao chọn HTTP

| Phương án | Lý do loại/chọn |
|---|---|
| `multiprocessing.Queue` | ❌ Chỉ chạy được khi mọi tiến trình cùng một chương trình cha — nhưng backend khởi động bằng lệnh riêng |
| gRPC | ❌ Phải viết `.proto` + sinh stub, đổi lại nhanh hơn vài trăm micro-giây — vô nghĩa với ~1 tin/giây |
| **HTTP POST** | ✅ Backend đã là HTTP sẵn, không cần hạ tầng mới, debug được bằng `curl` |

### MQTT — chưa dùng, nhưng cửa đã mở sẵn

MQTT là **một cách vận chuyển khác**, không phải thứ thay thế Event Bus. Nếu đổi:

```python
class MqttTransport(EventTransport):
    def send(self, event):
        self.client.publish(f'nhamay/{event.type.value.lower()}',
                            json.dumps(event.to_backend_payload()), qos=1)
```

Rồi sửa **đúng một dòng** ở `main.py`. Bốn nhánh phân tích không đụng chữ nào.

**Khi nào nên đổi:**
- Gắn đèn/còi báo động vật lý, nối PLC/SCADA — MQTT là chuẩn de-facto của tự động hóa công nghiệp
- Nhiều edge box ở nhiều khu vực báo về một trung tâm
- Cần đảm bảo không mất tin (QoS 1/2 tốt hơn cơ chế thử lại tự chế)

**Tính năng đáng chú ý — "Di chúc" (Last Will):** worker dặn trước broker *"nếu tôi đột ngột mất kết nối thì phát hộ tin cam1 đã chết"*. Điều này giải đúng bài toán **ai báo camera offline khi chính worker chết** — với HTTP phải tự viết cơ chế heartbeat ở backend.

### 🔴 Việc còn thiếu để Event Bus hoạt động

| Bước | Trạng thái |
|---|---|
| Có ai gọi `publish()` chưa | ❌ **Chưa** — worker chưa cắm |
| Endpoint backend nhận tin | ❌ **Chưa có** — gửi sang sẽ nhận 404 |
| Kiểm tra `event_id` trùng | ❌ Chưa (cột chưa tồn tại) |
| Upload ảnh lên R2 | ❌ Chưa có code |

Hiện Event Bus giống **đường ống đã lắp xong nhưng chưa nối vào vòi nước, cũng chưa nối vào bể chứa**.

---

## 6. Cảnh đông người — vấn đề xuyên suốt

### Vì sao tách riêng thành một mục

Đây không phải một lỗi cụ thể mà là **điều kiện làm mọi vấn đề khác nặng lên cùng lúc**. Và nó xảy ra đúng lúc nguy hiểm nhất: **đổi ca, tụ tập, sự cố** — lúc rủi ro an toàn cao nhất.

### Cái gì tăng theo số người?

| Thành phần | Cách tăng | Ghi chú |
|---|---|---|
| Chạy model pose | **Không đổi** ✅ | Một lần mỗi frame bất kể bao nhiêu người |
| NMS | O(N²) 🔴 | Vấn đề #2 |
| Bám vết (BoT-SORT) | O(N²) | Ma trận ghép cặp |
| PPE | O(4N) lượt gọi 🔴 | Vấn đề #3 |
| Fall | O(N) | Mỗi track một cửa sổ |
| Re-ID | Bùng theo đợt | Cả nhóm cùng vào một lúc |
| Ghi ảnh bằng chứng | O(số vi phạm) | I/O đĩa chặn vòng lặp |

Chỉ có model pose là không đổi. **Mọi thứ khác đều tăng.**

### 🔴 Hệ quả dây chuyền — điểm nguy hiểm nhất của cả hệ thống

```
Đông người
   → NMS chậm + PPE gọi 40 lượt + tracking nặng
      → vòng lặp frame chậm lại
         → FPS tụt (25 → 12)
            → cửa sổ 1 giây của Fall chỉ còn ~5 điểm keypoints
               → dưới ngưỡng tối thiểu 8 điểm
                  → PHÁT HIỆN NGÃ NGỪNG HOẠT ĐỘNG
```

**Hệ thống vẫn "chạy", vẫn hiện video, vẫn báo PPE — nhưng tính năng cứu người thì âm thầm tắt.** Đây là kiểu hỏng nguy hiểm nhất vì không ai nhận ra.

### Cách giải quyết: chiến lược xuống thang có chủ đích

Thay vì để hệ tự suy sụp lộn xộn, **định trước cái gì được hy sinh**.

**Thứ tự ưu tiên theo mức độ liên quan tính mạng:**

```
Fall  >  Zone  >  PPE  >  Re-ID
 ↑cứu người      ↑tuân thủ  ↑tiện lợi
```

**Bậc thang xuống cấp khi FPS tụt dưới ngưỡng:**

| Bậc | Điều kiện | Hành động | Vẫn giữ nguyên |
|---|---|---|---|
| 1 | FPS < 18 | Chu kỳ PPE 2s → 4s | Fall, Zone |
| 2 | FPS < 15 | Hoãn Re-ID cho track mới | Fall, Zone |
| 3 | FPS < 12 | PPE chỉ kiểm N người có bbox lớn nhất (gần camera nhất) | Fall, Zone |
| — | **Không bao giờ** | Giảm nhịp pose, tắt Zone, thu hẹp cửa sổ Fall | |

Nguyên tắc: **PPE là bài toán tuân thủ — lấy mẫu thưa vẫn dùng được. Fall và Zone là bài toán tính mạng — không được bỏ.**

### Việc cần làm

1. **Đo trước đã** — quay một đoạn video cảnh đổi ca thật, chạy qua pipeline, ghi lại FPS và thời gian từng chặng theo số người trong khung
2. Cài đặt bậc thang xuống cấp trong camera worker
3. **Ghi lại mức xuống cấp vào telemetry** — dashboard phải hiện rõ "đang chạy ở chế độ giảm tải", để người vận hành biết hệ đang không kiểm tra PPE đầy đủ
4. Bắn sự kiện cảnh báo khi xuống bậc 3 — đây là dấu hiệu phần cứng không đủ sức

---

## Thứ tự ưu tiên tổng hợp

| Thứ tự | Việc | Vì sao trước | Ai |
|---|---|---|---|
| 1 | **Bật Triton, đo FPS thật với 1 và 2 camera** | Mọi phân tích trên đây đều là suy luận từ code — chưa có số đo nào | AIE #1 |
| 2 | **Gom lô PPE** (#3) | Nghẽn rõ ràng nhất, sửa vừa phải, không đụng kiến trúc | AIE #2 |
| 3 | **Endpoint nhận sự kiện + cột `event_id`** (#5) | Không có thì cả luồng dữ liệu đứt | Data #1/#2 |
| 4 | **Bảng + API + trình vẽ vùng cấm** (#4) | Tính năng đang thiếu hoàn toàn | Data #2 |
| 5 | **NMS vào đồ thị ONNX** (#2) | Giải quyết luôn chuyện dữ liệu trả về 1.88MB | AIE #1 |
| 6 | **Chiến lược xuống thang** (#6) | Cần số đo từ bước 1 mới đặt ngưỡng đúng | AIE #1 |
| 7 | Kiểm tra phân bổ lõi P/E (#1) | Chỉ làm nếu bước 1 cho thấy hai camera lệch nhau | AIE #1 |

> **Nguyên tắc xuyên suốt:** không tối ưu chay. Mọi con số trong tài liệu này là suy luận từ code, **chưa đo trên phần cứng thật**. Việc số 1 quan trọng hơn tất cả những việc còn lại cộng lại — vì nó biến phỏng đoán thành dữ liệu.

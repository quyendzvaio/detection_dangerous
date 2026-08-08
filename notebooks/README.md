# Notebooks

## `fall_detection_training.ipynb`

Notebook train model phát hiện ngã đang chạy trong hệ thống. **Đây là nguồn sự thật** cho mọi
tham số tiền xử lý — [`ai_engine/analytics/fall.py`](../ai_engine/analytics/fall.py) port lại
đúng 4 hàm từ notebook này, lệch một bước là model đoán rác mà không báo lỗi.

### Model

| | |
|---|---|
| Kiến trúc | Compact Temporal Transformer (Conv1D + 2 encoder, d_model 96) |
| Dataset | Multiple Cameras Fall Dataset — 23 chute, 551 segment |
| Input | `(60, 85)` = 51 pose (17 COCO keypoint × x,y,conf đã chuẩn hóa) + 34 velocity |
| Nguồn keypoints | **YOLO11n-pose**, `imgsz=640`, `conf=0.25` — pipeline bắt buộc dùng đúng model/tham số này |
| Training | Early stopping ở epoch 46/100, `val_pr_auc` tốt nhất 0.883 |
| Weights | [`weights/fall_model/best_fall_model.keras`](../weights/fall_model/best_fall_model.keras) |
| Deploy | Convert ONNX bằng [`export_scripts/export_fall.py`](../export_scripts/export_fall.py) (verify diff < 1e-4) |

### Kết quả test (112 mẫu, cân bằng 56/56)

ROC-AUC **0.842** · PR-AUC **0.855**

| Threshold | Fall recall | Fall precision | Accuracy |
|---|---|---|---|
| 0.525 (F1-macro, cell 19) | 0.45 | 0.93 | 0.71 |
| **0.05 (F2, cell 22 — đang dùng)** | **0.70** | 0.83 | 0.78 |

Hệ thống chọn threshold F2 vì bỏ sót một cú ngã nguy hiểm hơn nhiều so với báo nhầm.
Báo giả được kìm bằng debounce M/N trong `FallDecision`, không phải bằng cách nâng threshold.

> ⚠️ **Chưa qua kiểm định hiện trường.** Dataset là người đóng thế trong phòng lab; val recall
> 0.833 nhưng test chỉ 0.70 → có generalization gap. Tính năng fall chạy ở chế độ **beta** cho
> tới khi đạt gate: recall ≥ 0.8 trên footage quay tại hiện trường (nhiệm vụ của AIE #2, xem
> [TEAM_PLAN.md](../docs/TEAM_PLAN.md)).

### Chạy lại

Notebook thiết kế cho Kaggle (bật GPU + Internet). Chọn Add Input →
`soumicksarker/multiple-cameras-fall-dataset` rồi Run All. Lần chạy đầu tải
`yolo11n-pose.pt` và trích pose cho 48 video (mất ~15 phút, có cache trong `pose_cache/`).

Muốn đổi threshold: chạy lại **cell 22** với `beta` khác, rồi cập nhật `threshold` trong
[`weights/fall_model/inference_config.json`](../weights/fall_model/inference_config.json).
Không cần train lại, không cần export ONNX lại.

### Ghi chú

Output của cell 7 (trích pose) đã lược bỏ vài nghìn dòng cảnh báo `'half' is deprecated` lặp
lại — chỉ là rác log, file gọn từ 1.6 MB xuống 300 KB. Mọi output có ý nghĩa (metrics, training
log, biểu đồ, confusion matrix) giữ nguyên.

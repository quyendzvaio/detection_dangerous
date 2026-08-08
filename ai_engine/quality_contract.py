"""Quality-critical inference invariants.

These values are intentionally separate from tenant/camera runtime profiles.
Changing one requires a benchmark and regression report; runtime APIs must not
write them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityContract:
    yolo_image_size: int = 640
    yolo_input_dtype: str = "UINT8"
    yolo_color_order: str = "RGB"
    yolo_layout: str = "CHW"
    yolo_confidence: float = 0.25
    yolo_nms_iou: float = 0.45
    camera_width: int = 1280
    camera_height: int = 720
    camera_fps: int = 25
    latest_frame_only: bool = True
    botsort_with_reid: bool = False
    botsort_use_cmc: bool = False
    fall_max_frames: int = 60
    fall_num_features: int = 85
    fall_threshold: float = 0.05
    fall_min_keypoint_confidence: float = 0.2
    fall_warning_m: int = 2
    fall_warning_n: int = 3
    fall_critical_seconds: float = 5.0
    fall_recovery_seconds: float = 2.0
    zone_debounce_frames: int = 5
    ppe_interval_seconds: float = 2.0
    layer2_queue_size: int = 32
    evidence_sample_fps: float = 8.0
    evidence_pre_seconds: float = 5.0
    evidence_post_seconds: float = 5.0
    preview_fps: float = 10.0


QUALITY_CONTRACT = QualityContract()


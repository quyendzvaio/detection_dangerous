import json
from pathlib import Path

from ai_engine.quality_contract import QUALITY_CONTRACT


def test_quality_contract_matches_shipped_fall_config():
    payload = json.loads(Path("weights/fall_model/inference_config.json").read_text())
    assert payload["max_frames"] == QUALITY_CONTRACT.fall_max_frames
    assert payload["num_features"] == QUALITY_CONTRACT.fall_num_features
    assert payload["threshold"] == QUALITY_CONTRACT.fall_threshold
    assert payload["min_keypoint_confidence"] == QUALITY_CONTRACT.fall_min_keypoint_confidence


def test_quality_contract_is_not_a_runtime_profile():
    assert QUALITY_CONTRACT.latest_frame_only is True
    assert QUALITY_CONTRACT.yolo_image_size == 640
    assert QUALITY_CONTRACT.yolo_input_dtype == "UINT8"
    assert QUALITY_CONTRACT.yolo_color_order == "RGB"
    assert QUALITY_CONTRACT.yolo_layout == "CHW"
    assert QUALITY_CONTRACT.botsort_with_reid is False
    assert QUALITY_CONTRACT.botsort_use_cmc is False


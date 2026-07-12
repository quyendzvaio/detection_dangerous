from ultralytics import YOLO
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import POSE_WEIGHTS_PATH, PPE_WEIGHTS_DIR

yolo_models = [
    POSE_WEIGHTS_PATH,
    os.path.join(PPE_WEIGHTS_DIR, "head_best.pt"),
    os.path.join(PPE_WEIGHTS_DIR, "face_best.pt"),
    os.path.join(PPE_WEIGHTS_DIR, "hand_best.pt"),
    os.path.join(PPE_WEIGHTS_DIR, "torso_best.pt")
]

for weight_path in yolo_models: 

    model = YOLO(weight_path)

    model.export(
        format = "onnx",
        dynamic = True, # Allow for dynamic batching
        opset = 14 # OpenVINO requirement 
    )

    print(f"Exported ONNX model for {weight_path}")
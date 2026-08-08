import os
import cv2
import numpy as np
import tritonclient.grpc as grpcclient

import sys
# Add parent directory to sys.path to allow config import when running directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from config import USE_GPU

class PPEDetector:
    def __init__(self, use_gpu=USE_GPU):
        """
        Initialize the gRPC client for PPE detection.
        """
        print("Đang kết nối tới Triton PPE Models...")
        self.client = grpcclient.InferenceServerClient(url="localhost:8001")
        
        # Save model names for Triton
        self.head_model = "ppe_head"
        self.face_model = "ppe_face"
        self.hand_model = "ppe_hand"
        self.torso_model = "ppe_torso"

    def predict_crop(self, model_name, crop):
        """
        Helper function to run classification on a single crop image using Triton gRPC.
        Returns the top 1 class ID or None if crop is invalid.
        """
        if crop is None or crop.size == 0:
            return None
        
        try:
            # Resize to 128x128 as expected by the exported model
            img = cv2.resize(crop, (128, 128))
            img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            img = img.astype(np.float32) / 255.0
            img = img.transpose(2, 0, 1)
            img = np.expand_dims(img, axis=0)

            inputs = [grpcclient.InferInput("images", img.shape, "FP32")]
            inputs[0].set_data_from_numpy(img)
            outputs = [grpcclient.InferRequestedOutput("output0")]

            response = self.client.infer(model_name=model_name, inputs=inputs, outputs=outputs)
            probs = response.as_numpy("output0")[0]
            
            return int(np.argmax(probs))
        except Exception as e:
            print(f"Lỗi Triton PPE {model_name}: {e}")
            return None

    def detect_violations(self, crops):
        """
        Runs PPE models on the crops dict and returns a dict of violation flags:
        {
            'no_helmet': 0/1,
            'no_glasses': 0/1,
            'no_gloves': 0/1,
            'no_vest': 0/1
        }
        """
        violations = {
            'no_helmet': 0,
            'no_glasses': 0,
            'no_gloves': 0,
            'no_vest': 0
        }
        
        # 1. Helmet (head_best.pt)
        # Class 0: helmet, Class 1: no_helmet
        head_crop = crops.get('head')
        head_pred = self.predict_crop(self.head_model, head_crop)
        if head_pred == 1:
            violations['no_helmet'] = 1

        # 2. Glasses (face_best.pt)
        # Class 0: glasses, Class 1: no_glasses
        face_crop = crops.get('face')
        face_pred = self.predict_crop(self.face_model, face_crop)
        if face_pred == 1:
            violations['no_glasses'] = 1

        # 3. Gloves (hand_best.pt)
        # Class 0: gloves, Class 1: no_gloves
        hand_crop = crops.get('hand')
        hand_pred = self.predict_crop(self.hand_model, hand_crop)
        if hand_pred == 1:
            violations['no_gloves'] = 1

        # 4. Vest (torso_best.pt)
        # Class 0: no_vests, Class 1: vests
        torso_crop = crops.get('torso')
        torso_pred = self.predict_crop(self.torso_model, torso_crop)
        if torso_pred == 0:
            violations['no_vest'] = 1

        return violations

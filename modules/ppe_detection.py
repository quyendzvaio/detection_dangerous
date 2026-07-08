import os
import cv2
import numpy as np
from ultralytics import YOLO

import sys
# Add parent directory to sys.path to allow config import when running directly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

class PPEDetector:
    def __init__(self, weights_dir=config.PPE_WEIGHTS_DIR, use_gpu=config.USE_GPU):
        """
        Initialize the 4 YOLO classification models for PPE detection.
        """
        device = "cuda" if use_gpu else "cpu"
        self.device = device
        
        self.head_model = YOLO(os.path.join(weights_dir, "head_best.pt"))
        self.face_model = YOLO(os.path.join(weights_dir, "face_best.pt"))
        self.hand_model = YOLO(os.path.join(weights_dir, "hand_best.pt"))
        self.torso_model = YOLO(os.path.join(weights_dir, "torso_best.pt"))

    def predict_crop(self, model, crop):
        """
        Helper function to run classification on a single crop image.
        Returns the top 1 class ID or None if crop is invalid.
        """
        if crop is None or crop.size == 0:
            return None
        
        # YOLO classification expects an image
        results = model.predict(crop, verbose=False, device=self.device)
        if len(results) > 0 and results[0].probs is not None:
            return int(results[0].probs.top1)
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

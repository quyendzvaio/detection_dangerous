# pyrefly: ignore [missing-import]
import torch
import torchvision.transforms as T
# pyrefly: ignore [missing-import]
import cv2
# pyrefly: ignore [missing-import]
import numpy as np 
import tritonclient.grpc as grpcclient 


class ReIDInference:
    def __init__(self):
        """
            Initialize Re-ID moddel
        """

        self.client = grpcclient.InferenceServerClient(url = "localhost:8001")
        self.model_name = "osnet_reid"

    def extract_feature(self, crop_img):

        img = cv2.resize(crop_img, (128, 256))
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        img = img.astype(np.float32) / 255.0

        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        img = (img - mean) / std

        img = img.transpose(2, 0, 1)

        img = np.expand_dims(img, axis=0)

        inputs = [grpcclient.InferInput("input", img.shape, "FP32")]
        inputs[0].set_data_from_numpy(img)

        outputs = [grpcclient.InferRequestedOutput("output")]
        response = self.client.infer(
            model_name = self.model_name, 
            inputs=inputs, 
            outputs=outputs
        )

        feature = response.as_numpy("output")[0]
        
        # Áp dụng chuẩn hóa độ dài L2 Norm
        norm = np.linalg.norm(feature)
        if norm > 0:
            feature = feature / norm

        return feature
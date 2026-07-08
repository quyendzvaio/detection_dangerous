# pyrefly: ignore [missing-import]
import torch
import torchvision.transforms as T
# pyrefly: ignore [missing-import]
import cv2
# pyrefly: ignore [missing-import]
import numpy as np 
# pyrefly: ignore [missing-import]
import torchreid


class ReIDInference:
    def __init__(self, weight_path, use_gpu = True):
        """
            Initialize Re-ID moddel
        """

        self.device = torch.device("cuda" if torch.cuda.is_available() and use_gpu else "cpu")

        self.model = torchreid.models.build_model(
            name = 'osnet_x1_0',
            num_classes = 751, # cho dataset Market-1501
            loss = 'softmax',
            pretrained = False
        )

        checkpoint = torch.load(weight_path, map_location = self.device, weights_only=False)
        if 'state_dict' in checkpoint: # Kiểm tra xem có state dict không 
            state_dict = checkpoint['state_dict']
        else:
            state_dict = checkpoint
        
        self.model.load_state_dict(state_dict)
        self.model.to(self.device)
        self.model.eval()

        self.transform = T.Compose([
            T.ToPILImage(), # Chuyển ảnh từ OpenCV sang PIL Image
            T.Resize((256, 128)), # Resize ảnh về kích thước chuẩn 
            T.ToTensor(), # Chuyển sang tensor 
            T.Normalize(mean = [0.485, 0.456, 0.406], std = [0.229, 0.224, 0.225]) # Chuẩn hóa ảnh 
        ])

    def extract_feature(self, crop_img):

        if crop_img is None or crop_img.size == 0:
            return None 

        # BGR -> RGB
        crop_img = cv2.cvtColor(crop_img, cv2.COLOR_BGR2RGB)

        input_tensor = self.transform(crop_img)
        input_tensor = input_tensor.unsqueeze(0).to(self.device)

        with torch.no_grad():
            feature = self.model(input_tensor)

            feature = feature.cpu().numpy().flatten()

            norm = np.linalg.norm(feature)

            if norm > 0:
                feature = feature / norm

        return feature


        


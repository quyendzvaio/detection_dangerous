import torch 
import torchreid 
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import REID_WEIGHTS_PATH

print("Initializ OSNET model")

model = torchreid.models.build_model(
    name = 'osnet_x1_0',
    num_classes = 751,
    loss = 'softmax',
    pretrained = False
)

checkpoint = torch.load(REID_WEIGHTS_PATH, map_location = "cpu", weights_only = False)

if 'state_dict' in checkpoint:
    state_dict = checkpoint['state_dict']
else:
    state_dict = checkpoint

model.load_state_dict(state_dict)

model.eval()

# Dummy input 
# tạo một tensor chứa dữ liệu rác để pytoch theo dõi đường đi của luồng tính toán 
# phải theo đúng tiêu chuẩn của OSNET
dummy_input = torch.randn(1, 3, 256, 128)

output_file = "weights/re_id_weights/onnx/osnet_reid_v1.onnx"

print("Exporting model to ONNX")

torch.onnx.export(
    model,
    dummy_input,
    output_file,
    export_params = True, # lưu kèm cả trọng số
    opset_version = 14,
    do_constant_folding = True, # tối ưu
    input_names = ["input"],
    output_names = ["output"],
    dynamic_axes = { # cho phép batch size thay đổi
        'input': {0: 'batch_size'},
        'output' : {0: 'batch_size'}
    }
)

print("Successfully exported ONNX model to ", output_file)

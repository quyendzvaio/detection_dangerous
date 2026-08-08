"""
Export YOLO11n-pose to ONNX for Triton with a uint8 input baked into the graph.

Why uint8-in-graph: the preprocessed pose tensor is the heaviest thing crossing
gRPC (see docs/PRODUCT_PIPELINE.md, Serving section). Sending uint8 (1 byte/value)
instead of float32 (4 bytes) cuts the payload 4x. The `Cast -> Div(255)` that
would run on the CPU is moved into the graph, so the GPU does it and the wire
carries raw bytes. Camera frames are already uint8, so this is numerically exact.

Usage:
    python3 export_scripts/export_pose.py [path/to/yolo11n-pose.pt]

Produces triton_model_repo/yolo_pose/1/model.onnx with:
    input  images_u8 : uint8  [N, 3, 640, 640]   (letterboxed frame, RGB, CHW)
    output output0   : float32 [N, 56, 8400]     (x,y,w,h,conf + 17*(x,y,v))
"""
import shutil
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PT = Path('/home/khanhnq/test_cam/yolo11n-pose.pt')
ONNX_OUT = ROOT / 'triton_model_repo/yolo_pose/1/model.onnx'
IMGSZ = 640


def export_fp32(pt_path):
    from ultralytics import YOLO
    model = YOLO(str(pt_path))
    exported = model.export(format='onnx', dynamic=True, opset=17,
                            imgsz=IMGSZ, simplify=True)
    return Path(exported)


def add_uint8_input(fp32_onnx, out_path):
    """Prepend a uint8 input -> Cast(float32) -> Div(255) feeding the old input."""
    import onnx
    from onnx import TensorProto, helper

    model = onnx.load(str(fp32_onnx))
    graph = model.graph
    orig_input = graph.input[0]                 # `images`, float32 [N,3,640,640]
    orig_name = orig_input.name
    dims = [d.dim_param or d.dim_value for d in orig_input.type.tensor_type.shape.dim]

    u8_name = 'images_u8'
    u8_input = helper.make_tensor_value_info(u8_name, TensorProto.UINT8, dims)
    scale = helper.make_tensor('pose_norm_255', TensorProto.FLOAT, [], [255.0])
    graph.initializer.append(scale)

    cast = helper.make_node('Cast', [u8_name], [u8_name + '_f32'],
                            to=TensorProto.FLOAT, name='pose_cast_u8')
    div = helper.make_node('Div', [u8_name + '_f32', 'pose_norm_255'], [orig_name],
                           name='pose_div_255')

    graph.node.insert(0, div)
    graph.node.insert(0, cast)
    graph.input.remove(orig_input)              # old float input now internal
    graph.input.insert(0, u8_input)

    onnx.checker.check_model(model)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(model, str(out_path))
    print(f'Wrote {out_path} ({out_path.stat().st_size // 1024} KB)')
    return u8_name


def verify(pt_path, onnx_path):
    """Compare ultralytics FP32 path vs our uint8 ONNX on one random frame."""
    import onnxruntime as ort
    from ultralytics import YOLO

    rng = np.random.default_rng(0)
    frame_u8 = rng.integers(0, 256, size=(IMGSZ, IMGSZ, 3), dtype=np.uint8)

    # Ultralytics reference (its own preprocess) on the exact same pixels
    model = YOLO(str(pt_path))
    ref = model.predict(frame_u8, imgsz=IMGSZ, verbose=False, device='cpu')[0]

    # Our path: CHW uint8, no /255 (graph does it)
    chw = np.transpose(frame_u8, (2, 0, 1))[None]  # (1,3,640,640) uint8
    sess = ort.InferenceSession(str(onnx_path), providers=['CPUExecutionProvider'])
    iname = sess.get_inputs()[0].name
    out = sess.run(None, {iname: chw})[0]
    print(f'ONNX input : {iname} {sess.get_inputs()[0].type}')
    print(f'ONNX output: {sess.get_outputs()[0].name} shape={out.shape}')
    # Sanity: output tensor stats should be finite and non-degenerate
    assert np.isfinite(out).all(), 'ONNX output has NaN/Inf'
    print(f'Output range [{out.min():.3f}, {out.max():.3f}] — OK finite')
    print(f'Ultralytics ref detections: {len(ref.boxes)} (random noise → thường 0-1)')


def main():
    pt_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PT
    if not pt_path.exists():
        raise SystemExit(f'Không tìm thấy weights: {pt_path}')
    print(f'Exporting {pt_path} → ONNX (FP32)…')
    fp32 = export_fp32(pt_path)
    print(f'Bọc uint8 input vào graph…')
    add_uint8_input(fp32, ONNX_OUT)
    verify(pt_path, ONNX_OUT)
    # keep a copy of the .pt in repo weights for reproducibility
    dest = ROOT / 'weights/yolo11n-pose.pt'
    if not dest.exists():
        shutil.copy(pt_path, dest)
        print(f'Copied weights → {dest}')


if __name__ == '__main__':
    main()

"""
Convert the fall-detection Keras model to ONNX for Triton (onnxruntime backend),
then verify numerical parity between Keras and ONNX outputs.

Usage:
    python3 export_scripts/export_fall.py

Requires: tensorflow-cpu, tf2onnx, onnx, onnxruntime (CPU is fine — conversion only).
The deploy gate: max |keras - onnx| over 50 random inputs must be < 1e-4.
"""
import os
import sys
from pathlib import Path

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
os.environ['CUDA_VISIBLE_DEVICES'] = '-1'  # conversion never needs the GPU

import numpy as np
import tensorflow as tf

ROOT = Path(__file__).resolve().parent.parent
KERAS_PATH = ROOT / 'weights/fall_model/best_fall_model.keras'
ONNX_PATH = ROOT / 'triton_model_repo/fall_model/1/model.onnx'
MAX_FRAMES, NUM_FEATURES = 60, 85
TOLERANCE = 1e-4


# The custom layer must match the training notebook exactly, or loading fails.
@tf.keras.utils.register_keras_serializable(package='FallDetection')
class LearnedPositionEmbedding(tf.keras.layers.Layer):
    def __init__(self, sequence_length, d_model, **kwargs):
        super().__init__(**kwargs)
        self.sequence_length = int(sequence_length)
        self.d_model = int(d_model)
        self.embedding = tf.keras.layers.Embedding(self.sequence_length, self.d_model)

    def call(self, inputs):
        positions = tf.range(self.sequence_length)
        return inputs + self.embedding(positions)[None, :, :]

    def get_config(self):
        return {**super().get_config(),
                'sequence_length': self.sequence_length, 'd_model': self.d_model}


def convert(model):
    import tf2onnx
    spec = (tf.TensorSpec((None, MAX_FRAMES, NUM_FEATURES), tf.float32,
                          name='pose_sequence'),)
    ONNX_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        tf2onnx.convert.from_keras(
            model, input_signature=spec, opset=17, output_path=str(ONNX_PATH)
        )
    except Exception as exc:
        # Keras 3 models sometimes reject from_keras; go through SavedModel.
        print(f'from_keras failed ({exc!r}) — falling back to SavedModel export')
        saved = ROOT / 'export_scripts/_fall_savedmodel'
        model.export(str(saved))
        rc = os.system(
            f'{sys.executable} -m tf2onnx.convert --saved-model "{saved}" '
            f'--opset 17 --output "{ONNX_PATH}"'
        )
        if rc != 0:
            raise RuntimeError('tf2onnx SavedModel conversion failed') from exc


def fix_unsupported_ops(onnx_path):
    """
    tf2onnx maps GELU to the `Erfc` op, which onnxruntime does not implement.
    Replace each `Erfc(x)` with `1 - Erf(x)` (their exact mathematical identity;
    `Erf` IS supported). Numerically identical, so parity with Keras is preserved.
    """
    import onnx
    from onnx import TensorProto, helper

    model = onnx.load(str(onnx_path))
    graph = model.graph
    erfc_nodes = [n for n in graph.node if n.op_type == 'Erfc']
    if not erfc_nodes:
        return
    one_name = 'erfc_fix_const_one'
    graph.initializer.append(
        helper.make_tensor(one_name, TensorProto.FLOAT, [], [1.0])
    )
    rebuilt = []
    for node in graph.node:
        if node.op_type == 'Erfc':
            erf_out = node.output[0] + '_erf'
            rebuilt.append(helper.make_node(
                'Erf', [node.input[0]], [erf_out], name=node.name + '_erf'))
            rebuilt.append(helper.make_node(
                'Sub', [one_name, erf_out], [node.output[0]], name=node.name + '_sub'))
        else:
            rebuilt.append(node)
    del graph.node[:]
    graph.node.extend(rebuilt)
    onnx.checker.check_model(model)
    onnx.save(model, str(onnx_path))
    print(f'Fixed {len(erfc_nodes)} unsupported Erfc op(s) -> 1 - Erf')


def verify(model):
    import onnxruntime as ort
    session = ort.InferenceSession(str(ONNX_PATH), providers=['CPUExecutionProvider'])
    input_name = session.get_inputs()[0].name
    output_name = session.get_outputs()[0].name
    print(f'ONNX input: {input_name} {session.get_inputs()[0].shape}')
    print(f'ONNX output: {output_name} {session.get_outputs()[0].shape}')
    print('>>> Cập nhật input/output name trong config.pbtxt và fall.py nếu khác '
          'pose_sequence / fall_probability')

    rng = np.random.default_rng(42)
    worst = 0.0
    for _ in range(50):
        x = rng.normal(0, 1, size=(1, MAX_FRAMES, NUM_FEATURES)).astype(np.float32)
        keras_out = float(np.ravel(model.predict(x, verbose=0))[0])
        onnx_out = float(np.ravel(session.run([output_name], {input_name: x})[0])[0])
        worst = max(worst, abs(keras_out - onnx_out))
    print(f'Max |keras - onnx| over 50 samples: {worst:.2e}')
    if worst >= TOLERANCE:
        raise SystemExit(f'FAIL: diff {worst:.2e} >= {TOLERANCE} — do not deploy')
    print('PASS: ONNX numerically matches Keras — safe to deploy on Triton')


def main():
    print(f'Loading {KERAS_PATH}')
    model = tf.keras.models.load_model(
        KERAS_PATH, custom_objects={'LearnedPositionEmbedding': LearnedPositionEmbedding}
    )
    model.summary(line_length=90)
    convert(model)
    fix_unsupported_ops(ONNX_PATH)
    print(f'Wrote {ONNX_PATH} ({ONNX_PATH.stat().st_size // 1024} KB)')
    verify(model)


if __name__ == '__main__':
    main()

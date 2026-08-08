"""
YOLO11n-pose inference client for Triton (gRPC).

Splits what ultralytics' model.track() used to do into explicit steps so the
model can live on Triton and tracking can run separately (BoxMOT):

    letterbox → uint8 CHW → gRPC yolo_pose → decode [56,8400] → NMS → rescale

The uint8 input matches the exported graph (Cast + Div(255) are inside the ONNX,
see export_scripts/export_pose.py), so this client sends raw bytes — 4x lighter
on the wire than float32.
"""
import cv2
import numpy as np

IMGSZ = 640
NUM_KEYPOINTS = 17


def letterbox(frame, size=IMGSZ, color=114):
    """Resize keeping aspect ratio, pad to a square. Returns (padded, scale, pad_x, pad_y)."""
    h, w = frame.shape[:2]
    scale = min(size / h, size / w)
    nh, nw = int(round(h * scale)), int(round(w * scale))
    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
    pad_x = (size - nw) // 2
    pad_y = (size - nh) // 2
    out = np.full((size, size, 3), color, dtype=np.uint8)
    out[pad_y:pad_y + nh, pad_x:pad_x + nw] = resized
    return out, scale, pad_x, pad_y


def preprocess(frame_bgr):
    """BGR frame -> (uint8 CHW tensor (3,640,640), scale, pad_x, pad_y)."""
    padded, scale, pad_x, pad_y = letterbox(frame_bgr)
    rgb = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
    chw = np.ascontiguousarray(np.transpose(rgb, (2, 0, 1)))  # (3,640,640) uint8
    return chw, scale, pad_x, pad_y


def _nms(boxes_xyxy, scores, iou_thresh):
    """Plain NumPy NMS. boxes_xyxy: (N,4). Returns kept indices."""
    if len(boxes_xyxy) == 0:
        return []
    x1, y1, x2, y2 = boxes_xyxy.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1)
        h = np.maximum(0.0, yy2 - yy1)
        inter = w * h
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= iou_thresh]
    return keep


def decode(output0, scale, pad_x, pad_y, conf_thresh=0.25, iou_thresh=0.45):
    """
    output0: (56, 8400) for one image. Returns (boxes_xyxy (M,4), scores (M,),
    keypoints (M,17,3)) in ORIGINAL frame coordinates.
    Layout per anchor: [cx, cy, w, h, conf, (kx,ky,kv) * 17].
    """
    pred = output0.T  # (8400, 56)
    scores = pred[:, 4]
    mask = scores >= conf_thresh
    pred = pred[mask]
    scores = scores[mask]
    if len(pred) == 0:
        return np.empty((0, 4), np.float32), np.empty((0,), np.float32), \
            np.empty((0, NUM_KEYPOINTS, 3), np.float32)

    cx, cy, w, h = pred[:, 0], pred[:, 1], pred[:, 2], pred[:, 3]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    kpts = pred[:, 5:].reshape(-1, NUM_KEYPOINTS, 3).copy()

    keep = _nms(boxes, scores, iou_thresh)
    boxes, scores, kpts = boxes[keep], scores[keep], kpts[keep]

    # Undo letterbox: subtract padding, divide by scale
    boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pad_x) / scale
    boxes[:, [1, 3]] = (boxes[:, [1, 3]] - pad_y) / scale
    kpts[:, :, 0] = (kpts[:, :, 0] - pad_x) / scale
    kpts[:, :, 1] = (kpts[:, :, 1] - pad_y) / scale
    return boxes.astype(np.float32), scores.astype(np.float32), kpts.astype(np.float32)


class PoseClient:
    def __init__(self, url='localhost:8001', model_name='yolo_pose',
                 input_name='images_u8', output_name='output0',
                 conf_thresh=0.25, iou_thresh=0.45):
        import tritonclient.grpc as grpcclient
        self._grpcclient = grpcclient
        self.client = grpcclient.InferenceServerClient(url=url)
        self.model_name = model_name
        self.input_name = input_name
        self.output_name = output_name
        self.conf_thresh = conf_thresh
        self.iou_thresh = iou_thresh

    def infer(self, frame_bgr):
        """Full frame -> (boxes_xyxy, scores, keypoints) in original coords."""
        chw, scale, pad_x, pad_y = preprocess(frame_bgr)
        batch = np.expand_dims(chw, 0)  # (1,3,640,640) uint8
        inputs = [self._grpcclient.InferInput(self.input_name, batch.shape, 'UINT8')]
        inputs[0].set_data_from_numpy(batch)
        outputs = [self._grpcclient.InferRequestedOutput(self.output_name)]
        response = self.client.infer(
            model_name=self.model_name, inputs=inputs, outputs=outputs
        )
        out = response.as_numpy(self.output_name)[0]  # (56, 8400)
        return decode(out, scale, pad_x, pad_y, self.conf_thresh, self.iou_thresh)

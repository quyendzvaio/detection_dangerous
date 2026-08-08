# Model Quality Contract

This repository locks the shipped inference artifacts and quality-critical
runtime invariants. The CI quality gate hashes the Triton model repository and
fall inference configuration. A change requires a benchmark, regression report
and explicit approval.

The transport migration must preserve:

- BGR decoded frames entering the existing preprocessing path.
- YOLO letterbox size 640, RGB CHW UINT8 input, confidence 0.25 and NMS IoU 0.45.
- 1280x720 at 25 FPS defaults and latest-frame-only semantics.
- BoT-SORT without Re-ID and without camera-motion compensation.
- Fall configuration in `weights/fall_model/inference_config.json`.
- Layer 2 queue/debounce/timing and evidence/preview defaults.

The deterministic regression surface is the same decoded frame sequence. RTSP
transport latency and packet loss are operational metrics; they must not be
used to silently alter model or preprocessing parameters.


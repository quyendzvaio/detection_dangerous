#!/usr/bin/env python3
"""Fail CI if shipped inference artifacts or locked constants drift."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ai_engine.quality_contract import QUALITY_CONTRACT

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HASHES = {
    "weights/fall_model/inference_config.json": "7bb547841af64fe9592bcd172546e5d1571c49712991d2649bc6c78a90986772",
    "triton_model_repo/fall_model/config.pbtxt": "000824786ef1e4d820d414d9ae62bffe9c973d759f4ec3891a8ccac884fcc396",
    "triton_model_repo/fall_model/1/model.onnx": "def10f3e2a0563c6dcae3e5b9e27d9a31bd98186694545151553502bfeb39ebc",
    "triton_model_repo/yolo_pose/config.pbtxt": "186a8563cdf23788415ea57d81fc183f55c20e9b63e5dad13fb46e98bd32d400",
    "triton_model_repo/yolo_pose/1/model.onnx": "3a73b7ca229bead3f26ef08ac5eadf5907ab779d0901eeda97f3dcb0b3dc2a4b",
    "triton_model_repo/ppe_face/config.pbtxt": "505401d09914aee0118095d1907d87fcf4cab9ea5e3a9c08e9b6805f0b7ff6bf",
    "triton_model_repo/ppe_face/1/model.onnx": "39c9df291d2e64c0deff45044451ff94c0040c44dfcfecfe965d54d52d803a50",
    "triton_model_repo/ppe_head/config.pbtxt": "2af637d576169984ebd3f55afd865dcbf8d48e3104bdd6c29902d3c168a25429",
    "triton_model_repo/ppe_head/1/model.onnx": "8b8927ed61cc8c096777f95fa675c1adad525729531c147024252fb41f08a351",
    "triton_model_repo/ppe_hand/config.pbtxt": "c628aad2f7f4cd9c2282fcfc1f6c179d0ee438ee8a3031e6694040e1273513ba",
    "triton_model_repo/ppe_hand/1/model.onnx": "ce3c669866b649dceda1686c940b204d400f11c5dbd706d92f8033cc807b89c4",
    "triton_model_repo/ppe_torso/config.pbtxt": "6cd6b407def9d729402e4a26716dd391802bd8ca2720d5433495ff02c9950daa",
    "triton_model_repo/ppe_torso/1/model.onnx": "137b146e8af3ff58bd918274410c16ef3da3c5bd7bcd11aab9da8ef0e9f3ffac",
    "triton_model_repo/osnet_reid/config.pbtxt": "44c7cea7e38a8740f0ffc11ec3794211092828af05186470df08844086ccff01",
    "triton_model_repo/osnet_reid/1/model.onnx": "a30c662cc9606be9555c24cda935fff9c2213f6230787d9bb66d67dba9585d1b",
    "triton_model_repo/osnet_reid/1/model.onnx.data": "cc1f02bf31b211568a779d34f786421cd0abb8f8699b38b0b96bab80d8fcb418",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    failures: list[str] = []
    for relative, expected in EXPECTED_HASHES.items():
        path = ROOT / relative
        actual = sha256(path) if path.exists() else "missing"
        if actual != expected:
            failures.append(f"{relative}: expected {expected}, got {actual}")

    fall = json.loads((ROOT / "weights/fall_model/inference_config.json").read_text())
    checks = {
        "fall.max_frames": fall["max_frames"] == QUALITY_CONTRACT.fall_max_frames,
        "fall.num_features": fall["num_features"] == QUALITY_CONTRACT.fall_num_features,
        "fall.threshold": fall["threshold"] == QUALITY_CONTRACT.fall_threshold,
        "fall.min_keypoint_confidence": fall["min_keypoint_confidence"] == QUALITY_CONTRACT.fall_min_keypoint_confidence,
    }
    failures.extend(name for name, passed in checks.items() if not passed)
    if failures:
        print("QUALITY GATE FAILED")
        print("\n".join(failures))
        return 1
    print(f"QUALITY GATE PASSED ({len(EXPECTED_HASHES)} artifact hashes locked)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

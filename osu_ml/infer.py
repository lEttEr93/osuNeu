"""Run the exported ONNX model on a real .osu file.

This is the contract the C# side has to reproduce: parse -> 19 features ->
onnxruntime -> per-segment scores.
"""

from __future__ import annotations

import sys

import numpy as np
import onnxruntime as ort

from .features import N_FEATURES, build_features
from .parse import parse_file
from .synth import LABELS

SEG = 32


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-x))


def analyze(path: str, onnx_path: str = "pattern_model.onnx"):
    bm = parse_file(path)
    feats = build_features(bm)
    sess = ort.InferenceSession(onnx_path, providers=["CPUExecutionProvider"])
    x = feats[None].astype(np.float32)
    seg_logits, map_logits, weights = sess.run(None, {"tokens": x})

    seg = sigmoid(seg_logits[0])                      # (N, 6)
    print(f"{path}")
    print(f"  objects={len(feats)}  segments={len(seg)}  "
          f"bpm~{60000 / bm.beat_length_at(bm.objects[0].time):.0f}")
    top = np.argsort(-sigmoid(map_logits[0]))[:3]
    print("  map: " + "  ".join(f"{LABELS[i]}={sigmoid(map_logits[0])[i]:.2f}" for i in top))
    print("  busiest segments (attention):")
    for i in np.argsort(-weights[0])[:3]:
        sec = seg[i]
        t0 = bm.objects[i * SEG].time / 1000
        names = ", ".join(f"{LABELS[j]}={sec[j]:.2f}" for j in np.argsort(-sec)[:2])
        print(f"    seg {i:3d} @{t0:7.1f}s  w={weights[0][i]:.3f}  {names}")


if __name__ == "__main__":
    analyze(sys.argv[1] if len(sys.argv) > 1 else "")

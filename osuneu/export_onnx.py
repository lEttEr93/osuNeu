"""Export the trained model to ONNX and verify it with onnxruntime.

The C# side (osu-roam) can then run inference with Microsoft.ML.OnnxRuntime,
feeding float[batch, T, 19] and reading segment logits + map logits.
"""

from __future__ import annotations

import argparse

import numpy as np
import torch

from .model import TinyPatternNet, count_params
from .synth import N_LABELS

N_FEATURES = 19


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default="model.pt")
    ap.add_argument("--out", default="pattern_model.onnx")
    ap.add_argument("--ch", type=int, default=64)
    ap.add_argument("--blocks", type=int, default=3)
    args = ap.parse_args()

    model = TinyPatternNet(N_FEATURES, N_LABELS, ch=args.ch, n_blocks=args.blocks)
    model.load_state_dict(torch.load(args.weights, map_location="cpu"))
    model.eval()
    print(f"model: {count_params(model):,} params")

    dummy = torch.randn(1, 320, N_FEATURES)
    torch.onnx.export(
        model, dummy, args.out,
        input_names=["tokens"], output_names=["seg_logits", "map_logits", "seg_weights"],
        dynamic_axes={"tokens": {0: "batch", 1: "objects"},
                      "seg_logits": {0: "batch", 1: "segments"},
                      "map_logits": {0: "batch"},
                      "seg_weights": {0: "batch", 1: "segments"}},
        opset_version=17, dynamo=False,
    )

    import os
    print(f"exported {args.out} ({os.path.getsize(args.out) / 1024:.0f} KB)")

    # parity check
    import onnxruntime as ort
    sess = ort.InferenceSession(args.out, providers=["CPUExecutionProvider"])
    for T in (320, 97, 1024):
        x = np.random.randn(2, T, N_FEATURES).astype(np.float32)
        with torch.no_grad():
            ref = model(torch.tensor(x))
        got = sess.run(None, {"tokens": x})
        for i, name in enumerate(("seg_logits", "map_logits", "seg_weights")):
            a, b = ref[i].numpy(), got[i]
            print(f"T={T:5d} {name:12s} max|diff|={np.abs(a - b).max():.2e}")


if __name__ == "__main__":
    main()

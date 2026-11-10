"""Quick diagnostics: segment-level AUC and label balance."""

from __future__ import annotations

import numpy as np
import torch

from .model import TinyPatternNet
from .synth import LABELS, N_LABELS, SEG, make_dataset

N_FEATURES = 19


def auc(y, p):
    y = np.asarray(y)
    if y.min() == y.max():
        return float("nan")
    order = np.argsort(p)
    ys = y[order]
    ranks = np.arange(1, len(y) + 1)
    n_pos, n_neg = (ys == 1).sum(), (ys == 0).sum()
    return float((ranks[ys == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def main():
    maps = make_dataset(300, seed=1234)
    rng = np.random.RandomState(0)
    order = rng.permutation(len(maps))
    val = order[:60]

    model = TinyPatternNet(N_FEATURES, N_LABELS)
    model.load_state_dict(torch.load("model.pt", map_location="cpu"))
    model.eval()

    seg_p, seg_y, map_p, map_y = [], [], [], []
    with torch.no_grad():
        for i in val:
            m = maps[i]
            seg_logits, _, _ = model(torch.tensor(m["features"][None]))
            p = torch.sigmoid(seg_logits)[0].numpy()
            n = len(m["seg_labels"])
            p = p[:n]
            seg_p.append(p)
            seg_y.append(m["seg_labels"])
            map_p.append(p.mean(axis=0))
            map_y.append(m["map_labels"])

    seg_p = np.concatenate(seg_p)
    seg_y = np.concatenate(seg_y)
    map_p, map_y = np.stack(map_p), np.stack(map_y)

    print("map label positive rate:", {n: float(maps[i]["map_labels"][j].mean())
                                       for j, n in enumerate(LABELS)})
    for j, n in enumerate(LABELS):
        print(f"{n:10s} seg_auc={auc(seg_y[:, j], seg_p[:, j]):.3f} "
              f"map_auc={auc(map_y[:, j], map_p[:, j]):.3f} "
              f"seg_pos_rate={seg_y[:, j].mean():.2f}")


if __name__ == "__main__":
    main()

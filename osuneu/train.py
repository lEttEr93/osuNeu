"""Train the tiny pattern model on the synthetic set (CPU, <1 min)."""

from __future__ import annotations

import argparse
import time

import numpy as np
import torch
import torch.nn.functional as F

from .model import TinyPatternNet, count_params
from .synth import LABELS, N_LABELS, SEG, make_dataset

N_FEATURES = 19


def window_batch(maps, idx, win_seg=8, rng=None):
    """Take a contiguous window of `win_seg` segments from each map."""
    xs, ys, my = [], [], []
    for i in idx:
        m = maps[i]
        n = len(m["seg_labels"])
        if n <= win_seg:
            s = 0
        else:
            s = (rng or np.random).randint(0, n - win_seg)
        tok = m["features"][s * SEG:(s + win_seg) * SEG]
        xs.append(tok)
        ys.append(m["seg_labels"][s:s + win_seg])
        my.append(m["seg_labels"][s:s + win_seg].max(axis=0))
    T = min(x.shape[0] for x in xs)
    n_seg = T // SEG
    return (torch.tensor(np.stack([x[:n_seg * SEG] for x in xs])),
            torch.tensor(np.stack([y[:n_seg] for y in ys])),
            torch.tensor(np.stack([y[:n_seg].max(axis=0) for y in ys])))


def evaluate(model, maps, idx):
    model.eval()
    probs, trues = [], []
    with torch.no_grad():
        for i in idx:
            m = maps[i]
            x = torch.tensor(m["features"][None])
            seg_logits, _, _ = model(x)
            # map score = max over segments (MIL-max), not the attention head
            probs.append(torch.sigmoid(seg_logits)[0].mean(dim=0).numpy())
            trues.append(m["map_labels"])
    probs = np.stack(probs)
    trues = np.stack(trues)
    out = {}
    for j, name in enumerate(LABELS):
        y, p = trues[:, j], probs[:, j]
        if y.min() == y.max():
            out[name] = float("nan")
            continue
        order = np.argsort(p)
        y_sorted = y[order]
        # rank-based AUC (no sklearn dependency)
        ranks = np.arange(1, len(y) + 1)
        pos = ranks[y_sorted == 1].sum()
        n_pos, n_neg = (y == 1).sum(), (y == 0).sum()
        auc = (pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
        out[name] = float(auc)
    pred = (probs >= 0.5).astype(np.float32)
    out["micro_f1"] = float(
        (2 * (pred * trues).sum()) / max(1.0, (pred + trues).sum())
    )
    model.train()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--maps", type=int, default=600)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--ch", type=int, default=64)
    ap.add_argument("--blocks", type=int, default=3)
    ap.add_argument("--out", default="model.pt")
    args = ap.parse_args()

    t0 = time.time()
    print(f"building {args.maps} synthetic maps ...")
    maps = make_dataset(args.maps, seed=1234)
    rng = np.random.RandomState(0)
    order = rng.permutation(len(maps))
    n_val = max(20, len(maps) // 5)
    val_idx, train_idx = order[:n_val], order[n_val:]
    print(f"  {len(maps)} maps, {len(train_idx)} train / {len(val_idx)} val, "
          f"{time.time() - t0:.1f}s")

    model = TinyPatternNet(N_FEATURES, N_LABELS, ch=args.ch, n_blocks=args.blocks)
    print(f"model: {count_params(model):,} params")
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)

    steps_per_epoch = max(1, len(train_idx) // args.batch)
    for ep in range(args.epochs):
        ep_loss = 0.0
        perm = rng.permutation(train_idx)
        for s in range(steps_per_epoch):
            idx = perm[s * args.batch:(s + 1) * args.batch]
            x, y, ym = window_batch(maps, idx, rng=rng)
            seg_logits, map_logits, _ = model(x)
            loss = F.binary_cross_entropy_with_logits(seg_logits, y)
            loss = loss + 0.5 * F.binary_cross_entropy_with_logits(map_logits, ym)
            opt.zero_grad()
            loss.backward()
            opt.step()
            ep_loss += float(loss) / steps_per_epoch
        metrics = evaluate(model, maps, val_idx)
        aucs = " ".join(f"{k}={v:.3f}" for k, v in metrics.items()
                        if k != "micro_f1" and not np.isnan(v))
        print(f"epoch {ep + 1}: loss={ep_loss:.4f} micro_f1={metrics['micro_f1']:.3f} {aucs}")

    torch.save(model.state_dict(), args.out)
    print(f"saved {args.out}  ({time.time() - t0:.1f}s total)")


if __name__ == "__main__":
    main()

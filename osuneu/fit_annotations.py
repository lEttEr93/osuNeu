"""Fit a tiny per-object classifier on exported annotations.

Purpose: a feasibility check, not a real model. It answers one question -
can a small network separate the user's `stream` vs `jump` labels from local
geometry alone?

Usage:
    python -m osuneu.fit_annotations export1.json export2.json ...
"""

from __future__ import annotations

import argparse
import json
import os
import zipfile
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn

from .features import N_FEATURES, build_features
from .parse import Beatmap, parse_osu

LABELS = ["stream", "jump"]
WINDOW = 2  # +-2 objects of context


def cache_dir() -> Path:
    return Path(os.environ.get("AI_CACHES", "D:/AI/caches")) / "osuneu" / "beatmaps"


def locate_beatmap(filename: str) -> Beatmap | None:
    base = os.path.basename(filename).casefold()
    for osz in sorted(cache_dir().glob("*.osz")):
        try:
            with zipfile.ZipFile(osz) as z:
                for name in z.namelist():
                    if os.path.basename(name).casefold() == base:
                        return parse_osu(z.read(name).decode("utf-8-sig", errors="replace"))
        except (zipfile.BadZipFile, OSError):
            continue
    return None


def load_dataset(paths):
    charts = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        bm = locate_beatmap(data["beatmap"]["filename"])
        if bm is None:
            print(f"skip {path}: beatmap not in cache")
            continue
        feats = build_features(bm)
        y = np.zeros((len(feats), len(LABELS)), dtype=np.float32)
        mask = np.zeros(len(feats), dtype=bool)
        for a in data["annotations"]:
            labels = [l for l in a["labels"] if l in LABELS]
            if not labels:
                continue
            for idx in a.get("objectIndices", []):
                if 0 <= idx < len(feats):
                    for l in labels:
                        y[idx, LABELS.index(l)] = 1.0
                    mask[idx] = True
        charts.append(dict(name=Path(path).stem, feats=feats, y=y, mask=mask,
                           bpm=data["beatmap"].get("bpm"), ar=data["beatmap"].get("ar")))
        print(f"{Path(path).stem}: {len(feats)} objects, {mask.sum()} labeled, "
              f"stream={int(y[mask,0].sum())} jump={int(y[mask,1].sum())}")
    return charts


def windows(feats: np.ndarray) -> np.ndarray:
    """(T, F) -> (T, (2*WINDOW+1)*F) with zero padding at the edges."""
    t = len(feats)
    pad = np.zeros((WINDOW, feats.shape[1]), dtype=np.float32)
    padded = np.vstack([pad, feats, pad])
    return np.stack([padded[i:i + 2 * WINDOW + 1].ravel() for i in range(t)])


class Net(nn.Module):
    def __init__(self, n_in: int, n_out: int, hidden: int = 64):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(n_in, hidden), nn.ReLU(),
                                 nn.Dropout(0.1), nn.Linear(hidden, n_out))
        self.n_in = n_in

    def forward(self, x):
        return self.net(x)


def train_eval(train, test, epochs=400, seed=0):
    torch.manual_seed(seed)
    xs = np.concatenate([windows(c["feats"])[c["mask"]] for c in train])
    ys = np.concatenate([c["y"][c["mask"]] for c in train])
    model = Net(xs.shape[1], len(LABELS))
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-3)
    x_t, y_t = torch.tensor(xs), torch.tensor(ys)
    for _ in range(epochs):
        opt.zero_grad()
        loss = nn.functional.binary_cross_entropy_with_logits(model(x_t), y_t)
        loss.backward()
        opt.step()
    model.eval()

    rows = []
    for c in test:
        x = torch.tensor(windows(c["feats"])[c["mask"]])
        y = c["y"][c["mask"]]
        with torch.no_grad():
            p = torch.sigmoid(model(x)).numpy()
        for j, name in enumerate(LABELS):
            rows.append((c["name"], name, y[:, j], p[:, j]))
    return rows


def report(rows, title):
    print(f"\n== {title}")
    for name in LABELS:
        yy = np.concatenate([r[2] for r in rows if r[1] == name])
        pp = np.concatenate([r[3] for r in rows if r[1] == name])
        if yy.min() == yy.max():
            print(f"  {name:7s} single-class in test ({int(yy.sum())}/{len(yy)})")
            continue
        acc = ((pp >= 0.5) == (yy >= 0.5)).mean()
        auc = roc_auc(yy, pp)
        print(f"  {name:7s} AUC={auc:.3f} acc={acc:.3f} (pos={int(yy.sum())}/{len(yy)})")


def roc_auc(y, p):
    order = np.argsort(p)
    y = y[order]
    ranks = np.arange(1, len(y) + 1)
    n_pos, n_neg = y.sum(), (1 - y).sum()
    if n_pos == 0 or n_neg == 0:
        return float("nan")
    return float((ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def rule_baseline(charts):
    """dt < 135ms -> stream, no learning at all (dt is inverted from feature 0)."""
    print("\n== rule baseline (per-object dt < 135ms -> stream)")
    for c in charts:
        dt = np.expm1(c["feats"][:, 0] * np.log1p(2000.0))
        dt[0] = dt[1] if len(dt) > 1 else 0
        pred = (dt < 135).astype(np.float32)
        m = c["mask"]
        acc = ((pred[m] >= 0.5) == (c["y"][m, 0] >= 0.5)).mean()
        print(f"  {c['name']}: stream-acc={acc:.3f} on {int(m.sum())} objects")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exports", nargs="+")
    args = ap.parse_args()
    charts = load_dataset(args.exports)
    if len(charts) < 2:
        raise SystemExit("need at least 2 charts")
    rule_baseline(charts)

    rich = max(charts, key=lambda c: c["mask"].sum())
    others = [c for c in charts if c is not rich]
    print(f"\ntrain on {rich['name']} ({rich['mask'].sum()} objects), test on others")
    report(train_eval([rich], others), "cross-map: rich -> others")

    for held in charts:
        rest = [c for c in charts if c is not held]
        if sum(c["mask"].sum() for c in rest) < 20:
            continue
        report(train_eval(rest, [held]), f"leave-out: {held['name']}")


if __name__ == "__main__":
    main()

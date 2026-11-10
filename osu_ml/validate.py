"""Parse a real osu! Songs folder and report parser / feature health."""

from __future__ import annotations

import argparse
import glob
import os
import traceback

import numpy as np

from .features import N_FEATURES, build_features
from .parse import parse_file


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("songs", nargs="?", default=os.path.expandvars(
        r"$LOCALAPPDATA/osu!/Songs"))
    ap.add_argument("--limit", type=int, default=300)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.songs, "**", "*.osu"), recursive=True))
    files = files[: args.limit]
    print(f"{len(files)} .osu files under {args.songs}")

    ok, failed, skipped = 0, [], 0
    objs, feats = [], []
    mins = np.full(N_FEATURES, np.inf)
    maxs = np.full(N_FEATURES, -np.inf)

    for path in files:
        try:
            text = open(path, "r", encoding="utf-8-sig", errors="replace").read()
            if "Mode: 3" in text or "Mode: 1" in text or "Mode: 2" in text:
                skipped += 1
                continue
            bm = parse_file(path)
            if not bm.objects:
                skipped += 1
                continue
            f = build_features(bm)
            if f.shape != (len(bm.objects), N_FEATURES) or not np.isfinite(f).all():
                failed.append((path, "bad features"))
                continue
            mins = np.minimum(mins, f.min(axis=0))
            maxs = np.maximum(maxs, f.max(axis=0))
            ok += 1
            objs.append(len(bm.objects))
            feats.append(f)
        except Exception:
            failed.append((path, traceback.format_exc(limit=1)))

    print(f"ok={ok} skipped(non-std/empty)={skipped} failed={len(failed)}")
    if objs:
        o = np.array(objs)
        print(f"objects/map: min={o.min()} median={int(np.median(o))} max={o.max()} "
              f"total={o.sum()}")
    if feats:
        allf = np.concatenate(feats)
        print("feature range check (min .. max):")
        for i in range(N_FEATURES):
            print(f"  {i:2d}  {mins[i]:+.3f} .. {maxs[i]:+.3f}")
    for path, err in failed[:5]:
        print("FAIL", os.path.basename(path), err)


if __name__ == "__main__":
    main()

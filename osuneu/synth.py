"""Synthetic beatmaps with known per-object pattern labels.

Purpose: let the whole pipeline (features -> model -> ONNX) run end-to-end
today, without waiting for human annotations. The labels are *not* the real
community labels; they only prove the plumbing and give a sanity baseline.
"""

from __future__ import annotations

import math
import random

import numpy as np

from .features import N_FEATURES, build_features
from .parse import Beatmap, HitObject

LABELS = ["jump", "stream", "tech", "alt", "precision", "reading"]
N_LABELS = len(LABELS)
SEG = 32

_SECTION_LABELS = {
    "stream": [0, 1, 0, 0, 0, 0],
    "jump":   [1, 0, 0, 0, 0, 0],
    "tech":   [0, 0, 1, 0, 0, 0],
    "alt":    [0, 0, 0, 1, 0, 0],
    "mixed":  [1, 1, 0, 0, 0, 0],
}


def _walk(rng: random.Random, x: float, y: float, dist: float, turn: float):
    ang = rng.uniform(0, 2 * math.pi) + turn
    nx, ny = x + dist * math.cos(ang), y + dist * math.sin(ang)
    if not (32 <= nx <= 480):
        nx = x - (nx - x) * 0.8
    if not (32 <= ny <= 352):
        ny = y - (ny - y) * 0.8
    return max(16.0, min(496.0, nx)), max(16.0, min(368.0, ny))


def make_map(rng: random.Random, max_objects: int = 1200) -> dict:
    bpm = rng.choice([150, 160, 170, 175, 180, 190, 200, 210])
    beat = 60000.0 / bpm
    bm = Beatmap(cs=round(rng.uniform(3.2, 5.8), 1),
                 ar=round(rng.uniform(7.5, 9.8), 1),
                 od=round(rng.uniform(7.0, 10.0), 1))
    bm.timing = [(0.0, beat, 1)]

    t = 1000.0
    x, y = rng.uniform(120, 400), rng.uniform(100, 280)
    obj_labels: list[list[int]] = []
    n_sections = rng.randint(4, 8)

    for _ in range(n_sections):
        kind = rng.choices(
            ["stream", "jump", "tech", "alt", "mixed"],
            weights=[30, 30, 15, 10, 15],
        )[0]
        base = _SECTION_LABELS[kind]
        n = rng.randint(48, 160)
        turn = 0.0

        for k in range(n):
            if len(bm.objects) >= max_objects:
                break

            if kind == "stream":
                dt, dist = beat / 4, rng.uniform(45, 90)
                turn = rng.uniform(-0.6, 0.6)
                o = HitObject(t, x, y, "circle")
            elif kind == "jump":
                dt, dist = beat / 2, rng.uniform(140, 420)
                turn = rng.choice([-1.0, 0.0, 1.0]) * rng.uniform(0.4, 1.4)
                o = HitObject(t, x, y, "circle")
            elif kind == "tech":
                dt = beat * rng.choice([1 / 6, 1 / 4, 1 / 3, 1 / 2])
                dist = rng.uniform(60, 300)
                turn = rng.uniform(-2.2, 2.2)
                if rng.random() < 0.18:
                    o = HitObject(t, x, y, "slider",
                                  length=rng.uniform(60, 220),
                                  slides=rng.choice([1, 1, 2]))
                else:
                    o = HitObject(t, x, y, "circle")
            elif kind == "alt":
                dt, dist = beat / 2, rng.uniform(80, 180)
                turn = rng.uniform(-1.2, 1.2)
                o = HitObject(t, x, y, "circle")
            else:  # mixed: stream / jump alternating in 8-note chunks
                if (k // 8) % 2 == 0:
                    dt, dist = beat / 4, rng.uniform(45, 90)
                else:
                    dt, dist = beat / 2, rng.uniform(140, 380)
                turn = rng.uniform(-1.0, 1.0)
                o = HitObject(t, x, y, "circle")

            x, y = _walk(rng, x, y, dist, turn)
            o.x, o.y, o.time = x, y, t
            if o.kind == "slider":
                velocity = bm.slider_multiplier * 100.0 / max(beat, 1.0)
                o.end_time = t + (o.length / velocity) * o.slides
            else:
                o.end_time = t
            bm.objects.append(o)
            obj_labels.append(list(base))
            t += dt

        t += beat * rng.uniform(1, 4)   # break between sections

    feats = build_features(bm)
    labels = np.array(obj_labels, dtype=np.float32)

    n_seg = len(labels) // SEG
    seg = labels[: n_seg * SEG].reshape(n_seg, SEG, N_LABELS).mean(axis=1) >= 0.5
    seg = seg.astype(np.float32)
    # equal weight per segment, so 1/4 streams don't outvote everything by density
    map_label = (seg.mean(axis=0) >= 0.5).astype(np.float32)

    return {
        "features": feats,
        "seg_labels": seg,
        "map_labels": map_label,
        "bpm": bpm,
        "objects": len(bm.objects),
        "beatmap": bm,
    }


def make_dataset(n_maps: int, seed: int = 0) -> list[dict]:
    rng = random.Random(seed)
    return [make_map(rng) for _ in range(n_maps)]


def to_osu_text(bm: Beatmap) -> str:
    lines = ["osu file format v14", "", "[General]", "Mode: 0", "",
             "[Difficulty]", f"CircleSize:{bm.cs}", f"ApproachRate:{bm.ar}",
             f"OverallDifficulty:{bm.od}", f"SliderMultiplier:{bm.slider_multiplier}",
             "", "[TimingPoints]"]
    for start, length, uninherited in bm.timing:
        lines.append(f"{start},{length},4,2,0,60,{uninherited},0")
    lines += ["", "[HitObjects]"]
    for o in bm.objects:
        if o.kind == "circle":
            lines.append(f"{int(o.x)},{int(o.y)},{int(o.time)},1,0,0:0:0:0:")
        elif o.kind == "slider":
            lines.append(f"{int(o.x)},{int(o.y)},{int(o.time)},2,0,"
                         f"L|{int(o.x) + 60}:{int(o.y)},{o.slides},{int(o.length)}")
        else:
            lines.append(f"{int(o.x)},{int(o.y)},{int(o.time)},8,0,{int(o.end_time)}")
    return "\n".join(lines)

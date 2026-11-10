"""Per-hitobject features.

The exact order below is the contract between Python training and the C# side.
Do not reorder without bumping FEATURE_VERSION.

  0  log1p(dt_ms) / log1p(2000)          time since previous object
  1  min(dist_px, 512) / 512             cursor displacement to reach this object
  2  cos(angle)                          +1 straight ahead, -1 full reversal
  3  |sin(angle)|                        how much the direction changes
  4  min(speed, 2.0) / 2.0               dist / dt, px per ms
  5  is_circle
  6  is_slider
  7  is_spinner
  8  min(slider_len, 512) / 512
  9  min(slides, 4) / 4
 10  x / 512 - 0.5
 11  y / 384 - 0.5
 12  min(duration_ms, 4000) / 4000       slider/spinner length in time
 13  min(density_500ms, 16) / 16         objects within +-250 ms
 14  log1p(dt / beat) / log1p(4)         snap ratio (1/4 -> 0.25)
 15  beat_length_ms / 1000               BPM proxy
 16  cs / 10
 17  ar / 10
 18  od / 10
"""

from __future__ import annotations

import math

import numpy as np

from .parse import Beatmap

FEATURE_VERSION = 1
N_FEATURES = 19


def build_features(bm: Beatmap) -> np.ndarray:
    objs = bm.objects
    t = len(objs)
    out = np.zeros((t, N_FEATURES), dtype=np.float32)
    if t == 0:
        return out

    times = np.array([o.time for o in objs], dtype=np.float64)

    for i, o in enumerate(objs):
        prev = objs[i - 1] if i > 0 else None
        nxt = objs[i + 1] if i + 1 < t else None

        dt = o.time - prev.time if prev else 0.0
        dx = o.x - prev.x if prev else 0.0
        dy = o.y - prev.y if prev else 0.0
        dist = math.hypot(dx, dy)

        if prev and nxt:
            ax, ay = o.x - prev.x, o.y - prev.y
            bx, by = nxt.x - o.x, nxt.y - o.y
            na, nb = math.hypot(ax, ay), math.hypot(bx, by)
            if na > 1e-6 and nb > 1e-6:
                cos = (ax * bx + ay * by) / (na * nb)
                cos = max(-1.0, min(1.0, cos))
                ang_cos = cos
                ang_sin = math.sqrt(max(0.0, 1.0 - cos * cos))
            else:
                ang_cos, ang_sin = 1.0, 0.0
        else:
            ang_cos, ang_sin = 1.0, 0.0

        speed = dist / dt if dt > 0 else 0.0
        beat = bm.beat_length_at(o.time)
        snap = dt / beat if beat > 0 else 0.0
        dens = int(np.sum(np.abs(times - o.time) <= 250.0))

        out[i] = (
            min(math.log1p(max(dt, 0.0)) / math.log1p(2000.0), 1.0),
            min(dist, 512.0) / 512.0,
            ang_cos,
            ang_sin,
            min(speed, 2.0) / 2.0,
            1.0 if o.kind == "circle" else 0.0,
            1.0 if o.kind == "slider" else 0.0,
            1.0 if o.kind == "spinner" else 0.0,
            min(o.length, 512.0) / 512.0,
            min(o.slides, 4) / 4.0,
            o.x / 512.0 - 0.5,
            o.y / 384.0 - 0.5,
            min(max(o.end_time - o.time, 0.0), 4000.0) / 4000.0,
            min(dens, 16) / 16.0,
            min(math.log1p(max(snap, 0.0)) / math.log1p(4.0), 1.0),
            beat / 1000.0,
            bm.cs / 10.0,
            bm.ar / 10.0,
            bm.od / 10.0,
        )
    return out

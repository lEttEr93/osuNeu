""".osu parser (osu!standard subset), no third-party deps.

Only what the feature extractor needs: difficulty settings, timing points and
the three osu! hitobject kinds. Slider duration is approximated with the legacy
formula (good enough for features, not for scoring).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class HitObject:
    time: float
    x: float
    y: float
    kind: str = "circle"          # circle | slider | spinner
    end_time: float = 0.0
    length: float = 0.0           # slider path length in px
    slides: int = 1


@dataclass
class Beatmap:
    cs: float = 4.0
    ar: float = 8.0
    od: float = 8.0
    slider_multiplier: float = 1.4
    objects: list[HitObject] = field(default_factory=list)
    timing: list[tuple[float, float, int]] = field(default_factory=list)

    def beat_length_at(self, t: float) -> float:
        beat = 500.0
        for start, length, uninherited in self.timing:
            if start > t:
                break
            if uninherited:
                beat = length
        return beat


def _f(v: str, default: float = 0.0) -> float:
    try:
        return float(v)
    except ValueError:
        return default


def parse_osu(text: str) -> Beatmap:
    bm = Beatmap()
    section = ""
    pending_timing: list[tuple[float, float, int]] = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1]
            continue

        if section == "Difficulty":
            if line.startswith("CircleSize:"):
                bm.cs = _f(line.split(":", 1)[1])
            elif line.startswith("ApproachRate:"):
                bm.ar = _f(line.split(":", 1)[1])
            elif line.startswith("OverallDifficulty:"):
                bm.od = _f(line.split(":", 1)[1])
            elif line.startswith("SliderMultiplier:"):
                bm.slider_multiplier = _f(line.split(":", 1)[1], 1.4)

        elif section == "TimingPoints":
            parts = line.split(",")
            if len(parts) >= 2:
                t = _f(parts[0])
                beat = _f(parts[1], 500.0)
                uninherited = int(_f(parts[6], 1)) if len(parts) > 6 else 1
                pending_timing.append((t, beat, uninherited))

        elif section == "HitObjects":
            parts = line.split(",")
            if len(parts) < 4:
                continue
            x, y, t = _f(parts[0]), _f(parts[1]), _f(parts[2])
            kind_bits = int(_f(parts[3]))
            if kind_bits & 8:                       # spinner
                end = _f(parts[5]) if len(parts) > 5 else t + 1000
                bm.objects.append(HitObject(t, x, y, "spinner", end))
            elif kind_bits & 2:                     # slider
                slides = int(_f(parts[6], 1)) if len(parts) > 6 else 1
                length = _f(parts[7]) if len(parts) > 7 else 0.0
                bm.objects.append(HitObject(t, x, y, "slider", t, length, max(1, slides)))
            else:                                   # circle
                bm.objects.append(HitObject(t, x, y, "circle", t))

    bm.timing = sorted(pending_timing, key=lambda p: p[0])

    # approximate slider duration with the legacy formula
    for o in bm.objects:
        if o.kind != "slider":
            continue
        beat = bm.beat_length_at(o.time)
        velocity = bm.slider_multiplier * 100.0 / max(beat, 1.0)   # px per ms
        o.end_time = o.time + (o.length / velocity if velocity > 0 else 0.0) * o.slides

    bm.objects.sort(key=lambda o: o.time)
    return bm


def parse_file(path: str) -> Beatmap:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        return parse_osu(f.read())

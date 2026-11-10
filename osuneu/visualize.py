"""Render a two-lane scroll of human annotations vs model predictions.

Usage:
    python -m osuneu.visualize map.json [map2.json ...] --target map.json --out report.html

The model is trained on every export except the target (leave-one-out) unless
--train-self is passed. Output is a single self-contained HTML file.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


import numpy as np
import torch

from .fit_annotations import LABELS, Net, load_dataset, locate_beatmap, windows
from .features import build_features

PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>osu!neu · 标注 vs 预测 · @@TITLE@@</title>
<style>
 :root{color-scheme:dark;--bg:#0f1117;--panel:#171a22;--line:#2b3040;--text:#e9ecf5;--muted:#8b93a7;
       --stream:#c4f277;--jump:#ff8fbd;--tech:#80caff;--reading:#cab0ff;--other:#ffcc80}
 *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--text);
   font:13px system-ui,"Microsoft YaHei",sans-serif}
 header{position:relative;z-index:2;background:var(--bg);padding:14px 20px;border-bottom:1px solid var(--line);display:flex;gap:18px;align-items:baseline;flex-wrap:wrap}
 h1{font-size:16px;margin:0} .meta{color:var(--muted);font-size:12px}
 .tools{margin-left:auto;display:flex;gap:8px;align-items:center}
 button{background:#222834;border:1px solid var(--line);color:var(--text);border-radius:6px;
        padding:5px 10px;cursor:pointer;font-size:12px}
 button:hover{border-color:var(--stream)}
 .lane{padding:10px 0 4px}
 .laneHead{display:flex;gap:12px;align-items:baseline;padding:0 20px 6px}
 .laneHead b{font-size:12px;letter-spacing:1px;color:var(--stream)}
 .laneHead span{color:var(--muted);font-size:11px}
 .scroll{overflow-x:auto;overflow-y:hidden;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
 .scroll::-webkit-scrollbar{height:10px}
 .scroll::-webkit-scrollbar-thumb{background:#2f3646;border-radius:5px}
 canvas{display:block}
 .legend{display:flex;gap:14px;padding:10px 20px;color:var(--muted);font-size:11px;flex-wrap:wrap}
 .dot{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:5px;vertical-align:-1px}
 footer{padding:10px 20px;color:#6c7488;font-size:11px}
</style></head><body>
<header>
  <h1>@@TITLE@@</h1>
  <div class="meta">@@ARTIST@@ · @@VERSION@@ · @@BPM@@ BPM · CS @@CS@@ / AR @@AR@@ · @@SECONDS@@ s · 物件 @@OBJECTS@@</div>
  <div class="tools">
    <span class="meta">@@TRAINED@@</span>
    <button id="zoomOut">−</button><button id="zoomIn">+</button><button id="fit">全谱</button>
  </div>
</header>

<div class="lane">
  <div class="laneHead"><b>人工标注</b><span>@@NANN@@ 段</span></div>
  <div class="scroll" id="scrollA"><canvas id="laneA" height="86"></canvas></div>
</div>
<div class="lane">
  <div class="laneHead"><b>模型预测</b><span>逐物件概率，窗口 ±2 物件</span></div>
  <div class="scroll" id="scrollB"><canvas id="laneB" height="150"></canvas></div>
</div>
<div class="legend">
  <span><i class="dot" style="background:var(--stream)"></i>stream</span>
  <span><i class="dot" style="background:var(--jump)"></i>jump</span>
  <span><i class="dot" style="background:var(--tech)"></i>tech</span>
  <span><i class="dot" style="background:var(--reading)"></i>reading</span>
  <span><i class="dot" style="background:var(--other)"></i>其他</span>
  <span>滚轮缩放 · 拖拽/滚动条平移 · 两个卷轴同步</span>
</div>
<footer>osu!neu / annotation vs prediction — 模型为留一验证（除目标图外训练），仅作可行性参考</footer>

<script>
const DATA = @@PAYLOAD@@;
const COLORS = {stream:'#c4f277', jump:'#ff8fbd', tech:'#80caff', reading:'#cab0ff'};
const state = { pxPerMs: 0 };
const dur = Math.max(DATA.durationMs, ...DATA.objects.map(o => o.t));
const scA = document.getElementById('scrollA'), scB = document.getElementById('scrollB');
const cA = document.getElementById('laneA'), cB = document.getElementById('laneB');

function laneWidth(){ return Math.max(600, dur * state.pxPerMs); }

function tickStep(){
  const target = 90 / state.pxPerMs;               // ~90px between ticks
  const steps = [500,1000,2000,5000,10000,15000,30000,60000,120000];
  return steps.find(v => v >= target) || 120000;
}

function syncScroll(from, to){
  if (Math.abs(to.scrollLeft - from.scrollLeft) > 1) to.scrollLeft = from.scrollLeft;
}

function draw(){
  const W = laneWidth();
  const dpr = window.devicePixelRatio || 1;
  for (const [cv, h] of [[cA, 86], [cB, 150]]){
    cv.style.width = W + 'px'; cv.style.height = h + 'px';
    cv.width = Math.round(W * dpr); cv.height = Math.round(h * dpr);
    const ctx = cv.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, W, h);
    ctx.fillStyle = '#12151d'; ctx.fillRect(0, 0, W, h);
    ctx.strokeStyle = '#20242e'; ctx.lineWidth = 1;
    const step = tickStep();
    for (let t = 0; t <= dur; t += step){
      const x = t * state.pxPerMs + .5;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
      if (cv === cA){
        ctx.fillStyle = '#6c7488'; ctx.font = '10px monospace';
        const m = Math.floor(t / 60000), s = Math.floor(t / 1000) % 60;
        ctx.fillText(`${m}:${String(s).padStart(2,'0')}`, x + 4, 12);
      }
    }
  }
  drawAnnotations();
  drawPredictions();
}

function drawAnnotations(){
  const ctx = cA.getContext('2d');
  const W = laneWidth(), lanes = 3, top = 20, laneH = 20;
  const sorted = [...DATA.annotations].sort((a, b) => a.start - b.start);
  const ends = new Array(lanes).fill(-1);
  for (const a of sorted){
    let lane = 0;
    while (lane < lanes && ends[lane] > a.start) lane++;
    if (lane === lanes) lane = 0;
    ends[lane] = a.end;
    const x = a.start * state.pxPerMs, w = Math.max(2, (a.end - a.start) * state.pxPerMs);
    const y = top + lane * laneH;
    ctx.fillStyle = (COLORS[a.labels[0]] || '#ffcc80') + '33';
    ctx.fillRect(x, y, w, laneH - 4);
    ctx.strokeStyle = COLORS[a.labels[0]] || '#ffcc80';
    ctx.strokeRect(x + .5, y + .5, w - 1, laneH - 5);
    if (w > 42){
      ctx.fillStyle = '#e9ecf5'; ctx.font = '10px system-ui';
      ctx.fillText(a.labels.join('+'), x + 4, y + 11);
    }
  }
}

function drawPredictions(){
  const ctx = cB.getContext('2d');
  const W = laneWidth(), h = 150, pad = 10;
  const rows = [{key: 0, color: '#c4f277', label: 'stream'},
                {key: 1, color: '#ff8fbd', label: 'jump'}];
  const rowH = (h - 2 * pad) / rows.length;
  rows.forEach((r, ri) => {
    const y = pad + ri * rowH;
    ctx.fillStyle = '#0d1016'; ctx.fillRect(0, y, W, rowH - 4);
    ctx.fillStyle = '#8b93a7'; ctx.font = '10px monospace';
    ctx.fillText(r.label, 4, y + 12);
    for (let i = 0; i < DATA.objects.length; i++){
      const o = DATA.objects[i];
      const next = DATA.objects[i + 1];
      const end = next ? next.t : DATA.durationMs;
      const x = o.t * state.pxPerMs;
      const w = Math.max(1.5, (end - o.t) * state.pxPerMs);
      const p = DATA.probs[i][r.key];
      const alpha = Math.round(28 + p * 220).toString(16).padStart(2, '0');
      ctx.fillStyle = r.color + alpha;
      ctx.fillRect(x, y + 16, w, rowH - 24);
    }
  });
}

function setZoom(z, anchorPx){
  const old = state.pxPerMs;
  state.pxPerMs = Math.max(0.002, Math.min(2, state.pxPerMs * z));
  const keep = anchorPx * (state.pxPerMs / old);
  draw();
  scA.scrollLeft = scB.scrollLeft = Math.max(0, keep - (anchorPx - scA.getBoundingClientRect().left));
}

document.getElementById('zoomIn').onclick = () => setZoom(1.6, scA.scrollLeft + innerWidth/2);
document.getElementById('zoomOut').onclick = () => setZoom(1/1.6, scA.scrollLeft + innerWidth/2);
document.getElementById('fit').onclick = () => { state.pxPerMs = 0; fit(); draw(); };

function fit(){ state.pxPerMs = Math.max(0.002, (scA.clientWidth - 40) / dur); }

scA.addEventListener('scroll', () => syncScroll(scA, scB));
scB.addEventListener('scroll', () => syncScroll(scB, scA));
for (const el of [scA, scB]){
  el.addEventListener('wheel', (e) => {
    if (!e.ctrlKey && !e.shiftKey) return;           // 普通滚动保持平移
    e.preventDefault();
    setZoom(e.deltaY > 0 ? 1/1.2 : 1.2, e.clientX);
  }, {passive: false});
}
addEventListener('resize', () => { if (state.pxPerMs <= 0.0021) { fit(); draw(); } });
fit(); draw();
</script></body></html>
"""


def predict(target, model):
    x = torch.tensor(windows(target["feats"]))
    with torch.no_grad():
        return torch.sigmoid(model(x)).numpy()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exports", nargs="+")
    ap.add_argument("--target", required=True)
    ap.add_argument("--out", default="viz.html")
    ap.add_argument("--train-self", action="store_true")
    args = ap.parse_args()

    charts = load_dataset(args.exports)
    target_path = Path(args.target).stem
    target = next((c for c in charts if c["name"] == target_path), None)
    if target is None:
        raise SystemExit("target not found among exports")

    train = charts if args.train_self else [c for c in charts if c is not target]
    if not train:
        raise SystemExit("nothing to train on")

    xs = np.concatenate([windows(c["feats"])[c["mask"]] for c in train])
    ys = np.concatenate([c["y"][c["mask"]] for c in train])
    torch.manual_seed(0)
    model = Net(xs.shape[1], len(LABELS))
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-3)
    xt, yt = torch.tensor(xs), torch.tensor(ys)
    for _ in range(400):
        opt.zero_grad()
        loss = torch.nn.functional.binary_cross_entropy_with_logits(model(xt), yt)
        loss.backward()
        opt.step()
    model.eval()

    probs = predict(target, model)
    data = json.loads(Path(args.target).read_text(encoding="utf-8"))
    bm = locate_beatmap(data["beatmap"]["filename"])
    objects = [dict(t=o.time, x=round(o.x, 1), y=round(o.y, 1), k=o.kind) for o in bm.objects]
    payload = dict(
        durationMs=bm.objects[-1].end_time,
        objects=objects,
        probs=[[round(float(p[0]), 4), round(float(p[1]), 4)] for p in probs],
        annotations=[],
    )
    for a in data["annotations"]:
        payload["annotations"].append(dict(start=a["startMs"], end=a["endMs"],
                                           labels=[l for l in a["labels"] if l in LABELS] or a["labels"]))
    meta = data["beatmap"]
    trained = ("训练：本图（过拟合参考）" if args.train_self
               else "训练：" + " / ".join(c["name"] for c in train))
    html = (PAGE
            .replace("@@TITLE@@", meta.get("title", ""))
            .replace("@@ARTIST@@", meta.get("artist", ""))
            .replace("@@VERSION@@", str(meta.get("version", "")))
            .replace("@@BPM@@", str(round(meta.get("bpm") or 0, 1)))
            .replace("@@CS@@", str(meta.get("cs")))
            .replace("@@AR@@", str(meta.get("ar")))
            .replace("@@SECONDS@@", str(round(payload["durationMs"] / 1000, 1)))
            .replace("@@OBJECTS@@", str(len(objects)))
            .replace("@@NANN@@", str(len(payload["annotations"])))
            .replace("@@TRAINED@@", trained)
            .replace("@@PAYLOAD@@", json.dumps(payload, ensure_ascii=False)))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({out.stat().st_size/1024:.0f} KB, {len(objects)} objects)")


if __name__ == "__main__":
    main()

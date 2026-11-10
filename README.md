# osu!neu

## 谱面区间标注器

双击 Windows 下的 `annotate.cmd`，或在仓库目录运行：

```powershell
.venv\Scripts\python.exe -m osuneu.annotator
```

浏览器会打开 `http://127.0.0.1:8765`。标注器仅使用 Python 标准库，不需要加载模型、GPU 或安装网页依赖。

- 打开或拖入 `.osu` / `.osz`；谱包内可选择 standard 难度，并自动加载对应音乐。单独的 `.osu` 可手动添加音频。
- 时间轴拖动定位；Shift + 拖动框选；拖动 I / O 边界修改选区。滚轮缩放，Shift + 滚轮或下方滚动条平移。
- I / O 将当前时间设为起点 / 终点，也可直接输入 `分:秒.毫秒` 或秒数。时间边界不吸附物件。
- 支持变速、循环选区、多标签、自定义标签、备注、编辑与删除。空格播放，左右键微调 100ms，Shift + 左右键微调 1s。
- 标注按谱面 SHA-256 自动保存在当前浏览器；导出 JSON 用于持久备份和后续训练。导入时核对谱面哈希，同 ID 标注更新，不同 ID 合并。

JSON 使用 `schema: osuneu.annotations`、`version: 1`，区间为 `startMs` / `endMs`，标签为独立的 `labels` 数组。导出同时附带区间内物件起点对应的 **0 起始** `objectIndices`，原始毫秒边界保留。未标注区间代表未知，不能直接视为负样本。标注器暂不接入模型预测。

预览支持圆圈、Bezier / 圆弧 / Catmull / 直线滑条、重复滑条、转盘和 AR / CS；滑条时长考虑 SV 与红线重置。它是标注预览，不是完整游戏引擎：尚未实现 stacking、皮肤、storyboard、视频、击打音效或官方 autoplay 光标。演示为无音频的合成谱面。音乐依赖浏览器支持的音频格式。

检查：`python -m unittest discover -s tests`。更换端口：`python -m osuneu.annotator --port 8766`。

---

> **Neu** = Neural。给「谱面键型」做小体量模型的可运行骨架：
> **特征契约 + 0.33 MB 模型 + 训练/导出脚本 + 合成数据自检**。
> 仓库：https://github.com/lEttEr93/osuNeu

> ⚠️ 现在仓库里的 `model.pt` 是在**合成谱面**上训练的，它的数字只证明管线通了，
> **没有任何现实意义**。真实价值要等接上官方 user tags 和你自己标的片段。

---

## 快速开始

```bash
# 环境（uv 已装好）
uv venv --python 3.14 .venv
uv pip install --python .venv/Scripts/python.exe torch onnx onnxruntime numpy

# 模型规模
.venv/Scripts/python.exe -m osuneu.model

# 合成数据训练（CPU，约 1 分钟）
.venv/Scripts/python.exe -m osuneu.train --maps 600 --epochs 10

# 导出 ONNX 并验证数值一致性
.venv/Scripts/python.exe -m osuneu.export_onnx

# 用真实 .osu 跑一遍（解析 -> 特征 -> onnxruntime）
.venv/Scripts/python.exe -m osuneu.infer "path/to/map.osu"

# 扫整个 Songs 目录，检查解析/特征健康度
.venv/Scripts/python.exe -m osuneu.validate
```

本机实测：242 个 `.osu` 里 35 个是标准模式，解析 **0 失败、0 NaN**，
物件数 34–1343；ONNX 单图推理毫秒级。

---

## 输入 / 输出契约

```
tokens      float32 [batch, T, 19]    每物件一行
   ↓
seg_logits  float32 [batch, N, 6]     N = ceil(T/32)，每 32 个物件一段
map_logits  float32 [batch, 6]        attention 池化后的整图分（弱标签用）
seg_weights float32 [batch, N]        attention 权重（可当"重点段落"可视化）
```

6 个标签：`jump, stream, tech, alt, precision, reading`（对应官方 user tags 的一级分类）。

### 19 维特征（顺序即契约，见 `osuneu/features.py`）

| # | 特征 | 说明 |
|---|---|---|
| 0 | `log1p(dt)/log1p(2000)` | 与上一物件的时间差 |
| 1 | `dist/512` | 到当前位置的位移 |
| 2 | `cos(angle)` | +1 直行，−1 完全折返 |
| 3 | `abs(sin(angle))` | 转向量 |
| 4 | `speed/2` | px/ms |
| 5–7 | circle / slider / spinner | one-hot |
| 8 | `slider_len/512` | |
| 9 | `slides/4` | |
| 10–11 | `x/512-0.5`, `y/384-0.5` | 归一化坐标 |
| 12 | `duration/4000` | 滑条/转盘时长 |
| 13 | `density/16` | ±250ms 内物件数 |
| 14 | `log1p(dt/beat)/log1p(4)` | snap 比（1/4 → 0.25） |
| 15 | `beat/1000` | BPM 代理 |
| 16–18 | `cs/10`, `ar/10`, `od/10` | 难度设置 |

改顺序 = 必须同时改 C# 侧，并把 `FEATURE_VERSION` +1。

---

## 模型

```
Conv1d(19→64, k=5)
3 × ResidualBlock(64, dilation=1,2,4)   # conv-GN-relu + 残差
每 32 个物件 mean-pool 成一段
  ├─ seg_head: Linear→GELU→Linear(64→6) → 每段 6 个 logit
  └─ attention 池化 → map_head(64→6)    → 整图 6 个 logit（弱标签训练用）
```

| 版本 | 参数 | 体积（fp32 / ONNX） | 单图 CPU 推理 |
|---|---|---|---|
| **默认** `ch=64, 3 blocks` | **85,645** | 0.33 MB / **349 KB** | 毫秒级 |
| 极小 `ch=32, 2 blocks` | 16,941 | 0.06 MB | 更快，容量可能不够 |

**为什么不是 Transformer**：真实标注大概率只有几千条、以局部模式为主，卷积的归纳偏置（局部性 + 平移等变）
比注意力更省数据；而且 ONNX 导出和 CPU 推理都更简单。等到有 10⁵ 级标注再考虑换。

---

## 合成自检结果（**仅证明管线**）

600 张程序生成的谱面，mapper-disjoint 不需要（全是合成的），验证集 120 张：

```
epoch 10: micro_f1=0.925  jump=0.985  stream=0.998  tech=1.000
```

段级 AUC 0.99+。这说明**特征和结构足够把「跳/串」这类形态学差异学出来**——
但也仅此而已，合成数据的标签是我自己生成的，不能说明真实键型。

---

## 接真实数据的三条路

1. **弱标签（先做这个）**：官方 user tags 是 map 级标签（≥5 票才显示）。
   训练时只开 `map_logits` + attention，`seg_logits` 不监督——就是 MIL。
   推理时仍然输出每段分数，attention 权重告诉你"模型认为重点在哪"。
2. **片段标注（你的标注器）**：一旦有了 `(物件区间, 标签)`，直接监督 `seg_logits`，
   map 级用 mean/max 聚合。这条路和 1 可以混用。
3. **autoplay 轨迹**：作为第二条输入分支（60Hz 帧 → 1D CNN），和物件特征拼接。
   先做对照实验，别默认它更好。

---

## 评估协议（别跳过）

- **按 mapper 切分**，不是随机切分——否则模型学的是「这个 mapper 的风格」；
- **样本效率曲线**：200 / 500 / 1000 / 2000 张，看轨迹分支是不是更省数据；
- **基线**：规则版（`aim/speed` 比 1.16、`slider_factor`、间距阈值）先跑一遍，
  NN 必须显著超过它才值得上线；
- 报告每类 AUC + 校准（ECE），不要只报 accuracy。

---

## C# 侧接入

```csharp
// Microsoft.ML.OnnxRuntime
using var session = new InferenceSession("pattern_model.onnx");
var input = new DenseTensor<float>(features, new[] { 1, t, 19 });
var outputs = session.Run(new[] { NamedOnnxValue.CreateFromTensor("tokens", input) });
// seg_logits: [1, N, 6] -> sigmoid -> 每段分数
```

`features` 必须和 Python 侧**逐位一致**（同样的归一化、同样的顺序）。
建议在 C# 里写一个 `PatternFeatures.Build(osuText)`，并和 Python 对同一张图 diff 一次。

---

## 已知限制

- 19 维特征丢了不少信息（滑条曲线、堆叠、timing 变化都只是近似）；
- 没实现 stacking 计算（`stack` 相关特征缺席）；
- 滑条时长用 legacy 公式近似，不是精确值；
- 合成数据的标签是程序生成的，`precision` / `reading` 两类根本没生成；
- attention 头还没在真实弱标签上训练过。

---

## 目录

```
osuneu/parse.py      .osu 解析（无第三方依赖）
osuneu/features.py   19 维特征（契约在这里）
osuneu/synth.py      合成谱面 + 标签
osuneu/model.py      TinyPatternNet
osuneu/train.py      训练循环 + 评估
osuneu/export_onnx.py 导出 + 数值一致性检查
osuneu/diag.py       段级 / 图级 AUC 诊断
```

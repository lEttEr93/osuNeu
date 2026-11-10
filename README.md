# osu-pattern-ml

给「谱面键型」做小体量模型的可运行骨架：**特征契约 + 0.33 MB 模型 + 训练/导出脚本 + 合成数据自检**。

> ⚠️ 现在仓库里的 `model.pt` 是在**合成谱面**上训练的，它的数字只证明管线通了，
> **没有任何现实意义**。真实价值要等接上官方 user tags 和你自己标的片段。

---

## 快速开始

```bash
# 环境（uv 已装好）
uv venv --python 3.14 .venv
uv pip install --python .venv/Scripts/python.exe torch onnx onnxruntime numpy

# 模型规模
.venv/Scripts/python.exe -m osu_ml.model

# 合成数据训练（CPU，约 1 分钟）
.venv/Scripts/python.exe -m osu_ml.train --maps 600 --epochs 10

# 导出 ONNX 并验证数值一致性
.venv/Scripts/python.exe -m osu_ml.export_onnx

# 用真实 .osu 跑一遍（解析 -> 特征 -> onnxruntime）
.venv/Scripts/python.exe -m osu_ml.infer "path/to/map.osu"

# 扫整个 Songs 目录，检查解析/特征健康度
.venv/Scripts/python.exe -m osu_ml.validate
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

### 19 维特征（顺序即契约，见 `osu_ml/features.py`）

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
osu_ml/parse.py      .osu 解析（无第三方依赖）
osu_ml/features.py   19 维特征（契约在这里）
osu_ml/synth.py      合成谱面 + 标签
osu_ml/model.py      TinyPatternNet
osu_ml/train.py      训练循环 + 评估
osu_ml/export_onnx.py 导出 + 数值一致性检查
osu_ml/diag.py       段级 / 图级 AUC 诊断
```

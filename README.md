# osu!neu

## 谱面区间标注器

双击 Windows 下的 `annotate.cmd`，或在仓库目录运行：

```powershell
.venv\Scripts\python.exe -m osuneu.desktop
```

默认打开独立的 Qt 桌面窗口，不使用浏览器配置、扩展或鼠标手势。首次安装桌面依赖：`uv sync --extra desktop`。标注器不加载模型。原来的浏览器入口仍可通过 `python -m osuneu.annotator` 使用。

- 打开或拖入 `.osu` / `.osz`；谱包内可选择 standard 难度，并自动加载对应音乐。单独的 `.osu` 可手动添加音频。
- **随机谱面**：点左上角「随机谱面」即可从 osu! 公开搜索 JSON 里抽一张 ranked 标准图，按 Roam 同款镜像链下载 `.osz`（`dl.sayobot.cn` → `txy1.sayobot.cn` → `catboy.best` → `beatconnect.io`），下载后直接进入标注，不再手动导入。谱包缓存在 `AI_CACHES/osuneu/beatmaps`，同一张不会重复下；某些镜像慢，超过 60 秒会报错，再点一次即可。后端也可直接 `POST /api/fetch {"set": 1234567}` 打开指定谱包。
- 时间轴左键单击定位、按住拖动实时预览；按住右键拖动框选，支持反向框选，不需要 Shift。左键拖动 I / O 边界修改选区。
- 按住鼠标中键拖动时间轴或下方滚动条平移；滚轮围绕鼠标位置缩放。下方滚动条仍支持左键操作。
- I / O 将当前时间设为起点 / 终点，也可直接输入 `分:秒.毫秒` 或秒数。时间边界不吸附物件。
- 支持变速、循环选区、多标签、自定义标签、备注、编辑与删除。空格播放，左右键微调 100ms，Shift + 左右键微调 1s。
- 标注按谱面 SHA-256 自动保存在桌面应用的独立 profile；导出 JSON 会弹出系统保存对话框。导入时核对谱面哈希，同 ID 标注更新，不同 ID 合并。旧浏览器标注可导出后导入桌面版。

桌面持久数据使用 `OSUNEU_DATA_DIR` 或 `--data-dir` 指定；默认复用 `artifacts/osuneu/*-desktop-studio` 中最新的目录，没有时通过工作区脚本创建。可删除的磁盘缓存使用 `AI_CACHES/osuneu`，不会使用浏览器用户目录。默认桌面服务端口为 8766，窗口关闭时服务随之退出。

启动器会检查编辑器是否实际载入。Qt 渲染进程崩溃或 15 秒内未就绪时，会自动重试兼容渲染方式，并记住成功配置。兼容方式只对编辑器子进程关闭 Chromium 沙箱，窗口限制访问本地编辑器资源；不改变系统或浏览器设置。启动日志保存在 `AI_ROOT/runs/osuneu/desktop-*.log`。删除 `AI_CACHES/osuneu/renderer.json` 可重新检测默认渲染方式。

JSON 使用 `schema: osuneu.annotations`、`version: 2`（v1 仍可导入，缺的字段按默认值补齐）。
区间仍是 `startMs` / `endMs`，导出附带区间内物件起点的 **0 起始** `objectIndices` 与 `objectCount`。

**v2 新增字段**（都是为了把「结构」和「间距」拆开、并区分「检查过」与「没看过」）：

| 层级 | 字段 | 取值 | 用途 |
|---|---|---|---|
| 顶层 | `session.annotator` / `session.mods` | 字符串 | 标注者身份与 MOD，做一致性分析时按人/按 MOD 分层 |
| 顶层 | `app` / `createdAt` | 版本、时间 | 追溯是哪版工具产出的 |
| `beatmap` | `cs` / `ar` / `od` / `bpm` | 数值 | 同一张图换 MOD 或改难度设置后仍能对上 |
| 每条标注 | `spacing` | `na` / `stack` / `tight` / `spaced` / `mixed` | **间距轴**：无位移（叠）、紧凑重叠、有间距、混合 |
| 每条标注 | `confidence` | 1–3 | 标注者对自己的确信度（与「强度」分开） |
| 每条标注 | `checked` | 布尔 | **已完整检查**。无标签 + `checked` = 「看过，没有这些模式」，与「没看过」区分 |
| 每条标注 | `annotator` / `mods` | 字符串 | 逐条记录，允许中途换人 |
| 每条标注 | `createdAt` / `updatedAt` | ISO 时间 | 修订历史 |

因此「无位移三连」可以同时写成 `labels: ["stream"]` + `spacing: "stack"`，
而「检查过但没有跳/串」写 `labels: []` + `checked: true`——这两条语义完全不同，训练时不能混。

预览支持圆圈、Bezier / 圆弧 / Catmull / 直线滑条、重复滑条、转盘和 AR / CS；滑条时长考虑 SV 与红线重置。它是标注预览，不是完整游戏引擎：尚未实现 stacking、皮肤、storyboard、视频、击打音效或官方 autoplay 光标。演示为无音频的合成谱面。音乐依赖浏览器支持的音频格式。

下拉框（难度 / 播放速度 / MOD / 间距 / 确信度）是页面内的自定义列表，不是系统 `<select>` 弹窗。
原因：Qt 的原生下拉弹窗在 150% 缩放下会比内容宽出一截、留一条白色空带（渲染缺陷），自绘列表可以绕开它，顺便统一深色样式。原生的 `<select>` 仍留在 DOM 里，只是隐藏，`.value` 与 `change` 事件契约不变。

检查：`python -m unittest discover -s tests`。更换桌面端口：`python -m osuneu.desktop --port 8767`。桌面交互测试见 `tests/desktop-ui.cjs`。

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

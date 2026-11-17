# chart2data

把**图表的截图**变成能用的东西，分两层：

- **层 1（几何）**：只认「图上有什么图形」——框、刻度、曲线像素点，产 `04_ir.json` + 干净重绘的 `clean.svg`，不解释数据语义；
- **层 2（数据）**：消费层 1 的 IR，做标定、采样、拟合，产数据表 + 函数式 + 数据坐标图 + 报告。

每一步都落盘并由 `manifest.json` 记 sha256，过程可查、可复核。

位图输入只依赖 `numpy` 与 `Pillow`，不需要 OpenCV、matplotlib、tesseract。**PDF 输入**额外需要 `pdfplumber`（走矢量层 + 文本层，免 OCR、免栅格化）。目标场景是**框内曲线**（折线/曲线，一条或多条），不是柱状图/热力图/散点语义提取。

## 快速开始

```bash
# 0) 依赖
pip install -r requirements.txt           # numpy + Pillow（+ pdfplumber，若要吃 PDF）

# 1) 先看工具能自动认出什么：框 + 刻度像素位置
python -m chart2data skeleton 截图.png -o 截图.calib.json

# 2) 打开 截图.calib.json，把 values 填成刻度对应的数据值
#    （工具不做 OCR，刻度数字由你看图填；也可以改用 "values_range": [min, max] 自动均分）

# 3) 抽取
python -m chart2data extract 截图.png --calib 截图.calib.json -o out/

# 不想标定也行：直接拿像素坐标（x=列号，y=框下边−行号，向上为正）
python -m chart2data extract 截图.png -o out/
```

**PDF 页**也直接吃（矢量+文本层，刻度数字自动从文本层读，不用手填）：

```bash
python -m chart2data skeleton 论文.pdf --page 3 -o 论文-p3.calib.json   # values 已自动填好
python -m chart2data extract 论文.pdf --page 3 --calib 论文-p3.calib.json -o out_pdf/
```

只看层 1（不标定、不拟合）：

```bash
python -m chart2data ir 截图.png -o out1/   # 04_ir.json + clean.svg + manifest.json
```

看 extract 的 outputs（层 1 + 层 2 全套，见 `INTERFACE.md` §10.3）：

| 文件 | 层 | 内容 |
|---|---|---|
| `01_input.json` … `04_ir.json` | 1 | 输入摘要、框、刻度、几何 IR |
| `clean.svg` | 1 | 由 IR 重绘的干净矢量图（像素坐标） |
| `05_calibration.json` … `07_fit.json` | 2 | 标定、系列清单、拟合结果 |
| `result.json` | 2 | 主结果（schema `chart2data/result@1`） |
| `table.csv` | 2 | 长表 `series,x,y,y_min,y_max` |
| `table_wide.csv` | 2 | 宽表（各系列 x 一致时） |
| `curve.svg` | 2 | 按数据坐标重绘的图（刻度值、图例、方程） |
| `overlay.png` | 2 | 原图 + 检测框 + 采样点，人眼校验用 |
| `report.md` | 2 | 短笔记：两层说明、标定、方程、表格、阶段清单、警告 |
| `manifest.json` | — | 阶段→文件→sha256（过程可查） |

可回查「见过没」：

```bash
python -m chart2data extract 截图.png --calib 截图.calib.json --remember -o out/
python -m chart2data ledger-find 截图.png     # 账本在 var/ledger.jsonl
```

## 示例

`tests/fixtures/` 里有两套图：

- `chart.png` / `chart.jpg` / `black_curve.png`：合成夹具，函数真值已知，供验收 round-trip；
- `sample_plot.png`：更像真实截图的示例（标题、轴标签、刻度数字、框外图例）。

`examples/sample_plot/` 是示例图的完整输出，可直接对照。

## 验收

```bash
python -m chart2data.tests.make_fixtures   # 重建合成夹具
python -m chart2data.tests.acceptance      # 机械验收（90 项）：位图/PDF round-trip、两层结构、失败语义、账本
```

验收判据值在 `tests/test_config.json`（语义在 `INTERFACE.md`）；断言的是**误差上限与退出码**，不是某次输出的具体数字。

## 已知边界

- **位图不做 OCR**：截图输入的刻度数字要人/agent 填进标定（PDF 输入不用，文本层直接读）。这是刻意的——OCR 装不上、也不值得为一张截图引一套依赖。
- **只拟合单值函数**：x 必须单调、y 单值；参数曲线（圆、闭合环）不拟合，`fit: null` 并给警告。
- **图例**：不自动识别；框内图例会被当曲线，`warnings` 会提示。
- **多条黑线**：会合成一个系列（同色无法区分），`warnings` 记一条。
- 框检测依赖「有完整矩形边框 + 大致白底」；无框截图请用 `--calib` 显式给像素标定（当前版本仍需框，见 `INTERFACE.md` §1）。
- 像素模式/彩色曲线在 JPEG 高压缩、渐变色、半透明填充下会退化。
- **PDF**：同色多条曲线会并成一条（按描边颜色分组，见 `INTERFACE.md` §10.5）；只认页面描边路径，不做 PDF 内的位图图；`ledger-find` 仍只收位图。

## 代码地图

| 模块 | 职责 |
|---|---|
| `ir.py` | 层 1（位图）：图 → 几何 IR + 像素采样点 |
| `pdfir.py` | 层 1（PDF）：矢量路径 + 文本层 → 同一份几何 IR |
| `semantic.py` | 层 2：IR + 标定 → 数据/拟合（不读原图） |
| `run.py` | 运行目录、分阶段落盘、manifest |
| `detect.py` | 背景/强墨判定、绘图框、刻度像素 |
| `calib.py` | 像素 ↔ 数据值（linear/log、显式/自动/像素模式） |
| `extract.py` | 彩色聚类与深色分系列、网格剔除、按列采样 |
| `fit.py` | 多项式拟合与选阶、方程格式化 |
| `render.py` | 干净 SVG 重绘、overlay 校验图 |
| `ledger.py` | sha256 + dHash 指纹、账本读写与命中 |
| `cli.py` | 四个子命令、位图/PDF 前端路由与退出码 |

契约（CLI、文件形状、失败语义、配置键语义）在 [`INTERFACE.md`](INTERFACE.md)。

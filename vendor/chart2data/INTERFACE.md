# chart2data 契约（INTERFACE）

> 本文件只写**语义**：键名、含义、谁读、行为、失败语义。**不写数值**。
> 一切可调参数的值见同目录 `config.json`（唯一值源）。
> 代码/验收脚本注释只写指针，如「语义见 INTERFACE.md §3」。

## 1. 目标与边界

把**确定图表**（标准绘图框、坐标轴、刻度、一条或多条曲线）的**截图/图片/PDF 页**，转成：

1. 曲线采样数据点（数据坐标）
2. 曲线拟合出来的函数式 + 残差（若该曲线是函数）
3. 干净的矢量图（SVG）与叠点校验图（PNG）
4. 一份可复核的 `report.md` 笔记
5. 可选的"见过没"账本记录（同一张图/近似图下次能命中）

**不做**：手写公式识别、相机拍摄的透视畸变照片、3D 图、热力图/柱状图语义解释、认人认物。

## 2. CLI

```
python -m chart2data extract IMAGE [-o OUT_DIR] [--calib CALIB] [--config CONFIG] [--remember] [--units pixel|data]
python -m chart2data ir IMAGE [-o OUT_DIR] [--config CONFIG]
python -m chart2data skeleton IMAGE [-o OUT_FILE] [--config CONFIG]
python -m chart2data ledger-find IMAGE [--config CONFIG]
```

### 2.1 `extract`

| 入参 | 语义 |
|---|---|
| `IMAGE` | 输入路径：位图（PNG/JPEG/WebP）或 PDF。PDF 走层1 的 PDF 前端（矢量路径 + 文本层，免 OCR，§10.5） |
| `-o/--out` | 输出目录；缺省见 config `cli.default_out_dir` |
| `--calib` | 标定文件（§4）。给了就用它；不给则尝试自动（§3.4） |
| `--config` | 覆盖默认 config.json 的配置文件（浅合并，键级覆盖） |
| `--remember` | 成功后把结果摘要写入账本（§6） |
| `--units` | `data`（默认，用标定换算成数据坐标）/ `pixel`（不标定，直接用像素坐标） |
| `--page` | PDF 页号（从 1 起，缺省第 1 页）；位图输入忽略 |

产出见 §10.2（层1 + 层2 全套，含 manifest）。

### 2.2 `skeleton`

只做**识别**：检出绘图框与刻度像素位置，输出一份**标定模板**（§4 的形状，附 `detected` 计数与提示），供人填数据值。位图输入时 `values` 为空；PDF 输入时若刻度标签是数字，会把 `values` 一并填好（可免手填）。退出码同 §5。

### 2.3 `ledger-find`

在账本里按图像指纹找"之前是不是处理过"。命中打印候选（时间、路径、系列名、拟合式、汉明距离）；未命中打印空结果。只读。

### 2.4 `ir`

只跑**层 1**（§10.1）：图 → 几何 IR + 干净重绘 SVG。不做标定、不拟合、不解释数据语义。产出 `01_input.json`、`02_frame.json`、`03_ticks.json`、`04_ir.json`、`clean.svg`、`manifest.json`（`command`=`ir`）。退出码同 §5。

## 3. 处理流程（行为契约）

### 3.1 读图与背景

读入 RGB；取四角小块的中位色作为背景色。像素按亮度分为：强墨（框线/刻度/曲线）、弱墨（网格）、背景。

### 3.2 框检测

用**强墨**的行/列计数找出长度接近整宽的横线与接近整高的竖线；取最外一圈为绘图框 `frame = {left, top, right, bottom}`（像素，含框线本身）。

**失败语义**：找不到成对的框线（少于一对横+一对竖）⇒ 退出码 `2`，stderr 提示"未检出绘图框，请用 --calib 显式给标定或换图"。

### 3.3 刻度检测

分别在框外（优先）与框内两条窄带里，找垂直于轴、且长度达到阈值的短线段；合并相邻列/行成组，取组中心为刻度像素位置。刻度值**不做 OCR**（见 §1），由 `--calib` 的 `values`/`values_range` 提供；`skeleton` 只报"检出几个"。

行为：框外带与框内带都检出时，取数量更多且间隔更均匀的一侧；主/次刻度按长度筛，长度不足的丢弃。

### 3.4 标定

标定 = 每个轴一条「像素位置 ↔ 数据值」映射。支持 `linear` 与 `log`（底 10）。

优先级：
1. `--calib` 给了 `pixels` + `values`（或 `values_range`）⇒ 最小二乘拟合映射；
2. `--calib` 只给了 `values`/`values_range`（没给 `pixels`）⇒ 先自动检刻度，再按顺序配对；数量不匹配 ⇒ 退出码 `4`，stderr 报两边数量；
3. 没给 `--calib` ⇒ 直接用像素坐标当数据坐标：`x` = 列号（向右），`y` = 框下边 − 行号（向上为正，原点在框左下角），并在 `warnings` 里写「未标定，坐标为像素」。

### 3.5 曲线提取

在框内（留边距）按颜色分系列；只有明显暗于背景（亮度差 ≥ `extract.ink_min_delta`）的像素算候选，以滤掉背景与压缩噪点：

- **彩色曲线**：以「最大通道差」作饱和度代理，聚类成若干代表色；每个代表色成一族像素；像素数不足的族丢弃。
- **黑色/深色曲线**：亮度低于深色阈值的像素，排除框线附近与网格色后成一族（可能多条黑线合一族，`warnings` 记一条）。
- **网格**：框内出现次数很多、灰度接近且呈长线的颜色判为网格色并剔除。

每条曲线：按列取曲线像素的**中位 y** 作采样点（可选步长），同时记录该列 y 的覆盖范围（多值/近竖直段用 hmm 标记）。图例区不自动识别，如框内含图例会污染系列，`warnings` 提示用 `--calib` 或换无图例截图。

**失败语义**：一条曲线都没提取到 ⇒ 结果正常写（`series: []`），退出码 `0`，但 `warnings` 必须含 "未提取到曲线"。

### 3.6 拟合

对每条系列，在其采样点 x 可排序且基本单值（函数形）时，按 1..`fit.degree_max` 次多项式拟合；从低阶起步，只有升一阶能把 RMSE 相对改善超过 `fit.min_rel_improve_frac` 时才升阶（防止把像素量化锯齿过拟合），输出：模型名、系数（从高次到低次）、RMSE、R²、可读方程。x 非单值（参数曲线）⇒ 不拟合，`fit: null`，`warnings` 记一条。

### 3.7 输出

每次 `extract` 都在 `OUT_DIR` 写全 §10.2 的两层产出（层 1：IR + 干净 SVG；层 2：数据表、函数、校验图、报告），并写 `manifest.json` 记录每个阶段的文件与 sha256。

## 4. 标定文件形状

```json
{
  "x": {"scale": "linear|log", "pixels": [..], "values": [..]},
  "y": {"scale": "linear|log", "pixels": [..], "values": [..]}
}
```

- `values` 为 null 时可用 `"values_range": [min, max]`（此时按像素位置线性/对数等距生成 values，长度自动对齐 `pixels`）。
- 两个字段都给 `pixels` 与 `values` 时长度必须一致（或 `pixels` 省略，见 §3.4-2）。
- `log` 标定要求数据值 > 0；违反 ⇒ 退出码 `4`。

## 5. 退出码

| 码 | 含义 |
|---|---|
| 0 | 正常（可有 warnings） |
| 2 | 未检出绘图框 |
| 3 | 输入不可读/不是图片 |
| 4 | 标定参数非法（长度不匹配、log 轴出现非正数等） |
| 5 | 内部错误（带 traceback 摘要） |

## 6. 账本（ledger）

JSONL，一行一条：

```json
{"ts": "...", "sha256": "...", "dhash": "16 hex chars", "path": "...", "series": [{"name": "...", "model": "poly2", "equation": "..."}], "calib": {...}}
```

`--remember` 追加；`ledger-find` 按 `sha256` 精确命中，或按 `dhash` 汉明距离（阈值见 config `ledger.phash_max_dist`）给近似命中。账本不存原图，只存指纹与摘要；路径写当时路径，文件可能已移动，仅供引用。

## 7. result.json schema

```json
{
  "schema": "chart2data/result@1",
  "image": {"path": "...", "sha256": "...", "width": 0, "height": 0},
  "frame": {"left": 0, "top": 0, "right": 0, "bottom": 0},
  "calibration": {
    "x": {"scale": "linear", "pixels": [..], "values": [..], "mode": "explicit|auto|pixel"},
    "y": {...}
  },
  "series": [
    {
      "name": "c0",
      "color": [r, g, b],
      "n_points": 0,
      "x": [..], "y": [..],
      "y_min": [..], "y_max": [..],
      "fit": {"model": "poly2", "coeffs": [..], "rmse": 0.0, "r2": 0.0, "equation": "..."} 
    }
  ],
  "warnings": ["..."]
}
```

`fit` 为 null 表示不拟合。

## 8. 配置键（语义；值见 config.json）

| 键 | 谁读 | 含义 |
|---|---|---|
| `background.corner_frac` | detect | 取四角多大比例的块估背景色 |
| `frame.ink_delta` | detect | 强墨阈值 = 背景亮度 − 该值 |
| `frame.line_ratio` | detect | 一行/列强墨占比达到多少算框线 |
| `frame.min_line_len_px` | detect | 框线候选的最小绝对长度 |
| `ticks.band_px` | detect | 刻度检测窄带宽度 |
| `ticks.min_count_px` | detect | 窄带内该列/行最少强墨像素 |
| `ticks.min_extent_px` | detect | 刻度线段最小长度（滤次刻度） |
| `ticks.group_gap_px` | detect | 合并相邻刻度列的间隙 |
| `ticks.max_ticks` | detect | 单轴刻度上限，超出视为误检 |
| `extract.margin_px` | extract | 框内留边，避免把框线当曲线 |
| `extract.sat_diff` | extract | 彩色判定：最大通道差 |
| `extract.ink_min_delta` | extract | 候选像素相对背景的最少亮度差 |
| `extract.kmeans_k` / `kmeans_iters` | extract | 颜色聚类参数 |
| `extract.merge_center_dist` | extract | 代表色合并距离 |
| `extract.close_dist` | extract | 像素归属代表色的距离上限 |
| `extract.min_pixels` | extract | 一个系列的最少像素 |
| `extract.dark_thresh` | extract | 深色曲线亮度阈值 |
| `extract.grid_gray_tol` / `grid_min_frac` | extract | 网格色容差 / 判网格的最小占比 |
| `extract.sample_stride` | extract | 采样列步长 |
| `extract.max_series` | extract | 彩色系列上限 |
| `fit.degree_max` | fit | 多项式最高阶 |
| `fit.min_points` | fit | 拟合最少点 |
| `fit.min_rel_improve_frac` | fit | 升一阶所需的最小相对 RMSE 改善；低于此不升阶 |
| `fit.rmse_warn_frac` | fit | RMSE 超过数据 y 跨度该比例时告警 |
| `render.width_px` / `height_px` / `padding_frac` | render | SVG 画布与留白 |
| `pdf.frame_min_w_frac` / `frame_min_h_frac` | pdfir | 框候选的最小宽/高（占页宽/页高比例） |
| `pdf.frame_margin_pt` | pdfir | 曲线点距框边的内缩量（避免把框线算进曲线） |
| `pdf.tick_max_len_pt` | pdfir | 刻度短线最大长度（pt） |
| `pdf.tick_attach_pt` | pdfir | 线段视为「贴着框边」的距离上限（pt） |
| `pdf.tick_merge_pt` | pdfir | 相邻刻度合并距离（pt） |
| `pdf.max_ticks` | pdfir | 单轴刻度上限，超出视为误检 |
| `pdf.label_x_tol_pt` / `label_y_tol_pt` | pdfir | 刻度数字与刻度线的对位容差（pt） |
| `pdf.tick_label_max_offset_pt` | pdfir | 刻度数字离框边的最大距离（超出不算刻度标签） |
| `pdf.title_gap_pt` | pdfir | 标题在框上方的最小间距（pt） |
| `pdf.sample_stride_pt` | pdfir | PDF 曲线按列采样步长（pt） |
| `pdf.min_points_per_curve` / `min_cols_per_curve` | pdfir | 一条曲线的最少点数/采样列数 |
| `pdf.grid_gray_tol` / `grid_gray_min` | pdfir | 浅灰网格线的通道差容差 / 亮度下限 |
| `ledger.path` / `ledger.phash_max_dist` | ledger | 账本路径 / 近似命中汉明距离上限 |
| `cli.default_out_dir` | cli | 缺省输出目录 |

## 9. 纪律

- 代码不写死任何可调数值，只从 config 读；注释只写「语义见 INTERFACE.md §X」。
- 验收脚本断机制（键在、类型对、文件产、计数对、误差在范围内），阈值放 `tests/test_config.json`，不钉在脚本里。
- 改了行为先改本契约，再改实现。

## 10. 两层结构（层1 几何 / 层2 数据）

### 10.1 层 1：几何 IR（`chart2data/ir@1`）

目标：只回答「图上有什么图形、在哪」，**不解释数据语义**（不知道哪条线是"销售额"，也不把像素换算成数据值）。

```json
{
  "schema": "chart2data/ir@1",
  "source": {"type": "raster|pdf", "path": "...", "sha256": "...",
             "width": 0, "height": 0, "backend": "raster-v1|pdf-plumber-v1",
             "page": 1},
  "canvas": {"width": 0, "height": 0},
  "frame": {"left": 0, "top": 0, "right": 0, "bottom": 0},
  "objects": [
    {"id": "frame", "kind": "frame", "role": "plot_frame",
     "geometry": {"rect": [l, t, r, b]}, "style": {"color": null, "width_px": 1.0}},
    {"id": "tick_x_0", "kind": "tick", "role": "tick", "axis": "x",
     "geometry": {"pixel": 0.0}, "style": {"color": null, "width_px": 1.0}},
    {"id": "series_c0", "kind": "curve", "role": "data", "series": "c0",
     "geometry": {"points_px": [[x, y], ...]},
     "style": {"color": [r, g, b], "width_px": 2.0}}
  ],
  "labels": [],
  "notes": []
}
```

- `objects[].kind`：`frame` / `tick` / `curve`（后续 PDF 前端可加 `text`、`gridline`、`legend`、`marker`）。
- `labels`：文本层（角色为 title/xlabel/ylabel/tick/legend 的文本与位置）；位图后端为空，PDF 后端可填。
- `source.backend` 标识前端：`raster-v1`（位图）/ `pdf-plumber-v1`（PDF）；PDF 的 `source.page` 是页号。
- 干净 SVG 由 IR 直接重绘（`clean.svg`，像素坐标），不依赖层 2 结果。

### 10.2 层 2：数据（消费 IR）

`semantic.build_result(ir, series_px, calib, cfg, units)`：用 tick 对象 + 标定文件建立坐标映射，把 curve 对象的像素点换算成数据坐标，做采样与拟合，产出 `result.json`（§7）。层 2 **不读原图**，只读 IR；换前端（PDF）时层 2 不用改。

### 10.3 运行目录与 manifest（过程可查）

`extract` 的 `OUT_DIR`：

| 文件 | 层 | 内容 |
|---|---|---|
| `01_input.json` | — | 输入路径、sha256、字节数、宽高、mtime |
| `02_frame.json` | 1 | 框检测结果 |
| `03_ticks.json` | 1 | 检出刻度位置 `{x:[..], y:[..]}` |
| `04_ir.json` | 1 | 几何 IR（§10.1） |
| `clean.svg` | 1 | 由 IR 重绘的干净矢量图（像素坐标） |
| `05_calibration.json` | 2 | 标定（像素↔值、mode） |
| `06_series.json` | 2 | 系列清单（名、色、点数） |
| `07_fit.json` | 2 | 每条系列的拟合结果 |
| `result.json` | 2 | 主结果（§7） |
| `table.csv` | 2 | 长表：`series,x,y,y_min,y_max` |
| `table_wide.csv` | 2 | 宽表：`x,c0,c1,...`；仅当各系列 x 数组一致时生成 |
| `curve.svg` | 2 | 按数据坐标重绘的图（含刻度值、图例、方程） |
| `overlay.png` | 2 | 原图 + 框 + 采样点，供人眼校验 |
| `report.md` | 2 | 人读笔记：层、标定、系列、方程、表格、阶段清单、警告 |
| `manifest.json` | — | 阶段清单与每个文件的 sha256（§10.4） |

`ir` 命令只写 `01_input.json`、`02_frame.json`、`03_ticks.json`、`04_ir.json`、`clean.svg`、`manifest.json`（`command`=`ir`）。

### 10.4 manifest schema（`chart2data/manifest@1`）

```json
{
  "schema": "chart2data/manifest@1",
  "command": "extract|ir",
  "created": "...",
  "status": "ok",
  "config_sha256": "...",
  "stages": [
    {"name": "input", "files": [{"path": "01_input.json", "sha256": "...", "bytes": 0}],
     "warnings": []}
  ],
  "warnings": ["..."]
}
```

- 阶段顺序：`input` → `frame` → `ticks` → `ir` → `calibration` → `series` → `fit` → `render` → `result`。
- 每个文件都在 manifest 里有 sha256；审计时可按 manifest 复核「这一步用了什么、产出了什么」。
- `config_sha256` 是本次生效配置的哈希（能确认结论是拿哪套参数跑出来的）。

### 10.5 PDF 前端（层 1 另一种 `source.backend`）

输入 `IMAGE` 是 `.pdf` 时，`extract` / `ir` / `skeleton` 走 PDF 前端（`pdfir.build_ir_pdf`），层 2 不变。

- **依赖**：Python 包 `pdfplumber`（仅 PDF 输入需要）。缺少时命令失败，退出码 3，提示安装方式。
- **取的是矢量层与文本层**，不栅格化、不做 OCR：曲线来自页面描边路径（`page.curves` / `page.lines`），刻度值来自文本层字符位置。
- **框**：优先独立 `rect`；否则用两条长横线 + 两条长竖线围出的矩形（四边都要满足 `pdf.frame_min_*`）。检不出 → 退出码 2（同位图）。
- **刻度**：贴着框边（`pdf.tick_attach_pt` 内）且长度不超过 `pdf.tick_max_len_pt` 的短线段；竖短线贴底边 = x 刻度，横短线贴左边 = y 刻度。
- **标签**（`labels[]`，仅 PDF 有）：
  - 数字词且贴着刻度 → `role=tick`，并带 `axis`、`pixel`、`value`（`skeleton` 用它自动填标定）；
  - 框上方 → `title`；框下方 → `xlabel`；框左侧 → `ylabel`；框内 → `legend`；其余 `other`。
- **曲线分组**：描边颜色（`stroking_color` 转 0–255）相同的元素合成一条系列；每列（`pdf.sample_stride_pt`）取 y 中位数与上下界。系列命名 `c{i}`，按颜色字典序排序（确定性）。**同色多条曲线会并成一条**（本版限制，见 IR `notes`）。
- **坐标空间**：与位图一致，原点左上、y 向下；`source.width/height` 为页面尺寸（pt）。因此层 2 的标定/采样/拟合零改动。
- **失败语义**：PDF 打不开 / 页号越界 / 缺 pdfplumber → 退出码 3；检不出框 → 退出码 2；标定非法 → 4；内部错误 → 5。
- **辅助产物**：`overlay.png` 需要位图，PDF 输入时用 `page.to_image` 按 72dpi 栅格化一页；栅格化失败不中断主流程，只把 `overlay.png` 跳过并在 `warnings` 里说明；`--remember` 同理跳过。
- **`ledger-find`** 仍只收位图（指纹需要位图）；PDF 先去 `extract` 或另存截图再查。

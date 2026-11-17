# dsh-image-read 契约（INTERFACE）

> 可调值（python / chart2dataRoot / workDir / timeoutMs / chart.previewPoints / chart.minR2）全部在 `img.config.json`；本文不抄值。

## 1. 挂载与接入

- 包名 `dsh-image-read`；bundle 入口 `./cordis.patch.yml`；宿主侧入口 `index.js`。
- 依赖服务：`tools`（`inject: ['tools']`）；没有该服务的 profile 静默不激活。
- 安装：`dsh plugin --profile <p> add link:<绝对路径>`；开发期用 `link:`（改源码即生效）。
- Python 依赖：`numpy` / `Pillow` / `opencv-python`（见 `requirements.txt`）；`chart_read` 走仓库自带的 `vendor/chart2data`，其 PDF 输入另需 `pdfplumber`。

## 2. 配置契约

| 键 | 类型 | 谁读 | 语义 |
|---|---|---|---|
| `python` | string | `lib/bridge.js` | 运行 `bridge/main.py` 的解释器绝对路径 |
| `chart2dataRoot` | string | `bridge/main.py` | chart2data 包目录；可写相对路径，按 `img.config.json` 所在目录解析；其父目录进 PYTHONPATH |
| `workDir` | string | `bridge/main.py` | 工件根目录；不存在则创建 |
| `timeoutMs` | int | `lib/bridge.js` / `bridge/main.py` | 单次调用上限（宿主进程与 Python 子进程同值） |
| `chart.previewPoints` | int | `bridge/main.py` | 每条曲线内联预览点上限 |
| `chart.minR2` | float | 调用方 / 验收 | 拟合可信下限；工具只回报，不拦截 |
| `slide.threshold` | float | `bridge/main.py` | 滑块匹配分值的可信下限；只决定 `trusted`，不拦截 |
| `slide.fineRadius` | int | `bridge/main.py` | 粗匹配峰附近的精匹配半径（px）；0 = 关闭精匹配 |
| `rotate.features` | int | `bridge/main.py` | ORB 特征数上限 |
| `rotate.maxMatches` | int | `bridge/main.py` | 参与仿射估计的最大匹配数 |
| `rotate.minInliers` | int | `bridge/main.py` | 可信所需最小内点数 |
| `rotate.minInlierRatio` | float | `bridge/main.py` | 可信所需最小内点占比 |
| `rotate.scaleMin` / `scaleMax` | float | `bridge/main.py` | 可信的尺度范围（旋转不应缩放） |
| `rotate.coarseStep` | int | `bridge/main.py` | 无参考图投影法的角度步长 |
| `curve.minPixels` | int | `bridge/main.py` | 判为「有曲线」的最小暗像素数 |
| `curve.maxPoints` | int | `bridge/main.py` | 返回点列的上限（均匀抽样，保留首尾） |

## 3. 工具契约

### 3.1 `chart_read`

参数（`additionalProperties:false`）：

| 键 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `image` | string | 是 | 输入图绝对路径（png / jpg） |
| `calib` | string | 否 | chart2data 标定 JSON 绝对路径；缺省=像素坐标模式 |
| `out` | string | 否 | 工件目录绝对路径；缺省=`workDir` 下唯一目录 |
| `include_points` | boolean | 否 | true 时内联完整 x/y（调试用；默认 false） |

返回（单行 JSON 字符串）：

```json
{"ok":true,"schema":"chart2data/result@1","image":{"path":"","sha256":"","width":0,"height":0},
 "frame":{"left":0,"top":0,"right":0,"bottom":0},
 "calibration":{"x":{},"y":{}},
 "series":[{"name":"c0","color":[0,0,0],"n_points":0,
            "fit":{"model":"poly2","coeffs":[],"rmse":0,"r2":0,"equation":""},
            "points_preview":[[0,0]]}],
 "warnings":[""],"artifacts":{"result_json":"","table_csv":""},"elapsed_ms":0}
```

- `points_preview` 长度 ≤ `chart.previewPoints`；`include_points=true` 时才出现 `x` / `y`。
- `fit` 可能为 `null`（单值函数不成立时），调用方必须判空。
- `artifacts` 只列实际存在的文件，键名固定：`result_json` `table_csv` `table_wide_csv` `curve_svg` `clean_svg` `overlay_png` `report_md` `manifest_json`。

错误码：

| 码 | 触发 |
|---|---|
| `E_INPUT` | 图片 / 标定路径不存在或不可读 |
| `E_DEP` | `chart2dataRoot` 不存在或不是包目录 |
| `E_CHART2DATA` | chart2data 子进程非零退出（附 `rc` + `stderr` 尾部） |
| `E_OUTPUT` | 子进程成功但缺 `result.json` |
| `E_TIMEOUT` | 超过 `timeoutMs` |
| `E_BRIDGE` | 桥未返回可解析 JSON |
| `E_INTERNAL` | 桥内未捕获异常 |

失败语义：任何失败都返回 `ok:false` + `error`，工具不抛异常，宿主进程退出码恒 0。

### 3.2 `captcha_slide`

参数（`additionalProperties:false`）：

| 键 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `bg` | string | 是 | 背景图绝对路径（含缺口的整图） |
| `slider` | string | 是 | 拼图块绝对路径（带 alpha 的 PNG 最佳） |
| `threshold` | number | 否 | 覆盖 `slide.threshold` |
| `out` | string | 否 | 工件目录绝对路径 |

返回（单行 JSON 字符串）：

```json
{"ok":true,"x":0,"y":0,"score":0.0,"threshold":0.0,"trusted":false,
 "slider_w":0,"slider_h":0,"bg":{"width":0,"height":0},
 "artifacts":{"overlay_png":""},"elapsed_ms":0}
```

- `x` / `y` 是缺口左上角（背景图坐标系），不是滑块起点。
- `trusted=false` 时不要据此拖动；调用方自行决定交人或重试。
- `artifacts.overlay.png` 画出匹配框，供人工复核。

错误码：

| 码 | 触发 |
|---|---|
| `E_INPUT` | `bg` / `slider` 不存在或不可读 |
| `E_SLIDE` | 拼图块 alpha 边缘为空，或背景图小于模板 |
| `E_INTERNAL` | 桥内未捕获异常 |

### 3.3 `captcha_rotate`

参数（`additionalProperties:false`）：

| 键 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `image` | string | 是 | 待测图片绝对路径 |
| `reference` | string | 否 | 竖直参考图绝对路径；有它才走可信路径 |
| `out` | string | 否 | 工件目录绝对路径 |

返回：

```json
{"angle":0.0,"correction":0.0,"trusted":false,"method":"reference_orb",
 "score":0.0,"inliers":0,"matches":0,"scale":1.0,
 "artifacts":{"overlay_png":"","aligned_png":""},"elapsed_ms":0}
```

- `angle` ∈ (-180,180]，顺时针为正；`correction = -angle`。
- 有 `reference`：ORB + `estimateAffinePartial2D`；`trusted` 同时看 `rotate.minInliers` / `minInlierRatio` / 尺度范围。
- 无 `reference`：投影法，`trusted` 恒 false 且带 `warning`（90° 歧义）。
- `artifacts.aligned.png` 是按 `correction` 转正后的图，供人工复核。

错误码：

| 码 | 触发 |
|---|---|
| `E_INPUT` | `image` / `reference` 不存在或不可读 |
| `E_ROTATE` | ORB 匹配点不足或仿射估计失败 |
| `E_INTERNAL` | 桥内未捕获异常 |

### 3.4 `captcha_curve`

参数（`additionalProperties:false`）：

| 键 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `image` | string | 是 | 输入图绝对路径 |
| `out` | string | 否 | 工件目录绝对路径 |

返回：

```json
{"ok":true,"points":[[0,0]],"n_points":0,"length_px":0.0,
 "endpoints":[[0,0],[0,0]],"bbox":[0,0,0,0],"method":"column_centerline",
 "artifacts":{"overlay_png":""},"elapsed_ms":0}
```

- `points` 从左到右有序；每列取暗像素游程的中心，按最近邻保证连续。
- 只适合单值曲线（每列一条、无自交）；多曲线/闭环会只取到一条，需调用方自行切图。
- 只返回几何，不生成拖动轨迹、不提交。

错误码：

| 码 | 触发 |
|---|---|
| `E_INPUT` | `image` 不存在或不可读 |
| `E_CURVE` | 暗像素少于 `curve.minPixels`，或有效列不足 2 |
| `E_INTERNAL` | 桥内未捕获异常 |

### 3.5 `img_ops`

参数（`additionalProperties:false`）：

| 键 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `image` | string | 是 | 输入图绝对路径 |
| `ops` | array | 是 | 算子数组，按顺序执行 |
| `out` | string | 否 | 工件目录绝对路径 |

算子：

| `op` | 参数 | 结果 |
|---|---|---|
| `rotate` | `angle`（默认 90） | 90/180/270 无裁剪；其他角度扩展画布 |
| `crop` | `x`,`y`,`w`,`h` | 越界自动裁到边界，非法尺寸 `E_OP` |
| `resize` | `width`,`height` | 强制尺寸 |
| `gray` | — | 转 1 通道 |
| `threshold` | `value`（默认 127） | 二值化，1 通道 |
| `invert` | — | 255 - 像素 |
| `blur` | `ksize`（默认 5，自动奇数） | 高斯模糊 |
| `edges` | `low`,`high` | Canny，1 通道 |
| `contours` | `minArea`（默认 10） | 返回 `count` + `largest_bbox` |

返回：

```json
{"ok":true,"steps":[{"op":"gray","ok":true,"width":0,"height":0,"channels":0}],
 "output":{"path":"","width":0,"height":0,"channels":0},
 "artifacts":{"output_png":""},"elapsed_ms":0}
```

错误码：

| 码 | 触发 |
|---|---|
| `E_INPUT` | `image` 不存在或不可读 |
| `E_OP` | `ops` 为空、未知 op、参数非法 |
| `E_INTERNAL` | 桥内未捕获异常 |

## 4. 工件目录契约

- 每次调用一个目录：`<workDir>/<op>-<unix秒>-<6hex>/`；只增不改，同名不复用。
- 调用方用 `artifacts.*` 的绝对路径做 PTC 链式处理（例如把 `overlay.png` 再交给别的工具看）。

## 5. 扩展点

新增一个工具 = 三处，不改 `index.js`：

1. `bridge/main.py`：加一个 op 函数（返回 dict），登记进 `OPS`；
2. `lib/bridge.js`：在 `toolDefinitions()` 加定义（`name` / `description` / `parameters` / `op`）；
3. 本文：加 §3.x 一节并更新 §6。

## 6. 验证记录

| 日期 | 步骤 | 命令 | 结果 |
|---|---|---|---|
| 2026-11-17 | S1 | `node acceptance/selftest.mjs` | PASS（证据：`/home/chenty/Reservoir/tasks/runs/dsh-image-read/evidence/verify.md`） |
| 2026-11-17 | S2 | `node acceptance/selftest.mjs` | PASS；合成夹具误差 1px；真实样本 overlay 对齐（同上证据文件） |
| 2026-11-17 | S3 | `node acceptance/selftest.mjs` | PASS；cat 集 7 个角度误差 ≤5°；无参考 trusted=false（同上证据文件） |
| 2026-11-17 | S4 | `node acceptance/selftest.mjs` | PASS；合成曲线端点误差 ≤2.3px、长度差 2.8%（同上证据文件） |
| 2026-11-17 | S5 | `node acceptance/selftest.mjs` | PASS；4 步链式算子 200x100/1ch；crop/contours/E_OP/E_INPUT（同上证据文件） |

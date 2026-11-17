# dsh-image-read

DeepSeek Harness（DSH）插件：把**规则场景**的图片读取做成确定性工具，供 PTC 会话连续调用。

只做几何 / 像素层面的确定性计算：图表曲线拟合、滑块缺口定位、旋转角估计、曲线路径提取、链式图片算子。**不做通用视觉理解，不接 VLM。**

## 工具

| 工具 | 输入 | 返回 |
|---|---|---|
| `chart_read` | 图表截图 + 可选标定 | 每条曲线的方程 / R² / 预览点，以及数据表 / SVG / overlay 工件 |
| `captcha_slide` | 背景图 + 拼图块 | 缺口左上角 `x/y`、`score`、`trusted`、overlay |
| `captcha_rotate` | 待测图 + 可选参考图 | 旋转角 `angle`（顺时针，(-180,180]）、`correction`、`trusted` |
| `captcha_curve` | 含主曲线的图 | 有序点列 `points`、`endpoints`、`length_px`、bbox、overlay |
| `img_ops` | 图 + 算子数组 | 每步尺寸 + 最终 PNG 工件 |

完整参数 / 返回 / 错误码见 [`INTERFACE.md`](INTERFACE.md)。

## 环境

- Node.js >= 22.13（DSH 宿主）
- Python 3，已装 `numpy` / `Pillow` / `opencv-python`
- `chart_read` 额外需要 [chart2data](https://github.com/)（可选，不用图表就不装）

## 安装

开发期用 `link:` 装进 profile：

```sh
dsh plugin --profile web add link:/path/to/dsh-image-read
```

重启一次 `dsh web`（或进入下一回合）后，五个工具进入 PTC 的 `tools`。

## 用法

```js
// 图表：曲线 → 方程 / 数据点
const chart = await tools.chart_read({ image: '/abs/chart.png' })

// 滑块
const slide = await tools.captcha_slide({ bg: '/abs/bg.png', slider: '/abs/piece.png' })

// 旋转（有参考图时可信）
const rot = await tools.captcha_rotate({ image: '/abs/rotated.png', reference: '/abs/upright.png' })

// 曲线
const curve = await tools.captcha_curve({ image: '/abs/curve.png' })

// 链式图片处理
const ops = await tools.img_ops({
  image: '/abs/in.png',
  ops: [{ op: 'rotate', angle: 90 }, { op: 'gray' }, { op: 'resize', width: 640, height: 480 }],
})
```

返回均为单行 JSON 字符串；`ok:false` 时看 `error.code`（`E_INPUT` / `E_DEP` / `E_SLIDE` / `E_ROTATE` / `E_CURVE` / `E_OP` 等）。

## 配置

所有可调值在 [`img.config.json`](img.config.json)：`python` 解释器、`chart2dataRoot`（改成你的 chart2data 路径）、`workDir`、各工具阈值。

## 自检

```sh
node acceptance/selftest.mjs
# 图表用例需要 chart2data + 一张图表图：
CHART_FIXTURE=/path/to/chart.png node acceptance/selftest.mjs
```

夹具全部是**合成**的，可用 `python3 acceptance/make_fixtures.py` 重新生成。

## 限制

- 只针对规律场景；照片 / 不规则图不适用。
- `captcha_rotate` 无参考图时有 90° 歧义，`trusted` 恒为 `false`。
- `captcha_curve` 假设每列单值、无自交；多曲线需先切图。
- `captcha_slide` 的 `trusted` 只是分数阈值，低分不要直接拖。

## 目录

```
index.js            宿主侧工具注册
lib/bridge.js       Node → Python 桥
bridge/main.py      算法实现
img.config.json     可调值
INTERFACE.md        契约
acceptance/         selftest + 合成夹具生成器
```

## License

MIT

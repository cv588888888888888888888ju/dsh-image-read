import assert from 'node:assert'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import * as plugin from '../index.js'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const registered = new Map()
const ctx = {
  tools: { register: (definition) => { registered.set(definition.name, definition); return () => registered.delete(definition.name) } },
  logger: { info() {} },
}
const dispose = plugin.apply(ctx, {})

// chart_read 用仓库自带的图表夹具（三线图）；CHART_FIXTURE 可换成自己的图。
const chartFixture = process.env.CHART_FIXTURE || path.join(HERE, 'fixtures', 'chart', 'sample_plot.png')
if (fs.existsSync(chartFixture)) {
  assert.ok(registered.has('chart_read'), 'chart_read 未注册')
  const tool = registered.get('chart_read')
  const ok = JSON.parse(await tool.execute({ image: chartFixture }))
  assert.equal(ok.ok, true, JSON.stringify(ok))
  assert.ok(ok.series.length >= 2, 'series=' + ok.series.length)
  for (const series of ok.series) assert.ok(series.fit.r2 >= 0.99)
  assert.ok(ok.series[0].points_preview.length <= 40)
  const missing = JSON.parse(await tool.execute({ image: '/tmp/definitely-not-here.png' }))
  assert.equal(missing.ok, false)
  assert.equal(missing.error.code, 'E_INPUT')
} else {
  console.log('SKIP chart_read (set CHART_FIXTURE=/path/to/chart.png)')
}

assert.ok(registered.has('captcha_slide'), 'captcha_slide 未注册')
const slideTool = registered.get('captcha_slide')
const slideDir = path.join(HERE, 'fixtures', 'slide')
const slideTruth = JSON.parse(fs.readFileSync(path.join(slideDir, 'synthetic_truth.json'), 'utf8'))
const synthetic = JSON.parse(await slideTool.execute({ bg: path.join(slideDir, 'synthetic_bg.png'), slider: path.join(slideDir, 'synthetic_slider.png') }))
assert.equal(synthetic.ok, true, JSON.stringify(synthetic))
assert.ok(Math.abs(synthetic.x - slideTruth.x0) <= 2, 'synthetic x=' + synthetic.x + ' truth=' + slideTruth.x0)
assert.ok(Math.abs(synthetic.y - slideTruth.y0) <= 2, 'synthetic y=' + synthetic.y + ' truth=' + slideTruth.y0)
assert.ok(synthetic.artifacts.overlay_png)

if (fs.existsSync(path.join(slideDir, 'real1_bg.png'))) {
  const real = JSON.parse(await slideTool.execute({ bg: path.join(slideDir, 'real1_bg.png'), slider: path.join(slideDir, 'real1_slider.png') }))
  assert.equal(real.ok, true, JSON.stringify(real))
  assert.ok(real.x > 0 && real.x < real.bg.width)
  assert.ok(real.score > 0)
}

const missingSlide = JSON.parse(await slideTool.execute({ bg: '/tmp/definitely-not-here.png', slider: path.join(slideDir, 'synthetic_slider.png') }))
assert.equal(missingSlide.ok, false)
assert.equal(missingSlide.error.code, 'E_INPUT')

assert.ok(registered.has('captcha_rotate'), 'captcha_rotate 未注册')
const rotTool = registered.get('captcha_rotate')
const rotDir = path.join(HERE, 'fixtures', 'rotate')
const rotCases = [[45, 'synthetic_45.png'], [90, 'synthetic_90.png'], [135, 'synthetic_135.png'], [180, 'synthetic_180.png'], [-135, 'synthetic_225.png'], [-90, 'synthetic_270.png'], [-45, 'synthetic_315.png']]
for (const [truth, file] of rotCases) {
  const res = JSON.parse(await rotTool.execute({ image: path.join(rotDir, file), reference: path.join(rotDir, 'synthetic_ref.png') }))
  assert.equal(res.ok, true, JSON.stringify(res))
  const diff = Math.abs(((res.angle - truth + 540) % 360) - 180)
  assert.ok(diff <= 5, file + ': angle=' + res.angle + ' truth=' + truth)
  assert.equal(res.trusted, true, file + ' trusted')
}
const noRefRot = JSON.parse(await rotTool.execute({ image: path.join(rotDir, 'synthetic_45.png') }))
assert.equal(noRefRot.ok, true, JSON.stringify(noRefRot))
assert.equal(noRefRot.trusted, false)
const missingRot = JSON.parse(await rotTool.execute({ image: '/tmp/definitely-not-here.png' }))
assert.equal(missingRot.error.code, 'E_INPUT')

assert.ok(registered.has('captcha_curve'), 'captcha_curve 未注册')
const curveTool = registered.get('captcha_curve')
const curveDir = path.join(HERE, 'fixtures', 'curve')
const curveTruth = JSON.parse(fs.readFileSync(path.join(curveDir, 'synthetic_truth.json'), 'utf8'))
const curve = JSON.parse(await curveTool.execute({ image: path.join(curveDir, 'synthetic_curve.png') }))
assert.equal(curve.ok, true, JSON.stringify(curve))
assert.ok(curve.n_points >= 20, 'n_points=' + curve.n_points)
const d0 = Math.hypot(curve.endpoints[0][0] - curveTruth.endpoints[0][0], curve.endpoints[0][1] - curveTruth.endpoints[0][1])
const d1 = Math.hypot(curve.endpoints[1][0] - curveTruth.endpoints[1][0], curve.endpoints[1][1] - curveTruth.endpoints[1][1])
assert.ok(d0 <= 5, 'start dist=' + d0)
assert.ok(d1 <= 5, 'end dist=' + d1)
assert.ok(Math.abs(curve.length_px - curveTruth.length_px) / curveTruth.length_px <= 0.05, 'length=' + curve.length_px)
const blankCurve = JSON.parse(await curveTool.execute({ image: path.join(curveDir, 'blank.png') }))
assert.equal(blankCurve.ok, false)
assert.equal(blankCurve.error.code, 'E_CURVE')
const missingCurve = JSON.parse(await curveTool.execute({ image: '/tmp/definitely-not-here.png' }))
assert.equal(missingCurve.error.code, 'E_INPUT')

assert.ok(registered.has('img_ops'), 'img_ops 未注册')
const opsTool = registered.get('img_ops')
const chain = JSON.parse(await opsTool.execute({ image: path.join(curveDir, 'synthetic_curve.png'), ops: [{ op: 'rotate', angle: 90 }, { op: 'gray' }, { op: 'resize', width: 200, height: 100 }, { op: 'invert' }] }))
assert.equal(chain.ok, true, JSON.stringify(chain))
assert.equal(chain.steps.length, 4)
assert.equal(chain.output.width, 200)
assert.equal(chain.output.height, 100)
assert.equal(chain.output.channels, 1)
const cropped = JSON.parse(await opsTool.execute({ image: path.join(curveDir, 'synthetic_curve.png'), ops: [{ op: 'crop', x: 10, y: 10, w: 100, h: 80 }] }))
assert.equal(cropped.output.width, 100)
assert.equal(cropped.output.height, 80)
const contourStep = JSON.parse(await opsTool.execute({ image: path.join(curveDir, 'synthetic_curve.png'), ops: [{ op: 'contours', minArea: 100 }] }))
assert.ok(contourStep.steps[0].count >= 1, 'contours count=' + contourStep.steps[0].count)
const badOp = JSON.parse(await opsTool.execute({ image: path.join(curveDir, 'synthetic_curve.png'), ops: [{ op: 'nope' }] }))
assert.equal(badOp.error.code, 'E_OP')
const missingOps = JSON.parse(await opsTool.execute({ image: '/tmp/definitely-not-here.png', ops: [{ op: 'gray' }] }))
assert.equal(missingOps.error.code, 'E_INPUT')

dispose()
console.log('PASS')

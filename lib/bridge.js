/**
 * 宿主 ↔ Python 桥。参数 / 返回 / 错误码见 INTERFACE.md §3。
 * 值（python / chart2dataRoot / workDir / timeoutMs）只从 img.config.json 读。
 */
import fs from 'node:fs'
import path from 'node:path'
import { spawn } from 'node:child_process'

const FALLBACK = { timeoutMs: 120000 }

export function loadConfig(pluginDir, rawConfig = {}) {
  const configPath = typeof rawConfig.configPath === 'string' && rawConfig.configPath !== ''
    ? rawConfig.configPath
    : path.join(pluginDir, 'img.config.json')
  const file = JSON.parse(fs.readFileSync(configPath, 'utf8'))
  return {
    ...FALLBACK,
    ...file,
    configPath,
    pluginDir,
    bridgePath: path.join(pluginDir, 'bridge', 'main.py'),
  }
}

/** 工具定义表；新增工具见 INTERFACE.md §5。 */
export function toolDefinitions() {
  return [
    {
      name: 'chart_read',
      op: 'chart_read',
      description:
        '读取图表截图：返回每条曲线的拟合方程 / R² / 数据点预览，以及数据表、重绘 SVG、overlay 的绝对路径。' +
        '输入须是「有完整矩形边框 + 刻度」的二维图；无框、柱状图、参数曲线（圆/闭环）不适用。' +
        '带标定文件时返回数据坐标，否则返回像素坐标并给 warning。',
      parameters: {
        type: 'object',
        properties: {
          image: { type: 'string', description: '输入图绝对路径（png / jpg）' },
          calib: { type: 'string', description: '可选：chart2data 标定 JSON 绝对路径；缺省=像素坐标模式' },
          out: { type: 'string', description: '可选：工件目录绝对路径；缺省=workDir 下唯一目录' },
          include_points: { type: 'boolean', description: '可选：true 时内联完整 x/y（调试用，token 大；默认 false）' },
        },
        required: ['image'],
        additionalProperties: false,
      },
    },
    {
      name: 'captcha_slide',
      op: 'captcha_slide',
      description:
        '滑块验证码缺口定位（背景图 + 拼图块）：返回缺口左上角 x / y、匹配分值 score 与 trusted。' +
        '只解几何，不模拟轨迹、不提交。score 低于阈值时 trusted=false，不要据此拖动。',
      parameters: {
        type: 'object',
        properties: {
          bg: { type: 'string', description: '背景图绝对路径（含缺口的整图）' },
          slider: { type: 'string', description: '拼图块绝对路径（带 alpha 的 PNG 最佳）' },
          threshold: { type: 'number', description: '可选：可信阈值，覆盖 img.config.json 的 slide.threshold' },
          out: { type: 'string', description: '可选：工件目录绝对路径' },
        },
        required: ['bg', 'slider'],
        additionalProperties: false,
      },
    },
    {
      name: 'captcha_rotate',
      op: 'captcha_rotate',
      description:
        '旋转验证码角度估计：给参考图时用 ORB 特征估计输入图相对参考图的旋转角；不给参考图时用投影法给低置信估计。' +
        '返回 angle（(-180,180]，顺时针为正）、correction 与 trusted。只估计，不拖动、不提交。',
      parameters: {
        type: 'object',
        properties: {
          image: { type: 'string', description: '待测图片绝对路径' },
          reference: { type: 'string', description: '可选：竖直参考图绝对路径；有它才走可信路径' },
          out: { type: 'string', description: '可选：工件目录绝对路径' },
        },
        required: ['image'],
        additionalProperties: false,
      },
    },
    {
      name: 'captcha_curve',
      op: 'captcha_curve',
      description:
        '曲线验证码路径提取：把图中主曲线变成有序点列（从左到右），返回 endpoints / length_px / bbox 与 overlay。' +
        '只提取几何，不生成拖动轨迹、不提交。适合单值曲线（每列一条）。',
      parameters: {
        type: 'object',
        properties: {
          image: { type: 'string', description: '输入图绝对路径' },
          out: { type: 'string', description: '可选：工件目录绝对路径' },
        },
        required: ['image'],
        additionalProperties: false,
      },
    },
    {
      name: 'img_ops',
      op: 'img_ops',
      description:
        '链式图片算子：rotate / crop / resize / gray / threshold / invert / blur / edges / contours，按顺序应用；' +
        '返回每步尺寸与最终 PNG 工件。只处理像素，不做语义识别。',
      parameters: {
        type: 'object',
        properties: {
          image: { type: 'string', description: '输入图绝对路径' },
          ops: {
            type: 'array',
            description: '算子数组，按顺序执行；每项含 op 与参数',
            items: { type: 'object', additionalProperties: true },
            minItems: 1,
          },
          out: { type: 'string', description: '可选：工件目录绝对路径' },
        },
        required: ['image', 'ops'],
        additionalProperties: false,
      },
    },
  ]
}

function errorJson(code, message) {
  return JSON.stringify({ ok: false, error: { code, message } })
}

/** 调 Python 桥：stdin 传参数 JSON，stdout 收结果 JSON。失败一律转结构化错误，不抛。 */
export function callBridge(op, args, config) {
  return new Promise((resolve) => {
    let settled = false
    const finish = (value) => { if (!settled) { settled = true; resolve(value) } }
    let child
    try {
      child = spawn(config.python, [config.bridgePath, op, '--config', config.configPath], {
        stdio: ['pipe', 'pipe', 'pipe'],
        env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
      })
    } catch (error) {
      finish(errorJson('E_BRIDGE', `无法启动 Python 桥：${error.message}`))
      return
    }
    let stdout = ''
    let stderr = ''
    const timer = setTimeout(() => {
      try { child.kill('SIGKILL') } catch { /* 已退出 */ }
      finish(errorJson('E_TIMEOUT', `超过 ${config.timeoutMs}ms`))
    }, Number(config.timeoutMs) || 120000)
    child.stdout.on('data', (chunk) => { stdout += chunk })
    child.stderr.on('data', (chunk) => { stderr += chunk })
    child.on('error', (error) => {
      clearTimeout(timer)
      finish(errorJson('E_BRIDGE', `Python 桥进程错误：${error.message}`))
    })
    child.on('close', (code) => {
      clearTimeout(timer)
      const text = stdout.trim()
      if (text === '') {
        finish(errorJson('E_BRIDGE', `桥无输出（rc=${code}）：${stderr.slice(-800)}`))
        return
      }
      try {
        JSON.parse(text)
        finish(text)
      } catch {
        finish(errorJson('E_BRIDGE', `桥输出不是 JSON（rc=${code}）：${text.slice(-800)}`))
      }
    })
    try {
      child.stdin.write(JSON.stringify(args))
      child.stdin.end()
    } catch (error) {
      finish(errorJson('E_BRIDGE', `写参数失败：${error.message}`))
    }
  })
}

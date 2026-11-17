/**
 * dsh-image-read —— 规则场景图片读取工具（宿主侧）。
 * 工具名 / 参数 / 返回 / 错误码：见 INTERFACE.md §3；可调值：见 img.config.json。
 */
import path from 'node:path'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import { loadConfig, callBridge, toolDefinitions } from './lib/bridge.js'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const LOAD_MARK = path.join(HERE, '.loaded.log')

export const name = 'dsh-image-read'
export const inject = ['tools']

export function apply(ctx, rawConfig = {}) {
  const config = loadConfig(HERE, rawConfig)
  const disposers = []
  for (const def of toolDefinitions(config)) {
    disposers.push(ctx.tools.register({
      name: def.name,
      description: def.description,
      parameters: def.parameters,
      output: { schema: { type: 'string' }, render: (_args, value) => [{ type: 'text', text: String(value) }] },
      async execute(args = {}) {
        return await callBridge(def.op, args, config)
      },
    }))
    ctx.logger?.info?.(`${name}: registered tool "${def.name}"`)
  }
  try {
    fs.appendFileSync(LOAD_MARK, `${new Date().toISOString()} pid=${process.pid} tools=${disposers.length}\n`)
  } catch { /* 装载证据写失败不影响工具 */ }
  return () => {
    for (const dispose of disposers.reverse()) {
      try { dispose() } catch { /* 卸载期错误不冒泡 */ }
    }
  }
}

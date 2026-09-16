import { apiFetch } from './client'
import { getClientUserId, _enterSSE, _leaveSSE } from './analysis'
import type { DrugStagesPayload, LLMConfig } from './types'

/**
 * 药物发现流水线的 API 层。
 *
 * 这里只有两个端点，但流式那条与 /api/llm/chat/stream 有两个实质差别，
 * 不是换个 URL 就能复用的：
 *
 *   1. 不传 messages，传 `query` + `stage_ids` —— 阶段化的 user message 由
 *      后端 `drug_stages.build_stage_message()` 组装，前端不拼提示词。
 *   2. 每次运行是**多次** LLM 循环（每个阶段一次），所以事件流里会出现多组
 *      message / tool_result，靠 `stage_id` 区分属于哪一段。
 */

export async function fetchDrugStages(): Promise<DrugStagesPayload> {
  return apiFetch<DrugStagesPayload>('/api/drug/stages')
}

export interface DrugPipelineRunOptions {
  query: string
  stageIds: string[]
  config: LLMConfig
  /** 可选：挂了数据集才有，不传则整个流水线在无数据上下文中运行。 */
  realPath?: string
  onEvent: (event: string, data: unknown) => void
  signal?: AbortSignal
}

export async function runDrugPipelineStreaming({
  query,
  stageIds,
  config,
  realPath = '',
  onEvent,
  signal,
}: DrugPipelineRunOptions): Promise<void> {
  // 与其它流式端点共用 HMR 保护：整页刷新会掐断一条可能跑十几分钟的流水线，
  // 而阶段结果只存在于这次响应里，断了就没了。
  _enterSSE()
  try {
    const response = await fetch('/api/drug/pipeline/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal,
      body: JSON.stringify({
        query,
        stage_ids: stageIds,
        api_key: config.apiKey,
        model: config.model,
        base_url: config.baseUrl,
        temperature: config.temperature,
        real_path: realPath,
        user_id: getClientUserId(),
      }),
    })

    if (!response.ok) {
      const body = await response.json().catch(() => ({}))
      throw new Error(body.error || `HTTP ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('No response body')

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      // 按空行切块。最后一段可能不完整，留回 buffer 等下一轮 ——
      // 直接 JSON.parse 会丢掉正好落在网络包边界的那个事件。
      const blocks = buffer.split('\n\n')
      buffer = blocks.pop() || ''

      for (const block of blocks) {
        const eventMatch = block.match(/^event: (.+)$/m)
        const dataMatch = block.match(/^data: (.+)$/m)
        if (!eventMatch || !dataMatch) continue
        try {
          onEvent(eventMatch[1], JSON.parse(dataMatch[1]))
        } catch {
          // 心跳是 SSE 注释（`: heartbeat`），没有 data 行，上面已跳过；
          // 真解析不了说明这一块坏了，跳过它比中断整条流水线好。
        }
      }
    }
  } finally {
    _leaveSSE()
  }
}

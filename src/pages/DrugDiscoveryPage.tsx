import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Pill } from 'lucide-react'
import DrugWorkbench from '../components/drug/DrugWorkbench'

/**
 * 药物发现工作台页面（/drug-discovery）。
 *
 * 壳层照 AnalysisPage 的 Shape B —— `h-screen flex flex-col overflow-hidden`，
 * 因为工作台内部靠自己滚动（消息流 + 工具结果两栏各自滚），
 * 整页滚动会把输入栏顶出视野。
 *
 * 与分析页的唯一壳层差异：**不需要数据集参数**。路由没有 `:tissue/:disease/:pmid`
 * 三段，返回目标也不是某个组织页 —— 因此用 `navigate(-1)` 回上一页，
 * 退不到就回主页。
 */
export default function DrugDiscoveryPage() {
  const navigate = useNavigate()

  const goBack = () => {
    // 直接输 URL 打开时 history 里没有上一页，navigate(-1) 会跳出站点。
    if (window.history.length > 1) navigate(-1)
    else navigate('/')
  }

  return (
    <div className="h-screen bg-brand-bg flex flex-col overflow-hidden">
      <div className="bg-surface border-b border-border-light shrink-0">
        <div className="max-w-full mx-auto px-4 py-1.5 flex items-center gap-2 min-w-0">
          <button
            onClick={goBack}
            className="flex items-center gap-1 text-sm text-text-secondary hover:text-brand transition-colors shrink-0"
          >
            <ArrowLeft className="w-4 h-4" /> Back
          </button>
          <div className="h-4 w-px bg-border-light shrink-0" />
          <Pill className="w-4 h-4 text-brand shrink-0" />
          <span className="text-sm font-semibold text-text-primary truncate">Drug Discovery</span>
          <span className="text-[11px] text-text-muted truncate hidden md:inline">
            临床前研究通路智能体 · 公开数据驱动，不做实验预测
          </span>
        </div>
      </div>

      <div className="flex-1 min-h-0 p-2">
        <DrugWorkbench />
      </div>
    </div>
  )
}

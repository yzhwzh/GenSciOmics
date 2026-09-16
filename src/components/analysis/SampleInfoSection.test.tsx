import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SampleInfoSection from './SampleInfoSection'
import type { SupplementaryItem } from '../../api/types'

const fetchSupplementaryTable = vi.fn()
vi.mock('../../api/analysis', () => ({
  fetchSupplementaryTable: (...args: unknown[]) => fetchSupplementaryTable(...args),
}))

/** 真实抓自 PMC8085501（IgAN）的清单，顺序刻意打乱：★ 的排在后面。 */
const ITEMS: SupplementaryItem[] = [
  { name: 'Table_3.xlsx', caption: 'DEGs in cell subtypes of glomerulus.', kind: 'table', is_sample_hint: false },
  { name: 'Table_1.xlsx', caption: 'Demographic and biochemical characteristics of patients with IgAN.', kind: 'table', is_sample_hint: true },
  { name: 'aba1972_SM.pdf', caption: 'Supplemental methods.', kind: 'file', is_sample_hint: false },
  { name: 'Table_8.xlsx', caption: 'Cell number of distinct clusters in kidney from each subject', kind: 'table', is_sample_hint: true },
]

beforeEach(() => {
  fetchSupplementaryTable.mockReset()
})

describe('SampleInfoSection — 清单', () => {
  it('把疑似样本表排到前面，且保持各自原有相对顺序', () => {
    render(<SampleInfoSection items={ITEMS} note="" pmcid="PMC8085501" />)
    const captions = screen.getAllByTitle(/^Table_|^aba/).map(el => el.getAttribute('title'))
    // Table_1 在源数组里排第 2、Table_8 排第 4；两个 ★ 项应整体前移且互不换位
    expect(captions.indexOf('Table_1.xlsx')).toBeLessThan(captions.indexOf('Table_8.xlsx'))
    expect(captions.indexOf('Table_8.xlsx')).toBeLessThan(captions.indexOf('Table_3.xlsx'))
  })

  it('一条都不隐藏 —— 打星只是提示，不是过滤', () => {
    render(<SampleInfoSection items={ITEMS} note="" pmcid="PMC8085501" />)
    for (const item of ITEMS) {
      expect(screen.getAllByTitle(item.name).length).toBeGreaterThan(0)
    }
  })

  it('只有 is_sample_hint 的项才带星', () => {
    render(<SampleInfoSection items={ITEMS} note="" pmcid="PMC8085501" />)
    expect(screen.getAllByLabelText('疑似样本信息表')).toHaveLength(2)
  })

  it('caption 为空时退回显示文件名（真实数据里有整篇 caption 全空的）', () => {
    render(<SampleInfoSection
      items={[{ name: 'mmc1.xlsx', caption: '', kind: 'table', is_sample_hint: false }]}
      note="" pmcid="PMC1" />)
    expect(screen.getByText('mmc1.xlsx')).toBeInTheDocument()
  })
})

describe('SampleInfoSection — 三种「没有」必须互不相同', () => {
  const textFor = (note: 'no-pmcid' | 'none' | 'error') => {
    const { unmount } = render(<SampleInfoSection items={[]} note={note} pmcid={undefined} />)
    const text = document.body.textContent ?? ''
    unmount()
    return text
  }

  it('no-pmcid 说的是「没检查过」，不是「没有」', () => {
    expect(textFor('no-pmcid')).toContain('无法检查')
  })

  it('none 才是「确实没有」', () => {
    expect(textFor('none')).toContain('没有补充材料附件')
  })

  it('error 要说明可重试', () => {
    expect(textFor('error')).toContain('重试')
  })

  it('三句话两两不同', () => {
    const a = textFor('no-pmcid'), b = textFor('none'), c = textFor('error')
    expect(new Set([a, b, c]).size).toBe(3)
  })
})

describe('SampleInfoSection — 按需展开', () => {
  it('展开前不碰网络（清单是免费的，内容才要下载）', () => {
    render(<SampleInfoSection items={ITEMS} note="" pmcid="PMC8085501" />)
    expect(fetchSupplementaryTable).not.toHaveBeenCalled()
  })

  it('点了才去取，取回后渲染表格', async () => {
    const user = userEvent.setup()
    fetchSupplementaryTable.mockResolvedValue({
      sheets: [{
        name: 'Sheet1',
        columns: ['Age', 'Gender'],
        rows: [[26, 'M'], [50, 'F']],
      }],
      truncated: false,
    })
    render(<SampleInfoSection items={ITEMS} note="" pmcid="PMC8085501" />)

    await user.click(screen.getAllByTitle('Table_1.xlsx')[0])

    expect(fetchSupplementaryTable).toHaveBeenCalledWith('PMC8085501', 'Table_1.xlsx')
    expect(await screen.findByText('Age')).toBeInTheDocument()
    expect(screen.getByText('26')).toBeInTheDocument()
  })

  it('加载中要写明代价，不能让用户以为卡死了', async () => {
    const user = userEvent.setup()
    fetchSupplementaryTable.mockReturnValue(new Promise(() => {})) // 永不 resolve
    render(<SampleInfoSection items={ITEMS} note="" pmcid="PMC8085501" />)

    await user.click(screen.getAllByTitle('Table_1.xlsx')[0])
    expect(screen.getByText(/正在下载该文献的补充材料压缩包/)).toBeInTheDocument()
  })

  it('再点一次同一个附件不会重复下载（已缓存在 state 里）', async () => {
    const user = userEvent.setup()
    fetchSupplementaryTable.mockResolvedValue({ sheets: [{ name: 'S', columns: ['a'], rows: [[1]] }], truncated: false })
    render(<SampleInfoSection items={ITEMS} note="" pmcid="PMC8085501" />)

    await user.click(screen.getAllByTitle('Table_1.xlsx')[0])
    await screen.findByText('a')
    await user.click(screen.getAllByTitle('Table_1.xlsx')[0])   // 收起
    await user.click(screen.getAllByTitle('Table_1.xlsx')[0])   // 再展开

    expect(fetchSupplementaryTable).toHaveBeenCalledTimes(1)
  })

  it('取失败只影响这一条，不炸掉整个区块', async () => {
    const user = userEvent.setup()
    fetchSupplementaryTable.mockRejectedValue(new Error('HTTP 429'))
    render(<SampleInfoSection items={ITEMS} note="" pmcid="PMC8085501" />)

    await user.click(screen.getAllByTitle('Table_1.xlsx')[0])

    expect(await screen.findByText(/429/)).toBeInTheDocument()
    // 其他条目仍在
    expect(screen.getAllByTitle('Table_3.xlsx').length).toBeGreaterThan(0)
  })

  it('非表格类附件（pdf）不给展开，避免下 37MB 来看一篇 PDF', async () => {
    const user = userEvent.setup()
    render(<SampleInfoSection items={ITEMS} note="" pmcid="PMC8085501" />)

    await user.click(screen.getAllByTitle('aba1972_SM.pdf')[0])

    expect(fetchSupplementaryTable).not.toHaveBeenCalled()
  })
})

describe('SupplementaryTable — 截断要如实说', () => {
  it('truncated 时给出提示而不是假装全部', async () => {
    const user = userEvent.setup()
    fetchSupplementaryTable.mockResolvedValue({
      sheets: [{ name: 'S', columns: ['id'], rows: [[1], [2]] }],
      truncated: true,
    })
    render(<SampleInfoSection items={ITEMS} note="" pmcid="PMC8085501" />)
    await user.click(screen.getAllByTitle('Table_1.xlsx')[0])

    await waitFor(() => expect(screen.getByText(/仅显示前/)).toBeInTheDocument())
  })
})

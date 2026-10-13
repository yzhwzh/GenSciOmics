import { describe, it, expect } from 'vitest'
import { summarizeDatasets } from './datasets'
import type { DatasetInfo } from './types'

/**
 * 首页 Hero 区那四个数字。它们此前与真实数据对不上，成因不是算错，而是**口径**：
 *
 *  - 文件条数被当成研究套数 —— Tabula Sapiens 一篇（PMID 35549404）被拆成 29 个
 *    单器官文件，于是「Datasets」把它数了 29 次。统计表按 PMID 计套数，首页却按
 *    文件计，两把尺子。（2026-10-13 实测：97 条记录 ↔ 64 个 PMID。）
 *  - `Health` 被当成一种疾病 —— disease 字段去重后含 'Health'，于是标着 Diseases
 *    的一栏里蹲着一个「健康」。29 种「疾病」里有 1 种是健康，真实为 28。
 *  - `4 Omics Types` 是写死的常量，实际只有 scRNA / BulkRNA / Protein 三类。
 *
 * 三条都是「数字看着合理、实则口径错」：跑起来不报错，只有对着数据核才发现。
 * 所以钉成单测，而不是靠下次有人肉眼比对。
 */
const ds = (over: Partial<DatasetInfo>): DatasetInfo => ({
  tissue: 'Lung',
  disease: 'COPD',
  pmid: '1',
  real_path: '/synthetic/path.h5ad',
  ...over,
})

describe('summarizeDatasets', () => {
  it('按 PMID 计套数：同一篇拆成多个文件只算一套', () => {
    const rows = [
      ds({ pmid: '35549404', tissue: 'Lung' }),
      ds({ pmid: '35549404', tissue: 'Heart' }),
      ds({ pmid: '35549404', tissue: 'Kidney' }),
      ds({ pmid: '99999999', tissue: 'Lung' }),
    ]

    expect(summarizeDatasets(rows).studies).toBe(2)
  })

  it('不把 Health 当成一种疾病', () => {
    const rows = [ds({ disease: 'Health' }), ds({ disease: 'COPD' }), ds({ disease: 'IPF' })]

    expect(summarizeDatasets(rows).diseases).toBe(2)
  })

  it('器官按 tissue 去重，且忽略大小写', () => {
    const rows = [ds({ tissue: 'Lung' }), ds({ tissue: 'lung' }), ds({ tissue: 'Heart' })]

    expect(summarizeDatasets(rows).organs).toBe(2)
  })

  it('组学种类从数据实算，而不是写死的 4', () => {
    const rows = [ds({ omics_type: 'scRNA' }), ds({ omics_type: 'BulkRNA' }), ds({ omics_type: 'scRNA' })]

    expect(summarizeDatasets(rows).omics).toBe(2)
  })

  it('空列表返回全 0 而不是抛异常', () => {
    expect(summarizeDatasets([])).toEqual({ organs: 0, diseases: 0, studies: 0, omics: 0 })
  })
})

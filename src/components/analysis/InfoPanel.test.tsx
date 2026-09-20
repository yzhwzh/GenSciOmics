import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import InfoPanel from './InfoPanel'
import type { AnalysisInfo } from '../../api/types'

// Why this file exists (BUG_LOG B35): AnalysisPage.test.tsx stubs InfoPanel to
// `() => null`, and no other suite renders it. So the abstract panel — the part
// of the B35 fix a user actually sees — had zero coverage. `abstractError` and
// the retry button could be deleted from the component and all tests would
// still pass.
//
// The three states must stay distinguishable. Collapsing "still fetching" or
// "fetch failed" into "Abstract not available" is a factual claim about the
// paper, and it is the bug that survived the first pass at this fix.

const stats = {
  cells: 243472, genes: 12000, patient_count: 3, sample_count: 5,
  celltype_count: 4, cell_type_names: [], sample_names: [], group_names: [],
  obs_columns: [], disease_count: 1, group_dist: '',
} as unknown as AnalysisInfo['stats']

const info = (over: Partial<AnalysisInfo> = {}): AnalysisInfo => ({
  pmid: '32832599',
  abstract: null,
  stats,
  ...over,
} as AnalysisInfo)

const noop = () => {}

describe('InfoPanel — abstract states', () => {
  it('spins while the abstract is still being fetched, and does not claim it is missing', () => {
    // abstract_ready is not true and no failure has been recorded → in flight.
    render(<InfoPanel info={info()} loading={false} onRetryAbstract={noop} />)

    expect(screen.getByText(/loading abstract/i)).toBeTruthy()
    expect(screen.queryByText(/abstract not available/i)).toBeNull()
  })

  it('spins even before the effect has run (state derived from data, not from a set flag)', () => {
    // The old implementation keyed the spinner off an `abstractLoading` flag set
    // inside the effect. On every cold load the panel commits one render where
    // that flag is still false — showing "Abstract not available" for a dataset
    // whose abstract is milliseconds away.
    render(<InfoPanel info={info({ abstract_ready: undefined })} loading={false} onRetryAbstract={noop} />)

    expect(screen.queryByText(/abstract not available/i)).toBeNull()
    expect(screen.getByText(/loading abstract/i)).toBeTruthy()
  })

  it('offers a retry when the fetch failed, rather than calling it a missing abstract', async () => {
    const onRetry = vi.fn()
    render(<InfoPanel info={info()} loading={false} abstractError onRetryAbstract={onRetry} />)

    expect(screen.queryByText(/abstract not available/i)).toBeNull()
    const retry = screen.getByRole('button', { name: /重试/ })
    await userEvent.click(retry)
    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('says "not available" only when the server has finalised the record', () => {
    // abstract_ready === true with no content is the server saying "this is all
    // there is" — the only case where the message is a fact.
    render(
      <InfoPanel
        info={info({ abstract: { title: '', abstract: '' } as never, abstract_ready: true })}
        loading={false}
        onRetryAbstract={noop}
      />,
    )

    expect(screen.getByText(/abstract not available/i)).toBeTruthy()
    expect(screen.queryByRole('button', { name: /重试/ })).toBeNull()
  })

  it('renders the abstract once it arrives', () => {
    render(
      <InfoPanel
        info={info({
          abstract: { title: 'A study', abstract: 'Body text.', journal: 'J', authors: 'X', year: '2020', doi: 'd' } as never,
          abstract_ready: true,
        })}
        loading={false}
        onRetryAbstract={noop}
      />,
    )

    expect(screen.getByText('A study')).toBeTruthy()
    expect(screen.getByText('Body text.')).toBeTruthy()
  })
})

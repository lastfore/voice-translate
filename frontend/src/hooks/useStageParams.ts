import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { StageParamSchemaResponse } from '@/types/pipeline'

export interface StageParamsFilter {
  stage: string
  vadOnly?: boolean
  sliceBatchOnly?: boolean
  keys?: string[]
}

export function stageParamsKey(filter: StageParamsFilter) {
  return ['stageParams', filter.stage, filter.vadOnly ?? false, filter.sliceBatchOnly ?? false, filter.keys?.join(',') ?? ''] as const
}

/**
 * Migration doc §5.2 caching policy: the schema comes from a static Python
 * dataclass table that only changes on process restart. `staleTime`/`gcTime`
 * Infinity means this only refetches on an explicit
 * `queryClient.invalidateQueries({ queryKey: ['stageParams'] })` call.
 */
export function useStageParams(filter: StageParamsFilter) {
  return useQuery({
    queryKey: stageParamsKey(filter),
    queryFn: () =>
      api.get<StageParamSchemaResponse>('/api/params/schema', {
        stage: filter.stage,
        vad_only: filter.vadOnly,
        slice_batch_only: filter.sliceBatchOnly,
        keys: filter.keys?.join(','),
      }),
    staleTime: Infinity,
    gcTime: Infinity,
  })
}

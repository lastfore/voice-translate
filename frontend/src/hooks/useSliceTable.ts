import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { SliceMode, SliceTableResponse } from '@/types/pipeline'

/** `GET /api/projects/{id}/slices?mode=` — migrated from webui.helpers.load_slice_table(). */
export function useSliceTable(projectId: string | null, mode: SliceMode) {
  return useQuery({
    queryKey: ['slices', projectId, mode],
    queryFn: () => api.get<SliceTableResponse>(`/api/projects/${projectId}/slices`, { mode }),
    enabled: !!projectId,
  })
}

import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { ConvertedSliceTableResponse, SliceMode } from '@/types/pipeline'

/** `GET /api/projects/{id}/converted-slices?mode=` — convert tab slice list preview. */
export function useConvertedSliceTable(projectId: string | null, mode: SliceMode) {
  return useQuery({
    queryKey: ['converted-slices', projectId, mode],
    queryFn: () => api.get<ConvertedSliceTableResponse>(`/api/projects/${projectId}/converted-slices`, { mode }),
    enabled: !!projectId,
  })
}

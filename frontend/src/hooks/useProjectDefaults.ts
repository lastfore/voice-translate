import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { ProjectDefaults } from '@/types/pipeline'

export const projectDefaultsKey = (projectId: string | null) => ['projectDefaults', projectId] as const

/**
 * Migration doc §6.2: `staleTime: 30_000` avoids a redundant refetch every
 * time the user flips back to a project they were just on. Cache
 * invalidation on project switch is `AppSidebar`'s job via
 * `queryClient.removeQueries({ queryKey: projectDefaultsKey(oldId) })` —
 * NOT this hook's `enabled`/`staleTime`.
 */
export function useProjectDefaults(projectId: string | null) {
  return useQuery({
    queryKey: projectDefaultsKey(projectId),
    queryFn: () => api.get<ProjectDefaults>(`/api/projects/${projectId}/defaults`),
    enabled: !!projectId,
    staleTime: 30_000,
  })
}

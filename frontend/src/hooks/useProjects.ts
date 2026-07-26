import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '@/lib/api'
import type { DeletePreviewRow, ProjectSummary } from '@/types/pipeline'

export const PROJECTS_QUERY_KEY = ['projects'] as const

export function useProjects() {
  return useQuery({
    queryKey: PROJECTS_QUERY_KEY,
    queryFn: () => api.get<ProjectSummary[]>('/api/projects'),
  })
}

export interface CreateProjectInput {
  projectId: string
  displayName?: string
  audio: File
  lrc?: File | null
}

export function useCreateProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async (input: CreateProjectInput) => {
      const form = new FormData()
      form.set('project_id', input.projectId)
      if (input.displayName) form.set('display_name', input.displayName)
      form.set('audio', input.audio)
      if (input.lrc) form.set('lrc', input.lrc)
      return api.postForm<ProjectSummary>('/api/projects', form)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROJECTS_QUERY_KEY })
    },
  })
}

export type DeleteScope = 'metadata' | 'artifacts' | 'all'

export function useDeletePreview(projectId: string | null, scope: DeleteScope) {
  return useQuery({
    queryKey: ['deletePreview', projectId, scope],
    queryFn: () => api.get<DeletePreviewRow[]>(`/api/projects/${projectId}/delete-preview`, { scope }),
    enabled: !!projectId,
  })
}

export function useDeleteProject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ projectId, scope, confirmed }: { projectId: string; scope: DeleteScope; confirmed: boolean }) =>
      api.delete(`/api/projects/${projectId}`, { scope, confirmed }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: PROJECTS_QUERY_KEY })
    },
  })
}

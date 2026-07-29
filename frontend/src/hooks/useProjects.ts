import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { projectDefaultsKey } from '@/hooks/useProjectDefaults'
import { api, ApiError } from '@/lib/api'
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

export interface DeleteProjectsInput {
  projectIds: string[]
  scope: DeleteScope
  confirmed: boolean
}

export interface DeleteProjectsResult {
  succeeded: string[]
  failed: { projectId: string; message: string }[]
}

export function useDeleteProjects() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: async ({ projectIds, scope, confirmed }: DeleteProjectsInput): Promise<DeleteProjectsResult> => {
      const succeeded: string[] = []
      const failed: DeleteProjectsResult['failed'] = []

      for (const projectId of projectIds) {
        try {
          await api.delete(`/api/projects/${projectId}`, { scope, confirmed })
          succeeded.push(projectId)
        } catch (err) {
          failed.push({
            projectId,
            message: err instanceof ApiError ? err.message : '删除失败',
          })
        }
      }

      if (succeeded.length === 0 && failed.length > 0) {
        throw new ApiError(400, failed[0].message, failed)
      }

      return { succeeded, failed }
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: PROJECTS_QUERY_KEY })
      for (const id of result.succeeded) {
        queryClient.removeQueries({ queryKey: ['deletePreview', id] })
        queryClient.removeQueries({ queryKey: projectDefaultsKey(id) })
      }
    },
  })
}

/** @deprecated Use `useDeleteProjects` — kept for callers that delete a single project. */
export function useDeleteProject() {
  const deleteProjects = useDeleteProjects()
  return {
    ...deleteProjects,
    mutate: (
      vars: { projectId: string; scope: DeleteScope; confirmed: boolean },
      options?: Parameters<typeof deleteProjects.mutate>[1]
    ) => deleteProjects.mutate({ projectIds: [vars.projectId], scope: vars.scope, confirmed: vars.confirmed }, options),
    mutateAsync: (vars: { projectId: string; scope: DeleteScope; confirmed: boolean }) =>
      deleteProjects.mutateAsync({ projectIds: [vars.projectId], scope: vars.scope, confirmed: vars.confirmed }),
  }
}

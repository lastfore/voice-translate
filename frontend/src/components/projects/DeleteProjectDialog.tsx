import { useState, type ReactNode } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Loader2Icon } from 'lucide-react'
import { toast } from 'sonner'

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Label } from '@/components/ui/label'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { useProject } from '@/context/ProjectContext'
import { useDeleteProjects, type DeleteScope } from '@/hooks/useProjects'
import { api } from '@/lib/api'
import { ApiError } from '@/lib/api'
import type { DeletePreviewRow } from '@/types/pipeline'

export interface DeleteProjectsResult {
  succeeded: string[]
  failed: { projectId: string; message: string }[]
}

export interface DeleteProjectDialogProps {
  projectIds: string[]
  trigger?: ReactNode
  open?: boolean
  onOpenChange?: (open: boolean) => void
  onDeleted?: (result: DeleteProjectsResult) => void
}

function previewTitle(projectIds: string[]): string {
  if (projectIds.length === 1) return `删除项目 ${projectIds[0]}`
  return `删除 ${projectIds.length} 个项目`
}

export function DeleteProjectDialog({
  projectIds,
  trigger,
  open: controlledOpen,
  onOpenChange,
  onDeleted,
}: DeleteProjectDialogProps) {
  const [internalOpen, setInternalOpen] = useState(false)
  const [scope, setScope] = useState<DeleteScope>('metadata')
  const deleteProjects = useDeleteProjects()
  const { projectId: activeProjectId, setProjectId } = useProject()

  const isControlled = controlledOpen !== undefined
  const open = isControlled ? controlledOpen : internalOpen

  const setOpen = (next: boolean) => {
    if (!isControlled) setInternalOpen(next)
    onOpenChange?.(next)
  }

  const previewQueries = useQueries({
    queries: projectIds.map((id) => ({
      queryKey: ['deletePreview', id, scope] as const,
      queryFn: () => api.get<DeletePreviewRow[]>(`/api/projects/${id}/delete-preview`, { scope }),
      enabled: open && projectIds.length > 0,
    })),
  })

  const previewRows = previewQueries.flatMap((query, index) => {
    const id = projectIds[index]
    return (query.data ?? []).map((row) => ({ ...row, projectId: id }))
  })
  const previewLoading = previewQueries.some((query) => query.isLoading)

  const handleDelete = () => {
    if (projectIds.length === 0) return

    deleteProjects.mutate(
      { projectIds, scope, confirmed: true },
      {
        onSuccess: (result) => {
          const { succeeded, failed } = result
          if (succeeded.length > 0) {
            if (activeProjectId && succeeded.includes(activeProjectId)) {
              setProjectId(null)
            }
            const label =
              succeeded.length === 1 ? `项目 ${succeeded[0]} 已删除` : `已删除 ${succeeded.length} 个项目`
            toast.success(label)
          }
          if (failed.length > 0) {
            const detail = failed.map((item) => `${item.projectId}: ${item.message}`).join('；')
            toast.error(`部分项目删除失败（${failed.length}）`, { description: detail })
          }
          setOpen(false)
          onDeleted?.(result)
        },
        onError: (err) => toast.error(err instanceof ApiError ? err.message : '删除失败'),
      }
    )
  }

  const dialogBody = (
    <AlertDialogContent className="flex max-h-[min(85vh,640px)] max-w-lg flex-col overflow-hidden p-6">
      <AlertDialogHeader className="shrink-0">
        <AlertDialogTitle>{previewTitle(projectIds)}</AlertDialogTitle>
        <AlertDialogDescription>此操作不可恢复，请谨慎选择删除范围。</AlertDialogDescription>
      </AlertDialogHeader>

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
        {projectIds.length > 1 && (
          <div className="min-w-0 space-y-1">
            <p className="text-sm text-muted-foreground">共 {projectIds.length} 个项目</p>
            <div
              className="h-24 overflow-y-auto rounded-md border p-2 text-xs text-muted-foreground"
              data-testid="delete-project-id-list"
            >
              <ul className="space-y-0.5">
                {projectIds.map((id) => (
                  <li key={id} className="break-all">
                    {id}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        )}

        <RadioGroup value={scope} onValueChange={(v) => setScope(v as DeleteScope)}>
          <div className="flex items-start gap-2">
            <RadioGroupItem value="metadata" id="scope-metadata" className="mt-0.5" />
            <Label htmlFor="scope-metadata" className="leading-snug">
              仅从列表移除（保留所有文件）
            </Label>
          </div>
          <div className="flex items-start gap-2">
            <RadioGroupItem value="artifacts" id="scope-artifacts" className="mt-0.5" />
            <Label htmlFor="scope-artifacts" className="leading-snug">
              删除产物（保留 input 原文件）
            </Label>
          </div>
          <div className="flex items-start gap-2">
            <RadioGroupItem value="all" id="scope-all" className="mt-0.5" />
            <Label htmlFor="scope-all" className="leading-snug">
              彻底删除（含 input 与 separated）
            </Label>
          </div>
        </RadioGroup>

        {previewLoading && <p className="text-xs text-muted-foreground">加载预览…</p>}
        {!previewLoading && previewRows.length > 0 && (
          <div className="min-w-0 space-y-1">
            <p className="text-xs text-muted-foreground">将删除 {previewRows.length} 个路径</p>
            <div
              className="max-h-32 overflow-y-auto rounded-md border p-2 text-xs"
              data-testid="delete-preview-list"
            >
              <div className="space-y-0.5">
                {previewRows.map((row, idx) => (
                  <p key={`${row.projectId}-${idx}`} className="break-all leading-relaxed">
                    [{row.kind}] {projectIds.length > 1 ? `${row.projectId}/` : ''}
                    {row.path}
                  </p>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      <AlertDialogFooter className="shrink-0 border-t pt-4">
        <AlertDialogCancel>取消</AlertDialogCancel>
        <AlertDialogAction
          onClick={handleDelete}
          disabled={deleteProjects.isPending || projectIds.length === 0}
          data-testid="delete-project-confirm"
        >
          {deleteProjects.isPending ? <Loader2Icon className="size-4 animate-spin" /> : null}
          确认删除
        </AlertDialogAction>
      </AlertDialogFooter>
    </AlertDialogContent>
  )

  if (trigger) {
    return (
      <AlertDialog open={open} onOpenChange={setOpen}>
        <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>
        {dialogBody}
      </AlertDialog>
    )
  }

  return (
    <AlertDialog open={open} onOpenChange={setOpen}>
      {dialogBody}
    </AlertDialog>
  )
}

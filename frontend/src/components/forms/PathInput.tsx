import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileIcon, FolderIcon, FolderOpenIcon } from 'lucide-react'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ScrollArea } from '@/components/ui/scroll-area'
import { api } from '@/lib/api'
import type { FsBrowseResponse } from '@/types/pipeline'

export interface PathInputProps {
  label: string
  value: string
  onChange: (path: string) => void
  directory?: boolean
  extensions?: string[]
  placeholder?: string
  helpText?: string
}

/**
 * Server-side path text field + browse dialog — migrated from
 * webui/components/path_input.py. Backed by `GET /api/fs/browse` (added in
 * Phase 1, see api/routers/filesystem.py — migration doc §5.3/§7).
 */
export function PathInput({ label, value, onChange, directory = false, extensions, placeholder, helpText }: PathInputProps) {
  const [open, setOpen] = useState(false)
  const [browsePath, setBrowsePath] = useState('')

  const { data, isLoading, isError } = useQuery({
    queryKey: ['fsBrowse', browsePath, directory, extensions?.join(',')],
    queryFn: () =>
      api.get<FsBrowseResponse>('/api/fs/browse', {
        path: browsePath,
        dirs_only: directory,
        extensions: extensions?.join(','),
      }),
    enabled: open,
  })

  const openDialog = () => {
    setBrowsePath('')
    setOpen(true)
  }

  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <div className="flex gap-2">
        <Input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder ?? `可手动输入路径，或点击右侧「浏览」选择${directory ? '文件夹' : '文件'}`}
          data-testid="path-input-text"
        />
        <Button type="button" variant="outline" onClick={openDialog} data-testid="path-input-browse">
          <FolderOpenIcon />
          浏览
        </Button>
      </div>
      {helpText && <p className="text-xs text-muted-foreground">{helpText}</p>}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>选择{directory ? '文件夹' : '文件'}</DialogTitle>
          </DialogHeader>
          <p className="truncate rounded bg-muted px-2 py-1 text-xs text-muted-foreground" data-testid="path-input-current-dir">
            /{data?.path ?? ''}
          </p>
          <ScrollArea className="h-72 rounded-md border">
            <div className="p-1">
              {isLoading && <p className="p-3 text-sm text-muted-foreground">加载中…</p>}
              {isError && <p className="p-3 text-sm text-destructive">目录加载失败</p>}
              {data?.parent !== null && data?.parent !== undefined && (
                <button
                  type="button"
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
                  onClick={() => setBrowsePath(data.parent ?? '')}
                >
                  <FolderIcon className="size-4" />
                  .. 上一级目录
                </button>
              )}
              {data?.entries.map((entry) => (
                <button
                  key={entry.path}
                  type="button"
                  className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent"
                  data-testid="path-input-entry"
                  onClick={() => {
                    if (entry.is_dir) {
                      setBrowsePath(entry.path)
                    } else {
                      onChange(entry.path)
                      setOpen(false)
                    }
                  }}
                >
                  {entry.is_dir ? <FolderIcon className="size-4" /> : <FileIcon className="size-4" />}
                  {entry.name}
                </button>
              ))}
              {data && data.entries.length === 0 && (
                <p className="p-3 text-sm text-muted-foreground">此目录为空</p>
              )}
            </div>
          </ScrollArea>
          {directory && (
            <DialogFooter>
              <Button
                type="button"
                onClick={() => {
                  onChange(data?.path ?? '')
                  setOpen(false)
                }}
                data-testid="path-input-choose-current"
              >
                选择当前文件夹
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}

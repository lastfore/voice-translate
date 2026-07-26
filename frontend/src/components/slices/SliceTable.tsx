import { useMemo } from 'react'
import { flexRender, getCoreRowModel, useReactTable, type ColumnDef } from '@tanstack/react-table'

import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'
import type { SliceRow } from '@/types/pipeline'

export interface SliceTableProps {
  rows: SliceRow[]
  selectedId: string | null
  onSelectRow: (row: SliceRow) => void
}

/**
 * Slice list preview table — migrated from webui/components/slice_preview.py
 * (`gr.Dataframe`), rendered with TanStack Table per migration doc §5.4.
 * Row click resolves the slice audio URL for playback; multi-select for
 * `SliceTuner` batch re-conversion is Phase 2 scope.
 */
export function SliceTable({ rows, selectedId, onSelectRow }: SliceTableProps) {
  const columns = useMemo<ColumnDef<SliceRow>[]>(
    () => [
      { accessorKey: 'id', header: 'id' },
      { accessorKey: 'start_ms', header: 'start_ms' },
      { accessorKey: 'end_ms', header: 'end_ms' },
      { accessorKey: 'text', header: 'text' },
      { accessorKey: 'file', header: 'file' },
      {
        accessorKey: 'status',
        header: 'status',
        cell: ({ row }) => (row.original.status ? <Badge variant="secondary">{row.original.status}</Badge> : null),
      },
    ],
    []
  )

  const table = useReactTable({ data: rows, columns, getCoreRowModel: getCoreRowModel() })

  return (
    <div className="rounded-md border" data-testid="slice-table">
      <Table>
        <TableHeader>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHead key={header.id}>
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHead>
              ))}
            </TableRow>
          ))}
        </TableHeader>
        <TableBody>
          {table.getRowModel().rows.length === 0 && (
            <TableRow>
              <TableCell colSpan={columns.length} className="text-center text-muted-foreground">
                暂无切片数据
              </TableCell>
            </TableRow>
          )}
          {table.getRowModel().rows.map((row) => {
            const isSelected = row.original.id === selectedId
            return (
              <TableRow
                key={row.id}
                data-state={isSelected ? 'selected' : undefined}
                data-testid="slice-table-row"
                data-slice-id={row.original.id}
                className={cn('cursor-pointer', isSelected && 'bg-muted')}
                onClick={() => onSelectRow(row.original)}
              >
                {row.getVisibleCells().map((cell) => (
                  <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
                ))}
              </TableRow>
            )
          })}
        </TableBody>
      </Table>
    </div>
  )
}

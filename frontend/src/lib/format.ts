/**
 * Display formatting helpers — migrated from webui/helpers.py's pure
 * formatting functions (migration doc §4.2). Path/media/security logic stays
 * server-side; only presentation logic lives here.
 */

import type { ProjectSummary, StageName, StageStatus } from '@/types/pipeline'

export const STAGE_LABELS: Record<StageName, string> = {
  separate: '分离',
  slice: '切片',
  convert: '转换',
  merge: '合并',
}

const STAGE_ORDER: StageName[] = ['separate', 'slice', 'convert', 'merge']

export function stageStatusIcon(status: StageStatus | undefined): string {
  switch (status) {
    case 'done':
      return '●'
    case 'running':
      return '◐'
    case 'failed':
      return '✗'
    default:
      return '○'
  }
}

/** Equivalent of `webui.helpers.format_stage_icons()`. */
export function formatStageIcons(stageStatus: Partial<Record<StageName, StageStatus>>): string {
  return STAGE_ORDER.map((stage) => `${stageStatusIcon(stageStatus[stage])}${STAGE_LABELS[stage]}`).join(' ')
}

/** Equivalent of `webui.helpers.format_project_choice()`. */
export function formatProjectChoice(summary: ProjectSummary): string {
  return `${summary.display_name} (${summary.id}) — ${formatStageIcons(summary.stages)}`
}

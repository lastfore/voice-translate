/**
 * Mode constants — migrated from webui/mode_utils.py + webui/components/mode_panel.py
 * (migration doc §4.3). No index<->mode bidirectional sync needed here: React
 * `Tabs` is controlled directly via `value={mode}` / `onValueChange={setMode}`.
 */

import type { ConvertMode, MergeMode, SliceMode } from '@/types/pipeline'

export const SLICE_VAD: SliceMode = 'vad'
export const SLICE_LRC: SliceMode = 'lrc'
export const SLICE_MODES: SliceMode[] = [SLICE_LRC, SLICE_VAD]
export const SLICE_TAB_LABELS: Record<SliceMode, string> = {
  vad: 'VAD 断句',
  lrc: 'LRC 歌词断句',
}

export const CONVERT_BATCH: ConvertMode = 'slice_batch'
export const CONVERT_FULL: ConvertMode = 'full_track'
export const CONVERT_MODES: ConvertMode[] = [CONVERT_BATCH, CONVERT_FULL]
export const CONVERT_TAB_LABELS: Record<ConvertMode, string> = {
  slice_batch: '切片批量',
  full_track: '整轨快捷',
}

export const MERGE_WHOLE: MergeMode = 'whole_track'
export const MERGE_SLICE: MergeMode = 'slice_stitch'
export const MERGE_MODES: MergeMode[] = [MERGE_WHOLE, MERGE_SLICE]
export const MERGE_TAB_LABELS: Record<MergeMode, string> = {
  whole_track: '整轨合并',
  slice_stitch: '切片拼接',
}

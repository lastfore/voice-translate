/**
 * TypeScript types mirroring `api/schemas/*.py` + `pipeline/stage_params.py`.
 *
 * There is no OpenAPI/Pydantic generation for the schema endpoint (it's a
 * hand-rolled JSON shape, not a Pydantic model — see migration doc §5.2), so
 * these types are hand-maintained. Keep them in sync with:
 *   - api/routers/params.py `_param_to_dict()`
 *   - api/services/pipeline_service.py `get_project_defaults()`
 *   - api/routers/stages.py `sse_frame()` / `stream_stage_events()`
 *   - api/routers/slices.py / api/services/slice_service.py
 *   - api/routers/filesystem.py `browse()`
 */

export type StageName = 'separate' | 'slice' | 'convert' | 'merge'

export type StageStatus = 'not_run' | 'running' | 'done' | 'failed' | 'skipped'

export type SliceMode = 'vad' | 'lrc'

export type ConvertMode = 'slice_batch' | 'full_track'

export type MergeMode = 'whole_track' | 'slice_stitch'

export type ParamType = 'int' | 'float' | 'bool' | 'choice' | 'str'

/** One entry from `GET /api/params/schema` — mirrors `StageParam` (pipeline/stage_params.py). */
export interface StageParamSchema {
  key: string
  label: string
  description: string
  param_type: ParamType
  default: unknown
  choices: string[] | null
  minimum: number | null
  maximum: number | null
  step: number | null
  wizard: boolean
  vad_only: boolean
  slice_batch_only: boolean
  full_track_only: boolean
}

export interface StageParamSection {
  title: string
  keys: string[]
}

/** Response of `GET /api/params/schema`. */
export interface StageParamSchemaResponse {
  stage: string
  params: StageParamSchema[]
  sections: StageParamSection[]
}

export type StageParamValues = Record<string, unknown>

/** `ProjectSummary` — `Project.to_summary()` in pipeline/models.py. */
export interface ProjectSummary {
  id: string
  display_name: string
  updated_at: string
  stages: Record<StageName, StageStatus>
  input_audio: string | null
  input_lrc: string | null
}

export type StageParamsByStage = Record<StageName, StageParamValues>

export interface ProjectArtifacts {
  sep_vocals: string | null
  sep_instrumental: string | null
  convert_full_track: string | null
  convert_dir: string | null
  mixed: string | null
}

/** Response of `GET /api/projects/{id}/defaults` — pipeline_service.get_project_defaults(). */
export interface ProjectDefaults {
  display_name: string
  input_audio: string | null
  input_lrc: string | null
  mix_audio: string
  vocals_path: string
  lrc_path: string
  slice_mode: SliceMode
  active_slice_mode: SliceMode
  convert_mode: ConvertMode
  reference: string
  slices_dir: string
  manifest: string
  merge_vocals_file: string
  merge_vocals_dir: string
  merge_instrumental: string
  merge_reference: string
  merge_profile: string
  merge_mode: MergeMode
  stage_status: Record<StageName, StageStatus>
  stage_params: StageParamsByStage
  wizard_params: StageParamValues
  artifacts: ProjectArtifacts
}

/** SSE `log` event payload — `ProgressEvent.to_ui_dict()` in pipeline/models.py. */
export interface StageLogEvent {
  project_id: string
  stage: StageName
  job_id: string
  percent: number
  message: string
  log_line: string | null
}

/** SSE `done` event payload — api/routers/stages.py `run_stage()`. */
export interface StageDoneEvent {
  success: boolean
  error: string | null
  artifacts: Record<string, unknown>
}

/** SSE `error` event payload (transport/exception-level, not a failed stage run). */
export interface StageErrorEvent {
  message: string
}

export type StageSseEvent =
  | { type: 'log'; data: StageLogEvent }
  | { type: 'done'; data: StageDoneEvent }
  | { type: 'error'; data: StageErrorEvent }
  | { type: string; data: unknown }

/** One row of `GET /api/projects/{id}/slices` — api/services/slice_service.py. */
export interface SliceRow {
  id: string
  start_ms: number | null
  end_ms: number | null
  text: string
  file: string
  status: string
  audio_url: string | null
}

export interface SliceTableResponse {
  mode: SliceMode
  dir_path: string | null
  rows: SliceRow[]
  first_audio_url: string | null
}

/** `GET /api/fs/browse` response — api/routers/filesystem.py. */
export interface FsEntry {
  name: string
  path: string
  is_dir: boolean
}

export interface FsBrowseResponse {
  path: string
  parent: string | null
  entries: FsEntry[]
}

export interface DeletePreviewRow {
  kind: string
  path: string
}

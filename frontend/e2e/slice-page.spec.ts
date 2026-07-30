import { expect, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { fileURLToPath } from 'node:url'

function makeFakeFlac(): string {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vt-e2e-'))
  const p = path.join(tmp, 'sample.flac')
  fs.writeFileSync(p, Buffer.from('fake-flac-for-e2e'))
  return p
}

async function createProject(page: any, projectId: string, audioPath: string) {
  await page.getByTestId('create-project-trigger').click()
  await page.getByTestId('create-project-id').fill(projectId)
  await page.locator('input[data-testid="create-project-audio"]').setInputFiles(audioPath)
  await page.getByTestId('create-project-submit').click()
  await expect(page.getByTestId('project-list').getByText(`(${projectId})`)).toBeVisible()
}

async function selectProject(page: any, projectId: string) {
  await page.getByTestId('project-list').locator(`[data-project-id="${projectId}"]`).click()
}

const repoRoot = path.resolve(fileURLToPath(import.meta.url), '..', '..', '..')

function writeSliceData(projectId: string, mode: 'vad' | 'lrc', rows: Array<{ id: string; text: string }>) {
  const root = repoRoot
  const modeDir = path.join(root, 'output', 'slices', projectId, mode)
  fs.mkdirSync(modeDir, { recursive: true })

  const slices = rows.map((row, index) => ({
    id: row.id,
    start_ms: index * 1000,
    end_ms: (index + 1) * 1000,
    text: row.text,
    file: `${row.id}.flac`,
  }))

  for (const row of rows) {
    fs.writeFileSync(path.join(modeDir, `${row.id}.flac`), Buffer.from('fake-slice-audio'))
  }

  fs.writeFileSync(
    path.join(modeDir, 'manifest.json'),
    JSON.stringify({ slices }, null, 2),
    'utf-8'
  )
}

/**
 * TC-Phase1-03: slice page mode switch correctly shows per-mode data.
 */
test('slice page mode switch shows correct rows', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `slice-mode-${Date.now()}`

  writeSliceData(projectId, 'vad', [{ id: 'v0', text: 'vad-hello' }])
  writeSliceData(projectId, 'lrc', [{ id: 'l0', text: 'lrc-hello' }])

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)
  await selectProject(page, projectId)
  await page.getByTestId('tab-slice').click()
  await page.waitForSelector('[data-testid="slice-page"]')

  // Default mode depends on project state; force VAD to verify its row.
  await page.getByTestId('mode-tab-vad').click()
  await expect(page.getByTestId('slice-table').getByText('v0', { exact: true })).toBeVisible()
  await expect(page.getByTestId('slice-table').getByText('vad-hello')).toBeVisible()

  await page.getByTestId('mode-tab-lrc').click()
  await expect(page.getByTestId('slice-table').getByText('l0', { exact: true })).toBeVisible()
  await expect(page.getByTestId('slice-table').getByText('lrc-hello')).toBeVisible()
  await expect(page.getByTestId('slice-table').getByText('v0', { exact: true })).not.toBeVisible()
})

/**
 * TC-P1-06: selecting a slice table row resolves the audio preview URL.
 */
test('slice table row selection resolves audio preview', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `slice-audio-${Date.now()}`

  writeSliceData(projectId, 'vad', [{ id: 'v0', text: 'vad-hello' }])

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)
  await selectProject(page, projectId)
  await page.getByTestId('tab-slice').click()
  await page.waitForSelector('[data-testid="slice-page"]')
  await page.getByTestId('mode-tab-vad').click()

  await page.getByTestId('slice-table').locator('[data-slice-id="v0"]').click()
  const audio = page.locator('audio[data-testid="artifact-audio"]')
  await expect(audio).toBeVisible()
  const src = await audio.getAttribute('src')
  expect(src).toContain('/api/media?path=')
  expect(src).toContain('output/slices')
})

/**
 * TC-Phase4-01: LRC mode shows onset-alignment params; VAD params stay hidden.
 */
test('lrc mode shows onset alignment params', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `slice-lrc-params-${Date.now()}`

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)
  await selectProject(page, projectId)
  await page.getByTestId('tab-slice').click()
  await page.waitForSelector('[data-testid="slice-page"]')

  await page.getByTestId('mode-tab-vad').click()
  await page.getByTestId('advanced-params-trigger').click()
  await expect(page.getByTestId('param-vad_threshold')).toBeVisible()
  await expect(page.getByTestId('param-boundary_mode')).toHaveCount(0)

  await page.getByTestId('mode-tab-lrc').click()
  await page.getByTestId('advanced-params-trigger').click()
  await expect(page.getByTestId('param-boundary_mode')).toBeVisible()
  await expect(page.getByTestId('param-search_margin_ms')).toBeVisible()
  await expect(page.getByTestId('param-onset_min_lead_silence_ms')).toBeVisible()
  await expect(page.getByTestId('param-min_slice_ms')).toBeVisible()
  await expect(page.getByTestId('param-onset_energy_threshold_db')).toBeVisible()
  await expect(page.getByTestId('param-safety_margin_ms')).toBeVisible()
  await expect(page.getByTestId('param-g2p_preroll_ms')).toBeVisible()
  await expect(page.getByTestId('param-boundary_zcr_weight')).toBeVisible()
  await expect(page.getByTestId('param-phoneme_align_mode')).toBeVisible()
  await page.getByTestId('param-phoneme_align_mode').click()
  await expect(page.getByRole('option', { name: 'remote' })).toBeVisible()
  await expect(page.getByTestId('param-vad_threshold')).toHaveCount(0)
})

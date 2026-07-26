import { expect, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'

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

/**
 * TC-Phase2-03: slice tuner retune only affects selected slices.
 *
 * We intercept the slices table and overrides APIs so no real slice stage is
 * needed, then verify that clicking "重转选中片" sends a convert run request
 * whose slice_ids matches the selected rows.
 */
test('slice tuner retune targets only selected slices', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `tuner-${Date.now()}`
  let savedOverrides = false
  let capturedBody: any = null

  await page.route(new RegExp(`/api/projects/${projectId}/slices`), async (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        mode: 'vad',
        dir_path: 'output/slices/xxx/vad',
        rows: [
          { id: 's0', start_ms: 0, end_ms: 1000, text: 'hello', file: 's0.flac', status: 'ready', audio_url: null },
          { id: 's1', start_ms: 1000, end_ms: 2000, text: 'world', file: 's1.flac', status: 'ready', audio_url: null },
        ],
        first_audio_url: null,
      }),
    })
  })

  await page.route(new RegExp(`/api/projects/${projectId}/slices/overrides`), async (route) => {
    if (route.request().method() === 'PUT') {
      savedOverrides = true
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          slice_mode: 'vad',
          global_defaults: { diffusion_steps: 40, fp16: true },
          slices: { s0: { diffusion_steps: 55 } },
          orphans: [],
        }),
      })
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          slice_mode: 'lrc',
          global_defaults: { diffusion_steps: 40, fp16: true },
          slices: savedOverrides ? { s0: { diffusion_steps: 55 } } : {},
          orphans: [],
        }),
      })
    }
  })

  await page.route(`/api/projects/${projectId}/stages/convert/run`, async (route) => {
    capturedBody = route.request().postDataJSON()
    const sse =
      'event: log\ndata: {"project_id":"' + projectId + '","stage":"convert","job_id":"job-test","percent":100,"message":"done","log_line":"done"}\n\n' +
      'event: done\ndata: {"success":true,"error":null,"artifacts":{}}\n\n'
    route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: sse,
    })
  })

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)
  await selectProject(page, projectId)
  await page.getByTestId('tab-convert').click()
  await page.waitForSelector('[data-testid="convert-page"]')

  await page.getByTestId('mode-tab-slice_tuner').click()
  await page.waitForSelector('[data-testid="slice-tuner"]')
  await page.waitForSelector('[data-testid="slice-tuner-check-s0"]')

  await page.getByTestId('slice-tuner-check-s0').click()

  // Expand advanced and change a numeric param so we have non-default values to save.
  await page.getByTestId('advanced-params-trigger').click()
  const diffusionInput = page.getByTestId('param-diffusion_steps')
  await expect(diffusionInput).toBeVisible()
  await diffusionInput.fill('55')

  await page.getByTestId('stage-run-submit').click()
  await page.getByTestId('slice-tuner-retune').click()

  await expect.poll(() => capturedBody).toBeTruthy()
  expect(capturedBody.params.slice_ids).toEqual(['s0'])
  expect(capturedBody.params.mode).toBe('slice_batch')
  expect(capturedBody.params.skip_existing).toBe(false)
})

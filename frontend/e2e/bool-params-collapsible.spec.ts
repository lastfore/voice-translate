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
 * TC-P0-12: bool parameters are submitted correctly even when the advanced
 * Collapsible section is collapsed.
 *
 * The convert stage has bool params (`fp16`, `auto_f0_adjust`) rendered outside
 * the Collapsible and numeric params inside it. We intercept the SSE run
 * request and verify the body contains the toggled bool value and the numeric
 * value.
 */
test('bool params survive collapsed advanced section', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `bool-${Date.now()}`
  let capturedBody: any = null

  await page.route(`/api/projects/${projectId}/stages/convert/run`, async (route) => {
    capturedBody = route.request().postDataJSON()
    // Return a minimal SSE stream so the UI treats the run as done.
    const sse =
      'event: log\ndata: {"project_id":"' +
      projectId +
      '","stage":"convert","job_id":"job-test","percent":100,"message":"done","log_line":"done"}\n\n' +
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

  // Bool param is outside the collapsible (Radix Checkbox renders as a button).
  const fp16Checkbox = page.getByTestId('param-fp16')
  await expect(fp16Checkbox).toBeVisible()
  await fp16Checkbox.click()

  // Expand advanced, change a numeric param, then collapse.
  await page.getByTestId('advanced-params-trigger').click()
  const diffusionInput = page.getByTestId('param-diffusion_steps')
  await expect(diffusionInput).toBeVisible()
  await diffusionInput.fill('55')
  await page.getByTestId('advanced-params-trigger').click()

  // Submit the form while the advanced section is collapsed.
  await page.getByTestId('stage-run-submit').click()

  await expect.poll(() => capturedBody).toBeTruthy()
  expect(capturedBody.params.fp16).toBe(false)
  expect(capturedBody.params.diffusion_steps).toBe(55)
  expect(capturedBody.params.mode).toBe('slice_batch')
})

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
 * TC-Phase3-01/02/03: wizard single-step / run-from / run-all submit the
 * correct stages to the pipeline run endpoint.
 */
test('wizard submits correct stages for single-step, run-from, and run-all', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `wizard-${Date.now()}`
  const captured: any[] = []

  await page.route(`/api/projects/${projectId}/pipeline/run`, async (route) => {
    captured.push(route.request().postDataJSON())
    const sse =
      'event: log\ndata: {"project_id":"' + projectId + '","stage":"separate","job_id":"job-test","percent":100,"message":"done","log_line":"done"}\n\n' +
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
  await page.getByTestId('tab-wizard').click()
  await page.waitForSelector('[data-testid="wizard-page"]')

  // Single step on separate
  await page.getByTestId('stage-run-submit').click()
  await expect.poll(() => captured.length).toBeGreaterThanOrEqual(1)
  expect(captured[0].stages).toEqual(['separate'])

  // Switch to slice and run-from
  await page.getByTestId('wizard-step-slice').click()
  await page.getByTestId('wizard-run-from').click()
  await expect.poll(() => captured.length).toBeGreaterThanOrEqual(2)
  expect(captured[1].stages).toEqual(['slice', 'convert', 'merge'])

  // Run all
  await page.getByTestId('wizard-run-all').click()
  await expect.poll(() => captured.length).toBeGreaterThanOrEqual(3)
  expect(captured[2].stages).toBeUndefined()
})

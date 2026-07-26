import { expect, test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'

function makeFakeAudio(ext: string): string {
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'vt-e2e-'))
  const p = path.join(tmp, `sample.${ext}`)
  fs.writeFileSync(p, Buffer.from(`fake-${ext}-for-e2e`))
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
 * TC-Phase2-06: reference audio upload path is used in the convert run.
 *
 * We intercept the reference upload endpoint and the convert run SSE, then
 * verify that the captured convert body contains the uploaded reference path.
 */
test('uploaded reference audio is submitted to convert run', async ({ page }) => {
  const audioPath = makeFakeAudio('flac')
  const refPath = makeFakeAudio('wav')
  const projectId = `ref-${Date.now()}`
  let capturedBody: any = null

  await page.route(new RegExp(`/api/projects/${projectId}/reference`), async (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ reference: 'input/ref-upload/reference.wav' }),
    })
  })

  await page.route(new RegExp(`/api/projects/${projectId}/stages/convert/run`), async (route) => {
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

  await page.locator('input[data-testid="convert-reference-upload"]').setInputFiles(refPath)

  await page.getByTestId('stage-run-submit').click()
  await expect.poll(() => capturedBody).toBeTruthy()
  expect(capturedBody.params.reference).toBe('input/ref-upload/reference.wav')
})

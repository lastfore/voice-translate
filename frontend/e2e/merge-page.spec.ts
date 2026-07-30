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
 * TC-Phase2-04: Merge dual modes can run and produce mixed.
 *
 * We intercept the merge run SSE and assert that the submitted body contains
 * the selected merge_mode and a profile.
 */
test('merge page runs both modes and submits correct merge_mode', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `merge-${Date.now()}`
  let capturedBody: any = null

  await page.route(new RegExp(`/api/projects/${projectId}/stages/merge/run`), async (route) => {
    capturedBody = route.request().postDataJSON()
    const sse =
      'event: log\ndata: {"project_id":"' + projectId + '","stage":"merge","job_id":"job-test","percent":100,"message":"done","log_line":"done"}\n\n' +
      'event: done\ndata: {"success":true,"error":null,"artifacts":{"mixed":"output/merged/xxx/mixed.flac"}}\n\n'
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
  await page.getByTestId('tab-merge').click()
  await page.waitForSelector('[data-testid="merge-page"]')

  // Default mode is whole_track; run it.
  await page.getByTestId('stage-run-submit').click()
  await expect.poll(() => capturedBody).toBeTruthy()
  expect(capturedBody.params.merge_mode).toBe('whole_track')
  expect(capturedBody.params.profile).toBeTruthy()

  // Switch to slice_stitch and run again.
  capturedBody = null
  await page.getByTestId('mode-tab-slice_stitch').click()
  await page.getByTestId('advanced-params-trigger').click()
  await expect(page.getByTestId('param-boundary_crossfade_ms')).toBeVisible()
  await page.getByTestId('stage-run-submit').click()
  await expect.poll(() => capturedBody).toBeTruthy()
  expect(capturedBody.params.merge_mode).toBe('slice_stitch')
})

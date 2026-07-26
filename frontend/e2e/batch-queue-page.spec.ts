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

/**
 * TC-Phase3-04/05/06: batch queue page can enqueue, run, and clear.
 *
 * We intercept the persistent status SSE with a finite stream and verify the
 * run request is sent after clicking "执行队列".
 */
test('batch queue page enqueues and runs', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `batch-${Date.now()}`
  let enqueueCount = 0
  let runCaptured = false
  let clearCount = 0

  await page.route('/api/batch/status', async (route) => {
    const sse = 'event: status\ndata: {"running":false,"items":[]}\n\n'
    route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: sse,
    })
  })

  await page.route('/api/batch/enqueue', async (route) => {
    enqueueCount += 1
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ id: `batch-${enqueueCount}`, project_id: projectId, stages: ['separate'], status: 'pending' }),
    })
  })

  await page.route('/api/batch/run', async (route) => {
    runCaptured = true
    const sse =
      'event: log\ndata: {"project_id":"' + projectId + '","stage":"separate","job_id":"job-test","percent":100,"message":"done","log_line":"done"}\n\n' +
      'event: done\ndata: {"success":true}\n\n'
    route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: sse,
    })
  })

  await page.route('/api/batch/clear', async (route) => {
    clearCount += 1
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ removed: 1 }) })
  })

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)
  await page.getByTestId('tab-batch').click()
  await page.waitForSelector('[data-testid="batch-queue-page"]')

  await page.getByTestId(`batch-project-${projectId}`).click()
  await page.getByTestId('batch-enqueue').click()
  await expect.poll(() => enqueueCount).toBe(1)

  await page.getByTestId('batch-run').click()
  await expect.poll(() => runCaptured).toBe(true)

  await page.getByTestId('batch-clear').click()
  await expect.poll(() => clearCount).toBe(1)
})

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
 * TC-Phase1-06 / TC-P0-09: leaving the page aborts the in-flight stage SSE.
 *
 * Radix Tabs keep inactive panels mounted, so tab switch alone does not unmount
 * `useStageRun`. A full page reload destroys the JS context and aborts fetch.
 * Playwright may not emit `requestfailed` on reload, so we assert the UI is
 * no longer stuck in a running state after reload.
 */
test('page reload during run returns to idle state', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `cancel-${Date.now()}`

  await page.route(new RegExp(`/api/projects/${projectId}/stages/separate/run`), async (route) => {
    await new Promise<void>(() => {})
  })

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)
  await selectProject(page, projectId)
  await page.getByTestId('tab-separate').click()
  await page.waitForSelector('[data-testid="separate-page"]')
  await page.getByTestId('stage-run-submit').click()
  await expect(page.getByTestId('separate-cancel')).toBeVisible()

  await page.reload()
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await selectProject(page, projectId)
  await page.getByTestId('tab-separate').click()
  await page.waitForSelector('[data-testid="separate-page"]')
  await expect(page.getByTestId('separate-cancel')).not.toBeVisible()
  await expect(page.getByTestId('stage-run-submit')).toBeEnabled()
})

/**
 * TC-Phase1-06 (interactive cancel): explicit cancel button also aborts SSE.
 */
test('cancel button aborts in-flight separate run', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `cancel-btn-${Date.now()}`
  let runRequestSettled = false

  page.on('requestfailed', (request) => {
    if (!request.url().includes(`/api/projects/${projectId}/stages/separate/run`)) return
    const failure = request.failure()
    if (failure && /abort/i.test(failure.errorText)) {
      runRequestSettled = true
    }
  })

  await page.route(new RegExp(`/api/projects/${projectId}/stages/separate/run`), async (route) => {
    await new Promise<void>(() => {})
  })

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)
  await selectProject(page, projectId)
  await page.getByTestId('tab-separate').click()
  await page.waitForSelector('[data-testid="separate-page"]')
  await page.getByTestId('stage-run-submit').click()
  await expect(page.getByTestId('separate-cancel')).toBeVisible()
  await page.getByTestId('separate-cancel').click()
  await expect.poll(() => runRequestSettled).toBe(true)
})

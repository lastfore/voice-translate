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
 * TC-Phase1-02: separate page run completes and refreshes defaults/artifacts.
 *
 * Uses mocked SSE (no GPU/model) and a staged defaults refetch to prove the
 * post-run `invalidateQueries(projectDefaultsKey)` path updates the UI.
 */
test('separate page run refreshes defaults and artifacts', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `sep-${Date.now()}`
  let defaultsFetchCount = 0
  let cachedDefaults: any = null

  await page.route(new RegExp(`/api/projects/${projectId}/defaults`), async (route) => {
    defaultsFetchCount++
    if (!cachedDefaults) {
      const resp = await route.fetch()
      cachedDefaults = await resp.json()
    }
    const body =
      defaultsFetchCount === 1
        ? {
            ...cachedDefaults,
            artifacts: {
              ...cachedDefaults.artifacts,
              sep_vocals: null,
              sep_instrumental: null,
            },
          }
        : {
            ...cachedDefaults,
            stage_status: { ...cachedDefaults.stage_status, separate: 'done' },
            artifacts: {
              ...cachedDefaults.artifacts,
              sep_vocals: '/api/media?path=output/e2e/vocals.flac',
              sep_instrumental: '/api/media?path=output/e2e/instrumental.flac',
            },
          }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  })

  await page.route(new RegExp(`/api/projects/${projectId}/stages/separate/run`), async (route) => {
    const sse =
      `event: log\ndata: {"project_id":"${projectId}","stage":"separate","job_id":"job-test","percent":50,"message":"running","log_line":"running"}\n\n` +
      `event: done\ndata: {"success":true,"error":null,"artifacts":{"sep_vocals":"output/e2e/vocals.flac","sep_instrumental":"output/e2e/instrumental.flac"}}\n\n`
    await route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: sse,
    })
  })

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)
  await selectProject(page, projectId)
  await page.getByTestId('tab-separate').click()
  await page.waitForSelector('[data-testid="separate-page"]')

  await expect(page.getByText('暂无产物')).toHaveCount(2)

  await page.getByTestId('stage-run-submit').click()
  await expect(page.getByText('分离完成', { exact: true })).toBeVisible()

  await expect.poll(() => defaultsFetchCount).toBeGreaterThanOrEqual(2)
  const audioPlayers = page.getByTestId('artifact-audio')
  await expect(audioPlayers).toHaveCount(2)
  await expect(audioPlayers.first()).toHaveAttribute('src', /vocals\.flac/)
})

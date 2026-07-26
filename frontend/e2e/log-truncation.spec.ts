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
 * TC-Phase4-05: log panel truncates after 80 lines and keeps the latest logs.
 */
test('log panel truncates to 80 lines', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `log-${Date.now()}`

  const lines: string[] = []
  for (let i = 1; i <= 100; i++) {
    lines.push(
      `event: log\ndata: {"project_id":"${projectId}","stage":"convert","job_id":"job-test","percent":${i},"message":"line ${i}","log_line":"line ${i}"}\n\n`
    )
  }
  lines.push('event: done\ndata: {"success":true,"error":null,"artifacts":{}}\n\n')

  await page.route(`/api/projects/${projectId}/stages/convert/run`, async (route) => {
    route.fulfill({
      status: 200,
      headers: { 'content-type': 'text/event-stream' },
      body: lines.join(''),
    })
  })

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)
  await selectProject(page, projectId)
  await page.getByTestId('tab-convert').click()
  await page.waitForSelector('[data-testid="convert-page"]')
  await page.getByTestId('stage-run-submit').click()

  await expect.poll(async () => page.getByTestId('stage-log-line').count()).toBe(80)
  await expect(page.getByTestId('stage-log-truncated')).toContainText('已隐藏 20')
  await expect(page.getByTestId('stage-log-line').first()).toContainText('[21%]')
})

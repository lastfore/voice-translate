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
 * TC-Phase4-04: slice table renders and interacts with a large manifest.
 */
test('slice table handles 150 rows', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `perf-${Date.now()}`

  const rows = Array.from({ length: 150 }, (_, i) => ({
    id: `s${i}`,
    start_ms: i * 1000,
    end_ms: (i + 1) * 1000,
    text: `line ${i}`,
    file: `s${i}.flac`,
    status: 'ready',
    audio_url: null,
  }))

  await page.route(new RegExp(`/api/projects/${projectId}/slices`), async (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ mode: 'lrc', dir_path: 'output/slices/xxx/lrc', rows, first_audio_url: null }),
    })
  })

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)
  await selectProject(page, projectId)
  await page.getByTestId('tab-slice').click()
  await page.waitForSelector('[data-testid="slice-page"]')

  await expect.poll(async () => page.getByTestId('slice-table-row').count()).toBe(150)

  // Click the last row to verify selection works in a large table.
  await page.getByTestId('slice-table-row').last().click()
  await expect(page.getByTestId('slice-table-row').last()).toHaveAttribute('data-state', 'selected')
})

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

async function openVadThreshold(page: any) {
  await page.getByTestId('mode-tab-vad').click()
  await page.getByTestId('advanced-params-trigger').click()
  const thresholdInput = page.locator('input[data-testid="param-vad_threshold"]')
  await expect(thresholdInput).toBeVisible()
  return thresholdInput
}

/**
 * TC-Phase1-01 / TC-P1-05: project switch remount behavior.
 *
 * Changing a slice parameter on project A without submitting must not leak
 * into project B when switching projects. The `key={projectId}` remount in
 * SlicePage should re-seed the form from the new project's defaults.
 */
test('project switch remount discards dirty form values', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const idA = `a-${Date.now()}`
  const idB = `b-${Date.now() + 1}`

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')

  await createProject(page, idA, audioPath)
  await createProject(page, idB, audioPath)

  await selectProject(page, idA)
  await page.getByTestId('tab-slice').click()
  await page.waitForSelector('[data-testid="slice-page"]')

  const thresholdInput = await openVadThreshold(page)
  const defaultValue = await thresholdInput.inputValue()

  // Change the value without submitting.
  await thresholdInput.fill('0.88')

  // Switch to project B and verify the threshold reverted to the default.
  await selectProject(page, idB)
  await page.waitForSelector('[data-testid="slice-page"]')
  const bInput = await openVadThreshold(page)
  const bValue = await bInput.inputValue()
  expect(bValue).toBe(defaultValue)
  expect(bValue).not.toBe('0.88')

  // Switch back to A and verify it is also re-seeded from defaults.
  await selectProject(page, idA)
  await page.waitForSelector('[data-testid="slice-page"]')
  const aInput = await openVadThreshold(page)
  const aValue = await aInput.inputValue()
  expect(aValue).toBe(defaultValue)
  expect(aValue).not.toBe('0.88')
})

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

async function createProject(page: import('@playwright/test').Page, projectId: string, audioPath: string) {
  await page.getByTestId('create-project-trigger').click()
  await page.getByTestId('create-project-id').fill(projectId)
  await page.locator('input[data-testid="create-project-audio"]').setInputFiles(audioPath)
  await page.getByTestId('create-project-submit').click()
  await expect(page.getByTestId('project-list').getByText(`(${projectId})`)).toBeVisible()
}

async function deleteProjectWithScope(
  page: import('@playwright/test').Page,
  triggerTestId: string,
  scopeLabel: string
) {
  await page.getByTestId(triggerTestId).click()
  await page.getByLabel(scopeLabel).click()
  await page.getByTestId('delete-project-confirm').click()
}

test('sidebar scroll keeps project list reachable', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const prefix = `scroll-${Date.now()}`

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')

  for (let i = 0; i < 8; i += 1) {
    await createProject(page, `${prefix}-${i}`, audioPath)
  }

  const list = page.getByTestId('project-list')
  await list.locator(`[data-project-id="${prefix}-7"]`).scrollIntoViewIfNeeded()
  await expect(list.locator(`[data-project-id="${prefix}-7"]`)).toBeVisible()
})

test('delete project from header and row', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `del-header-${Date.now()}`

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)

  await page.getByTestId('project-list').locator(`[data-project-id="${projectId}"]`).click()
  await expect(page.getByTestId('project-header')).toContainText(projectId)

  await deleteProjectWithScope(page, 'delete-project-trigger', '仅从列表移除（保留所有文件）')
  await expect(page.getByTestId('project-list').getByText(`(${projectId})`)).not.toBeVisible()
  await expect(page.getByTestId('project-header-empty')).toBeVisible()
})

test('select all toggles every project in multi-select mode', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const idA = `all-a-${Date.now()}`
  const idB = `all-b-${Date.now() + 1}`

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')

  await createProject(page, idA, audioPath)
  await createProject(page, idB, audioPath)

  await page.getByTestId('project-multi-select-toggle').click()
  await page.getByTestId('project-select-all').click()

  await expect(page.getByTestId(`project-select-${idA}`)).toBeChecked()
  await expect(page.getByTestId(`project-select-${idB}`)).toBeChecked()
  await expect(page.getByTestId('project-select-all')).toHaveText('取消全选')

  await page.getByTestId('project-select-all').click()
  await expect(page.getByTestId(`project-select-${idA}`)).not.toBeChecked()
  await expect(page.getByTestId(`project-select-${idB}`)).not.toBeChecked()
  await expect(page.getByTestId('project-select-all')).toHaveText('全选')
  await expect(page.getByTestId('project-batch-actions')).toContainText('已选 0 项')
})

test('batch delete selected projects from sidebar', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const idA = `batch-a-${Date.now()}`
  const idB = `batch-b-${Date.now() + 1}`
  const keepId = `batch-keep-${Date.now() + 2}`

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')

  await createProject(page, idA, audioPath)
  await createProject(page, idB, audioPath)
  await createProject(page, keepId, audioPath)

  await page.getByTestId('project-multi-select-toggle').click()
  await page.getByTestId(`project-select-${idA}`).click()
  await page.getByTestId(`project-select-${idB}`).click()
  await page.getByTestId('delete-selected-projects').click()
  await page.getByLabel('仅从列表移除（保留所有文件）').click()
  await page.getByTestId('delete-project-confirm').click()

  await expect(page.getByTestId('project-list').getByText(`(${idA})`)).not.toBeVisible()
  await expect(page.getByTestId('project-list').getByText(`(${idB})`)).not.toBeVisible()
  await expect(page.getByTestId('project-list').getByText(`(${keepId})`)).toBeVisible()
})

test('bulk delete dialog keeps scope options clickable', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const ids = Array.from({ length: 12 }, (_, index) => `bulk-ui-${Date.now()}-${index}`)

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')

  for (const projectId of ids) {
    await createProject(page, projectId, audioPath)
  }

  await page.getByTestId('project-multi-select-toggle').click()
  for (const projectId of ids) {
    await page.getByTestId(`project-select-${projectId}`).click()
  }

  await page.getByTestId('delete-selected-projects').click()
  await expect(page.getByTestId('delete-project-id-list')).toBeVisible()

  const listBox = await page.getByTestId('delete-project-id-list').boundingBox()
  const scopeAll = page.getByLabel('彻底删除（含 input 与 separated）')
  const scopeBox = await scopeAll.boundingBox()

  expect(listBox).not.toBeNull()
  expect(scopeBox).not.toBeNull()
  if (listBox && scopeBox) {
    expect(scopeBox.y).toBeGreaterThan(listBox.y + listBox.height - 1)
  }

  await scopeAll.click()
  await expect(scopeAll).toBeChecked()
  await page.getByTestId('delete-project-confirm').click()

  for (const projectId of ids) {
    await expect(page.getByTestId('project-list').getByText(`(${projectId})`)).not.toBeVisible()
  }
})

test('delete project from row trash icon', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `del-row-${Date.now()}`

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)

  await page.getByTestId(`delete-project-row-${projectId}`).click()
  await page.getByLabel('仅从列表移除（保留所有文件）').click()
  await page.getByTestId('delete-project-confirm').click()

  await expect(page.getByTestId('project-list').getByText(`(${projectId})`)).not.toBeVisible()
})

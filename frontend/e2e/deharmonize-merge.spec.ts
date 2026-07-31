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
 * TC-MG-02 / P3: three-stem merge UI disables clean_instrumental when backing exists.
 */
test('merge page shows three-stem hint and omits clean_instrumental when backing present', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `deharm-${Date.now()}`

  await page.route(new RegExp(`/api/projects/${projectId}/defaults`), async (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        display_name: projectId,
        input_audio: 'input/x.flac',
        input_lrc: null,
        mix_audio: 'input/x.flac',
        vocals_path: 'output/separated/x_(Vocals)_m.flac',
        lrc_path: '',
        slice_mode: 'lrc',
        active_slice_mode: 'lrc',
        convert_mode: 'slice_batch',
        reference: 'input/x.flac',
        slices_dir: '',
        manifest: '',
        merge_vocals_file: '',
        merge_vocals_dir: '',
        merge_instrumental: 'output/separated/x_(Other)_m.flac',
        merge_reference: 'input/x.flac',
        merge_profile: 'full',
        merge_mode: 'whole_track',
        stage_status: {
          separate: 'done',
          deharmonize: 'done',
          slice: 'not_run',
          convert: 'not_run',
          merge: 'not_run',
        },
        stage_params: {
          separate: {},
          deharmonize: {},
          slice: {},
          convert: {},
          merge: { backing_gain_db: 0, include_backing: true },
        },
        wizard_params: {},
        artifacts: {
          sep_vocals: '/media/output/separated/x_(Vocals)_m.flac',
          sep_instrumental: '/media/output/separated/x_(Other)_m.flac',
          deharm_lead: '/media/output/separated/x_(Lead)_karaoke.flac',
          deharm_backing: '/media/output/separated/x_(Backing)_karaoke.flac',
          convert_full_track: null,
          convert_dir: null,
          mixed: null,
        },
      }),
    })
  })

  await page.goto('/')
  await page.waitForSelector('[data-testid="app-sidebar"]')
  await createProject(page, projectId, audioPath)
  await selectProject(page, projectId)
  await page.getByTestId('tab-merge').click()
  await page.waitForSelector('[data-testid="merge-page"]')

  await expect(page.getByTestId('merge-three-stem-hint')).toBeVisible()
  await expect(page.getByTestId('param-clean_instrumental')).toHaveCount(0)
})

test('deharmonize page renders and submits stage run', async ({ page }) => {
  const audioPath = makeFakeFlac()
  const projectId = `dh-${Date.now()}`
  let capturedBody: any = null

  await page.route(new RegExp(`/api/projects/${projectId}/defaults`), async (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        display_name: projectId,
        input_audio: 'input/x.flac',
        input_lrc: null,
        mix_audio: 'input/x.flac',
        vocals_path: 'output/separated/x_(Vocals)_m.flac',
        lrc_path: '',
        slice_mode: 'lrc',
        active_slice_mode: 'lrc',
        convert_mode: 'slice_batch',
        reference: 'input/x.flac',
        slices_dir: '',
        manifest: '',
        merge_vocals_file: '',
        merge_vocals_dir: '',
        merge_instrumental: '',
        merge_reference: 'input/x.flac',
        merge_profile: 'full',
        merge_mode: 'whole_track',
        stage_status: {
          separate: 'done',
          deharmonize: 'not_run',
          slice: 'not_run',
          convert: 'not_run',
          merge: 'not_run',
        },
        stage_params: {
          separate: {},
          deharmonize: { model: 'mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt' },
          slice: {},
          convert: {},
          merge: {},
        },
        wizard_params: {},
        artifacts: {
          sep_vocals: null,
          sep_instrumental: null,
          deharm_lead: null,
          deharm_backing: null,
          convert_full_track: null,
          convert_dir: null,
          mixed: null,
        },
      }),
    })
  })

  await page.route(/\/api\/params\/schema\?stage=deharmonize/, async (route) => {
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        stage: 'deharmonize',
        params: [
          {
            key: 'model',
            label: 'Karaoke 模型',
            description: 'test',
            param_type: 'choice',
            default: 'mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt',
            choices: ['mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt'],
            minimum: null,
            maximum: null,
            step: null,
            wizard: true,
            vad_only: false,
            lrc_only: false,
            slice_batch_only: false,
            full_track_only: false,
          },
        ],
        sections: [],
      }),
    })
  })

  await page.route(new RegExp(`/api/projects/${projectId}/stages/deharmonize/run`), async (route) => {
    capturedBody = route.request().postDataJSON()
    const sse =
      'event: log\ndata: {"project_id":"' +
      projectId +
      '","stage":"deharmonize","job_id":"job-dh","percent":100,"message":"done","log_line":"done"}\n\n' +
      'event: done\ndata: {"success":true,"error":null,"artifacts":{"lead_vocals":"output/separated/x_(Lead)_k.flac","backing_vocals":"output/separated/x_(Backing)_k.flac"}}\n\n'
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
  await page.getByTestId('tab-deharmonize').click()
  await page.waitForSelector('[data-testid="deharmonize-page"]')
  await page.getByTestId('stage-run-submit').click()
  await expect.poll(() => capturedBody).toBeTruthy()
  expect(capturedBody.params.model).toBeTruthy()
})

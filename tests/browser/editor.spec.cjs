const { test, expect } = require('@playwright/test');

async function mount(page) {
  await page.goto('/');
  await page.evaluate(async () => {
    await customElements.whenDefined('sunriser-dayplan-card');
    window.writes = [];
    window.failSave = false;
    const markers = [{ time: '00:00', percent: 0 }, { time: '12:00', percent: 80 }, { time: '24:00', percent: 0 }];
    window.snapshot = {
      weekday: 4,
      channels: [{ pwm: 1, name: 'Tank light', manager: 2, markers, daily: [{ time: '06:00', percent: 10 }], week: [0, 1, 1, 1, 1, 1, 0, 1], program_name: 'Daylight', daily_revision: 'daily-rev', week_revision: 'week-rev' }],
      programs: [{ id: 1, name: 'Daylight', markers, revision: 'program-rev', channels: ['Tank light', 'Second light'] }],
    };
    const card = document.createElement('sunriser-dayplan-card');
    card.setConfig({ device_id: 'controller-one' });
    document.body.append(card);
    card.hass = { connection: { async sendMessagePromise(request) {
      if (request.service === 'save_planning') {
        window.writes.push(request.service_data);
        if (window.failSave) throw new Error('Schedule changed on the controller');
        return {};
      }
      return { response: structuredClone(window.snapshot) };
    } } };
  });
  await expect(page.getByText('Weekly planner — Daylight')).toBeVisible();
}

test('table edits preview locally, reject duplicates, save and preserve failed drafts', async ({ page }, testInfo) => {
  await mount(page);
  await page.getByRole('button', { name: 'Edit daily curve' }).click();
  await page.getByRole('spinbutton', { name: 'Percent 1', exact: true }).fill('65');
  await page.getByRole('spinbutton', { name: 'Percent 1', exact: true }).press('Tab');
  await expect(page.getByLabel('Draft preview')).toBeVisible();
  expect(await page.evaluate(() => window.writes.length)).toBe(0);
  await page.screenshot({ path: testInfo.outputPath('editor-desktop.png'), fullPage: true });
  await page.getByRole('button', { name: 'Add marker' }).click();
  await page.getByLabel('Time 2', { exact: true }).fill('06:00');
  await page.getByLabel('Time 2', { exact: true }).press('Tab');
  await expect(page.getByRole('button', { name: 'Save', exact: true })).toBeDisabled();
  await page.getByLabel('Time 2', { exact: true }).fill('24:00');
  await page.getByLabel('Time 2', { exact: true }).press('Tab');
  await page.evaluate(() => { window.failSave = true; });
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('Schedule changed');
  await expect(page.getByRole('spinbutton', { name: 'Percent 1', exact: true })).toHaveValue('65');
  await page.evaluate(() => { window.failSave = false; });
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(page.getByLabel('Schedule editor')).toHaveCount(0);
  const writes = await page.evaluate(() => window.writes);
  expect(writes[1]).toMatchObject({ device_id: 'controller-one', kind: 'daily', target: 1, revision: 'daily-rev', markers: [{ time: '06:00', percent: 65 }, { time: '24:00', percent: 0 }] });
});

test('discard reloads external changes before reopening a draft', async ({ page }) => {
  await mount(page);
  await page.getByRole('button', { name: 'Edit daily curve' }).click();
  await page.evaluate(() => {
    window.snapshot.channels[0].daily = [{ time: '09:00', percent: 25 }];
    window.snapshot.channels[0].daily_revision = 'external-rev';
  });
  await page.getByRole('button', { name: 'Discard' }).click();
  await page.getByRole('button', { name: 'Edit daily curve' }).click();
  await expect(page.getByLabel('Time 1', { exact: true })).toHaveValue('09:00');
  await expect(page.getByLabel('Percent 1', { exact: true })).toHaveValue('25');
  expect(await page.evaluate(() => window.writes.length)).toBe(0);
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  expect(await page.evaluate(() => window.writes[0].revision)).toBe('external-rev');
});

test('shared program warning and named weekly choices work on a narrow screen', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mount(page);
  await page.getByText('Named programs', { exact: true }).click();
  await page.getByRole('button', { name: 'Edit program' }).click();
  await expect(page.getByText('This is a shared program.', { exact: false })).toContainText('Second light');
  await page.screenshot({ path: testInfo.outputPath('editor-mobile.png'), fullPage: true });
  await page.getByRole('button', { name: 'Discard' }).click();
  await page.getByRole('button', { name: 'Edit week' }).click();
  await page.getByLabel('Sunday', { exact: true }).selectOption('1');
  await page.getByRole('button', { name: 'Save', exact: true }).click();
  const writes = await page.evaluate(() => window.writes);
  expect(writes[0]).toMatchObject({ kind: 'week', revision: 'week-rev', schedule: [1, 1, 1, 1, 1, 1, 0, 1] });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

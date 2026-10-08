const { test, expect } = require('@playwright/test');

async function mount(page) {
  await page.goto('/');
  await page.evaluate(async () => {
    await customElements.whenDefined('sunriser-dayplan-card');
    window.requests = [];
    const daily = [{ time: '06:00', percent: 0 }, { time: '12:00', percent: 80 }, { time: '22:00', percent: 0 }];
    const weekly = [{ time: '00:00', percent: 0 }, { time: '18:00', percent: 30 }, { time: '24:00', percent: 0 }];
    window.snapshot = {
      weekday: 4,
      channels: Array.from({ length: 8 }, (_, i) => ({
        pwm: i + 1, name: i === 0 ? 'Royal Blue' : `Tank channel ${i + 1}`,
        manager: i === 0 ? 2 : i === 6 ? 3 : i === 7 ? 0 : 1,
        markers: i === 0 ? weekly : i >= 6 ? [] : daily,
        program_name: i === 0 ? 'Moon weekdays' : null, fixed: 500,
      })),
    };
    const card = document.createElement('sunriser-dayplan-card');
    card.setConfig({ device_id: 'controller-one' });
    document.body.append(card);
    card.hass = { connection: { async sendMessagePromise(request) {
      window.requests.push(request);
      if (request.service !== 'get_planning') throw new Error('Unexpected write action');
      return { response: structuredClone(window.snapshot) };
    } } };
  });
  await expect(page.getByText('Royal Blue', { exact: true })).toBeVisible();
}

test('daily and weekly curves remain visible without editing controls', async ({ page }) => {
  await mount(page);
  const weekly = page.getByLabel('Royal Blue: Weekly planner — Moon weekdays', { exact: true });
  await expect(weekly).toHaveAttribute('title', 'Royal Blue: Weekly planner — Moon weekdays');
  await expect(page.locator('svg path[fill="none"]')).toHaveCount(6);
  await expect(page.locator('svg path[fill="none"]').first()).toHaveAttribute('d', /1080,70/);
  await expect(page.locator('svg path[fill="none"]').nth(1)).toHaveAttribute('d', /720,20/);
  await expect(page.getByLabel('Tank channel 7: Fixed output: 50%', { exact: true })).toBeVisible();
  await expect(page.locator('button, input, select, table, details')).toHaveCount(0);
  const requests = await page.evaluate(() => window.requests);
  expect(requests).toHaveLength(1);
  expect(requests[0]).toMatchObject({ service: 'get_planning', service_data: { device_id: 'controller-one' } });
});

test('eight-channel graph stays compact on a narrow dashboard', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 350, height: 700 });
  await mount(page);
  const card = await page.locator('ha-card').boundingBox();
  expect(card.height).toBeLessThan(400);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: testInfo.outputPath('compact-graph.png'), fullPage: true });
});

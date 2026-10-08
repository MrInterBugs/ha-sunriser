const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function loadCard() {
  let Card;
  const timers = new Map();
  let nextTimer = 0;
  const context = {
    LitElement: class {
      constructor() { this.isConnected = false; }
      connectedCallback() { this.isConnected = true; }
      disconnectedCallback() { this.isConnected = false; }
      requestUpdate() {}
    },
    html: () => '', css: () => '', unsafeSVG: value => value,
    customElements: { define(name, element) { Card = element; } },
    window: { dispatchEvent() {} }, Event: class {},
    console: { error() {} },
    setInterval(fn, delay) { timers.set(++nextTimer, { fn, delay }); return nextTimer; },
    clearInterval(id) { timers.delete(id); },
  };
  const source = fs.readFileSync(path.join(__dirname, '../../custom_components/sunriser/www/sunriser-dayplan-card.js'), 'utf8')
    .replace(/^import .*;$/gm, '');
  vm.runInNewContext(source, context);
  return { card: new Card(), timers };
}
const response = name => ({ response: { name, markers: [{ time: '12:00', percent: 50 }] } });
const flush = async () => { for (let i = 0; i < 30; i++) await Promise.resolve(); };

test('changing controller discards pending old responses and never mixes devices', async () => {
  const { card } = loadCard();
  const calls = [];
  let release;
  card.setConfig({ device_id: 'old' });
  card.hass = { connection: { sendMessagePromise(request) {
    calls.push(request.service_data.device_id);
    if (calls.length === 1) return new Promise(resolve => { release = resolve; });
    return Promise.resolve(response(request.service_data.device_id));
  } } };
  card.setConfig({ device_id: 'new' });
  await flush();
  release(response('old'));
  await flush();
  assert.equal(card._schedules.length, 10);
  assert.ok(card._schedules.every(schedule => schedule.name === 'new'));
  assert.equal(calls.filter(device => device === 'old').length, 1);
});

test('overlapping timer refreshes do not start duplicate requests', async () => {
  const { card } = loadCard();
  let count = 0;
  let release;
  card.hass = { connection: { sendMessagePromise() {
    count++;
    return new Promise(resolve => { release = resolve; });
  } } };
  card._fetch();
  card._fetch();
  assert.equal(count, 1);
  card.disconnectedCallback();
  release(response('old'));
  await flush();
});

test('disconnected card cannot publish an old response or keep fetching', async () => {
  const { card, timers } = loadCard();
  let release;
  let count = 0;
  card.connectedCallback();
  card.hass = { connection: { sendMessagePromise() {
    count++;
    return count === 1 ? new Promise(resolve => { release = resolve; }) : Promise.resolve(response('old'));
  } } };
  card.disconnectedCallback();
  release(response('old'));
  await flush();
  assert.equal(count, 1);
  assert.equal(card._schedules, null);
  assert.equal(timers.size, 0);
});

test('configuration changes reschedule a single timer', () => {
  const { card, timers } = loadCard();
  card.setConfig({ refresh_interval: 60 });
  card.connectedCallback();
  card.setConfig({ refresh_interval: 15 });
  assert.equal(timers.size, 1);
  assert.equal([...timers.values()][0].delay, 15000);
});

test('invalid intervals cannot create a tight refresh loop', () => {
  for (const refresh_interval of [0, -1, 'bad', Infinity]) {
    const { card, timers } = loadCard();
    card.setConfig({ refresh_interval });
    card.connectedCallback();
    assert.equal([...timers.values()][0].delay, 300000);
  }
});

test('reconnecting refreshes immediately', async () => {
  const { card } = loadCard();
  let count = 0;
  card.hass = { connection: { sendMessagePromise() {
    count++;
    return Promise.resolve(response('current'));
  } } };
  await flush();
  assert.equal(count, 10);
  card.disconnectedCallback();
  card.connectedCallback();
  await flush();
  assert.equal(count, 20);
});

test('a rejected response from the previous controller cannot replace the new result', async () => {
  const { card } = loadCard();
  let rejectOld;
  card.setConfig({ device_id: 'old' });
  card.hass = { connection: { sendMessagePromise(request) {
    if (request.service_data.device_id === 'old') return new Promise((resolve, reject) => { rejectOld = reject; });
    return Promise.resolve(response('new'));
  } } };
  card.setConfig({ device_id: 'new' });
  await flush();
  rejectOld(new Error('Old controller offline'));
  await flush();
  assert.equal(card._error, null);
  assert.ok(card._schedules.every(schedule => schedule.name === 'new'));
  assert.equal(card._loading, false);
});

test('request failures are displayed and a later refresh can recover', async () => {
  const { card } = loadCard();
  card.hass = { connection: { sendMessagePromise() { return Promise.reject(new Error('Controller offline')); } } };
  await flush();
  assert.equal(card._error, 'Controller offline');
  assert.equal(card._loading, false);
  card._hass.connection.sendMessagePromise = () => Promise.resolve(response('recovered'));
  await card._fetch();
  assert.equal(card._error, null);
  assert.equal(card._schedules.length, 10);
});

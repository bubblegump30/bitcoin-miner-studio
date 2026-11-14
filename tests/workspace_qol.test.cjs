const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');
const vm = require('node:vm');

const script = fs.readFileSync(path.join(__dirname, '../ui/script.js'), 'utf8');
const region = (start, end) => script.slice(script.indexOf(start), script.indexOf(end));

function deferred() {
  let resolve;
  const promise = new Promise(done => { resolve = done; });
  return { promise, resolve };
}

test('manual refresh joins an active poll and reports its outcome', async () => {
  const request = deferred();
  const buttons = { '#refreshBtn': {}, '#logsRefresh': {} };
  const toasts = [];
  let reads = 0;
  const context = vm.createContext({
    apiReady: true, stateRefreshRequest: null, bridgeAvailable: () => true,
    callApi: () => { reads++; return request.promise; },
    renderState: () => {}, $: id => buttons[id], showToast: message => toasts.push(message),
  });
  vm.runInContext(region('function refreshState(){', 'function syncMiningControls(){'), context);
  const poll = context.refreshState();
  const click = context.manualStateRefresh();
  assert.equal(buttons['#refreshBtn'].disabled, true);
  request.resolve({});
  await Promise.all([poll, click]);
  assert.equal(reads, 1);
  assert.deepEqual(toasts, ['App state refreshed']);
  assert.equal(buttons['#refreshBtn'].disabled, false);
});

test('pool and dashboard controls share one pending mining command', async () => {
  const start = deferred();
  const stalePoll = deferred();
  const elements = Object.fromEntries(
    ['#enginePrimary', '#quickMining', '#poolStart', '#poolStop', '#poolReset'].map(id => [id, {}]),
  );
  const calls = [];
  const context = vm.createContext({
    apiReady: true, lastState: { miner_running: false }, miningActionPending: false,
    securityTrusted: true, stateRefreshRequest: stalePoll.promise,
    $: id => elements[id], poolPayload: () => ({}), handleResult: promise => promise,
    callApi: method => { calls.push(method); return start.promise; },
    refreshState: () => { calls.push('refresh'); context.lastState = { miner_running: true }; },
  });
  vm.runInContext(region('function syncMiningControls(){', 'function scheduleStateRefresh('), context);
  const first = context.runMiningAction('start');
  await context.runMiningAction('start');
  context.syncMiningControls();
  assert.ok(Object.values(elements).every(button => button.disabled));
  start.resolve({ ok: true });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(calls, ['start_mining']);
  stalePoll.resolve();
  await first;
  assert.deepEqual(calls, ['start_mining', 'refresh']);
  assert.equal(elements['#poolStop'].disabled, false);
  assert.equal(elements['#poolStart'].disabled, true);
});

test('rapid range changes render only the latest monitoring response', async () => {
  const requests = [];
  const rendered = [];
  const context = vm.createContext({
    apiReady: true, analyticsRangeSeconds: 3600, analyticsLastFetch: 0,
    analyticsRequest: null, analyticsRefreshQueued: false, bridgeAvailable: () => true,
    callApi: (_method, range) => {
      const request = deferred();
      requests.push({ range, ...request });
      return request.promise;
    },
    renderAnalytics: result => rendered.push(result.range),
  });
  vm.runInContext(region('function refreshAnalytics(', 'function releaseAreaState('), context);
  const first = context.refreshAnalytics(true);
  context.analyticsRangeSeconds = 21600;
  context.refreshAnalytics(true);
  context.analyticsRangeSeconds = 86400;
  context.refreshAnalytics(true);
  requests[0].resolve({ ok: true, range: 3600 });
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(requests.map(request => request.range), [3600, 86400]);
  assert.deepEqual(rendered, []);
  requests[1].resolve({ ok: true, range: 86400 });
  await first;
  assert.deepEqual(rendered, [86400]);
});

// Offline regression test for the Google Apps Script integration (no Google account required).
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '..', 'integrations', 'google-apps-script', 'Code.gs'), 'utf8');

function harness(rows, props = {MAPLE_API_BASE_URL: 'https://maple.example.com', MAPLE_ADMIN_TOKEN: 'test-only'}) {
  const requests = [];
  let unlocked = false;
  const sheet = {
    getLastRow: () => rows.length + 1,
    getRange: (r, c, height) => ({
      getValues: () => r === 1
        ? [['아이템명', '가격', '전송(TRUE)', '메모'].slice(0, height === 1 ? 4 : 3)]
        : rows.slice(r - 2, r - 2 + height)
    })
  };
  const sandbox = {
    SpreadsheetApp: {
      getActiveSpreadsheet: () => ({getSheetByName: () => sheet}),
    },
    PropertiesService: {getScriptProperties: () => ({getProperty: key => props[key]})},
    LockService: {getScriptLock: () => ({tryLock: () => true, releaseLock: () => {unlocked = true;}})},
    UrlFetchApp: {fetch: (url, options) => {
      requests.push({url, options});
      const data = options.method === 'get'
        ? [{item_name: '광석', price_locked: false}, {item_name: '고정가', price_locked: true}]
        : {updated: JSON.parse(options.payload).prices};
      return {getResponseCode: () => 200, getContentText: () => JSON.stringify(data)};
    }},
    console
  };
  vm.createContext(sandbox);
  vm.runInContext(source, sandbox);
  return {sandbox, requests, wasUnlocked: () => unlocked};
}

const ok = harness([['광석', 150, true], ['무시', 3, false]]);
assert.equal(ok.sandbox.syncMaplePrices().updated, 1);
assert.equal(ok.requests.length, 2);
assert.equal(ok.requests[0].options.method, 'get');
assert.equal(ok.requests[1].options.method, 'patch');
assert.equal(ok.requests[1].options.headers['X-Admin-Token'], 'test-only');
assert.equal(JSON.parse(ok.requests[1].options.payload).prices[0].price, 150);
assert.equal(ok.wasUnlocked(), true);

const invalid = harness([['광석', -1, true]]);
assert.throws(() => invalid.sandbox.syncMaplePrices(), /정수/);
assert.equal(invalid.requests.length, 0);
assert.equal(invalid.wasUnlocked(), true);

const duplicate = harness([['광석', 1, true], ['광석', 2, true]]);
assert.throws(() => duplicate.sandbox.syncMaplePrices(), /중복/);
assert.equal(duplicate.requests.length, 0);

const locked = harness([['고정가', 1, true]]);
assert.throws(() => locked.sandbox.syncMaplePrices(), /카탈로그/);
assert.equal(locked.requests.length, 1);

const missingToken = harness([['광석', 1, true]], {MAPLE_API_BASE_URL: 'https://maple.example.com'});
assert.throws(() => missingToken.sandbox.syncMaplePrices(), /MAPLE_ADMIN_TOKEN/);
assert.equal(missingToken.requests.length, 0);

console.log('Maple GAS bridge tests passed');

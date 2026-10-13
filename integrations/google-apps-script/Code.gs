/**
 * Maple Craft Analytics -> Google Sheets price entry bridge.
 * Bind this script to a spreadsheet. Secrets belong only in Script Properties.
 * This is a manual, opt-in bridge; it never publishes the admin token to cells.
 */
const MAPLE_SHEET = '시세입력';
const MAPLE_COLUMNS = ['아이템명', '가격', '전송(TRUE)', '메모'];
const MAPLE_MAX_UPDATES = 500; // Existing FastAPI request schema limit.

function onOpen() {
  SpreadsheetApp.getUi().createMenu('Maple 시세')
    .addItem('입력 시트 준비', 'setupMaplePriceSheet')
    .addItem('전송 미리보기', 'previewMaplePrices')
    .addItem('검증 후 시세 전송', 'syncMaplePricesFromMenu')
    .addToUi();
}

function setupMaplePriceSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const oldSheet = ss.getSheetByName(MAPLE_SHEET);
  const sheet = oldSheet || ss.insertSheet(MAPLE_SHEET);
  const header = sheet.getRange(1, 1, 1, MAPLE_COLUMNS.length);
  const existing = header.getValues()[0];
  if (existing.some(value => String(value).trim() !== '') &&
      MAPLE_COLUMNS.some((value, index) => existing[index] !== value)) {
    throw new Error('기존 첫 행에 데이터가 있습니다. 덮어쓰지 않고 중단합니다.');
  }
  header.setValues([MAPLE_COLUMNS]).setFontWeight('bold');
  sheet.setFrozenRows(1);
  // Only insert checkboxes in a newly created sheet: rerunning setup must not
  // reset existing checkmarks or user-entered data.
  if (!oldSheet) sheet.getRange('C2:C1000').insertCheckboxes();
  return sheet.getName();
}

function collectMaplePrices_(sheet) {
  if (!sheet) throw new Error('시세입력 시트가 없습니다. 먼저 입력 시트를 준비하세요.');
  const header = sheet.getRange(1, 1, 1, 3).getValues()[0];
  if (header[0] !== MAPLE_COLUMNS[0] || header[1] !== MAPLE_COLUMNS[1] ||
      header[2] !== MAPLE_COLUMNS[2]) {
    throw new Error('시세입력 시트의 열 구성이 다릅니다.');
  }
  const lastRow = sheet.getLastRow();
  if (lastRow < 2) return [];
  const rows = sheet.getRange(2, 1, lastRow - 1, 3).getValues();
  const entries = [];
  const names = new Set();
  rows.forEach((row, index) => {
    if (row[2] !== true) return; // Only explicitly checked rows are sent.
    const line = index + 2;
    const name = String(row[0] || '').trim();
    const rawPrice = row[1];
    if (!name || name.length > 255) throw new Error(line + '행: 아이템명이 올바르지 않습니다.');
    if (rawPrice === '' || rawPrice === null ||
        typeof rawPrice === 'boolean' || !Number.isSafeInteger(Number(rawPrice)) ||
        Number(rawPrice) < 0) throw new Error(line + '행: 가격은 0 이상의 정수여야 합니다.');
    if (names.has(name)) throw new Error(line + '행: 중복 아이템명 ' + name);
    names.add(name);
    entries.push({item_name: name, price: Number(rawPrice)});
  });
  if (entries.length > MAPLE_MAX_UPDATES) {
    throw new Error('한 번에 최대 ' + MAPLE_MAX_UPDATES + '개까지만 전송할 수 있습니다.');
  }
  return entries;
}

function mapleConfig_() {
  const props = PropertiesService.getScriptProperties();
  const base = String(props.getProperty('MAPLE_API_BASE_URL') || '').trim().replace(/\/+$/, '');
  const token = String(props.getProperty('MAPLE_ADMIN_TOKEN') || '').trim();
  if (!/^https:\/\/[^\s/]+(?:\/[\w./-]+)?$/.test(base)) {
    throw new Error('Script Properties의 MAPLE_API_BASE_URL을 공개 HTTPS 서버 주소로 설정하세요.');
  }
  if (!token) throw new Error('Script Properties의 MAPLE_ADMIN_TOKEN이 필요합니다.');
  return {base: base, token: token};
}

function mapleRequest_(url, method, token, body) {
  const options = {
    method: method,
    headers: {'X-Admin-Token': token, 'Accept': 'application/json'},
    muteHttpExceptions: true,
    followRedirects: false
  };
  if (body !== undefined) {
    options.contentType = 'application/json';
    options.payload = JSON.stringify(body);
  }
  const response = UrlFetchApp.fetch(url, options);
  const status = response.getResponseCode();
  if (status < 200 || status >= 300) {
    throw new Error('Maple API ' + status + ': ' + response.getContentText().slice(0, 300));
  }
  return JSON.parse(response.getContentText());
}

function validateMapleCatalog_(entries, cfg) {
  const available = mapleRequest_(cfg.base + '/api/market-prices', 'get', cfg.token);
  if (!Array.isArray(available)) throw new Error('Maple API가 올바른 시세 목록을 반환하지 않았습니다.');
  const allowed = new Set(available.filter(row => !row.price_locked).map(row => row.item_name));
  const invalid = entries.filter(row => !allowed.has(row.item_name));
  if (invalid.length) {
    throw new Error('카탈로그에 없거나 고정가인 아이템: ' +
      invalid.slice(0, 5).map(row => row.item_name).join(', '));
  }
}

function previewMaplePrices() {
  const entries = collectMaplePrices_(SpreadsheetApp.getActiveSpreadsheet().getSheetByName(MAPLE_SHEET));
  const message = '전송 체크된 시세 ' + entries.length + '개\n' +
    entries.slice(0, 10).map(row => row.item_name + ': ' + row.price).join('\n') +
    (entries.length > 10 ? '\n...' : '');
  SpreadsheetApp.getUi().alert(message);
  return entries.length;
}

function syncMaplePrices() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(10000)) throw new Error('다른 시세 전송이 진행 중입니다.');
  try {
    const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(MAPLE_SHEET);
    const entries = collectMaplePrices_(sheet);
    if (!entries.length) return {updated: 0};
    const cfg = mapleConfig_();
    validateMapleCatalog_(entries, cfg); // Reject the whole batch before writing.
    const result = mapleRequest_(cfg.base + '/api/market-prices/bulk', 'patch',
      cfg.token, {prices: entries});
    if (!result || !Array.isArray(result.updated) || result.updated.length !== entries.length) {
      throw new Error('서버의 갱신 결과 개수가 일치하지 않습니다. 서버에서 실제 값을 확인하세요.');
    }
    console.log('Maple price sync completed: ' + entries.length);
    return {updated: entries.length};
  } finally {
    lock.releaseLock();
  }
}

function syncMaplePricesFromMenu() {
  const result = syncMaplePrices();
  SpreadsheetApp.getUi().alert('Maple 시세 ' + result.updated + '개 전송 완료');
}

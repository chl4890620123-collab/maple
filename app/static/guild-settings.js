const GUILD_DISCOUNT_STORAGE_KEY = "maple_guild_discount_enabled_v1";
const GUILD_DISCOUNT_RATE_STORAGE_KEY = "maple_guild_discount_rate_percent_v1";
let loadedFixedShopRate = null;

function readGuildDiscountPreference() {
  const stored = localStorage.getItem(GUILD_DISCOUNT_STORAGE_KEY);
  if (stored === null) {
    return Boolean(state.gameRules?.default_guild_discount_enabled ?? true);
  }
  return stored === "true";
}

function defaultGuildDiscountRatePercent() {
  const rate = Number(state.gameRules?.guild_shop_discount_rate ?? 0.04) * 100;
  return Number.isFinite(rate) ? Math.min(100, Math.max(0, rate)) : 4;
}

function readGuildDiscountRatePercent() {
  const stored = Number(localStorage.getItem(GUILD_DISCOUNT_RATE_STORAGE_KEY));
  if (Number.isFinite(stored) && stored >= 0 && stored <= 100) return stored;
  return defaultGuildDiscountRatePercent();
}

function guildDiscountEnabled() {
  const control = document.querySelector("#guildDiscount");
  return control ? control.checked : readGuildDiscountPreference();
}

function guildDiscountRatePercent() {
  const control = document.querySelector("#guildDiscountRate");
  const value = control ? Number(control.value) : readGuildDiscountRatePercent();
  if (!Number.isFinite(value)) return defaultGuildDiscountRatePercent();
  return Math.min(100, Math.max(0, value));
}

function guildDiscountRate() {
  return guildDiscountRatePercent() / 100;
}

function displayGuildDiscountRate() {
  return String(Number(guildDiscountRatePercent().toFixed(2)));
}

async function refreshFixedShopPricesForGuildRate() {
  const rate = guildDiscountRate();
  const cacheKey = rate.toFixed(6);
  if (loadedFixedShopRate === cacheKey) return;
  const params = new URLSearchParams({ guild_discount_rate: String(rate) });
  state.fixedShopPrices = await api(`/api/meister/fixed-shop-prices?${params}`);
  loadedFixedShopRate = cacheKey;
  renderFixedShopPrices();
}

function installGuildDiscountControl() {
  if (document.querySelector("#guildDiscount")) return;
  const grid = document.querySelector(".meister-filter-grid");
  if (!grid) return;

  const toggle = document.createElement("label");
  toggle.className = "toggle-field";
  toggle.innerHTML = `
    <input id="guildDiscount" type="checkbox" />
    <span id="guildDiscountLabel">길드 상점 할인 적용</span>
  `;

  const rateField = document.createElement("div");
  rateField.className = "search-field guild-rate-field";
  rateField.innerHTML = `
    <label for="guildDiscountRate">길드 할인율 (%)</label>
    <input id="guildDiscountRate" type="number" min="0" max="100" step="0.1" inputmode="decimal" />
  `;

  const refresh = document.querySelector("#refresh");
  grid.insertBefore(toggle, refresh || null);
  grid.insertBefore(rateField, refresh || null);

  const enabledControl = toggle.querySelector("#guildDiscount");
  const rateControl = rateField.querySelector("#guildDiscountRate");
  enabledControl.checked = readGuildDiscountPreference();
  rateControl.value = String(readGuildDiscountRatePercent());

  enabledControl.addEventListener("change", async () => {
    localStorage.setItem(GUILD_DISCOUNT_STORAGE_KEY, String(enabledControl.checked));
    await loadCalculations();
    toast(enabledControl.checked ? `길드 상점 ${displayGuildDiscountRate()}% 할인을 적용합니다.` : "길드 상점 할인을 제외합니다.");
  });

  rateControl.addEventListener("change", async () => {
    const rate = guildDiscountRatePercent();
    rateControl.value = String(rate);
    localStorage.setItem(GUILD_DISCOUNT_RATE_STORAGE_KEY, String(rate));
    loadedFixedShopRate = null;
    await loadCalculations();
    toast(`길드 할인율을 ${displayGuildDiscountRate()}%로 저장했습니다.`);
  });
}

loadCalculations = async function loadCalculationsWithGuildSetting() {
  state.feeRate = Number($("#feeRate").value);
  const guildDiscount = guildDiscountEnabled();
  const rate = guildDiscountRate();
  state.gameRules = {
    ...(state.gameRules || {}),
    guild_shop_discount_rate: rate,
  };
  const params = new URLSearchParams({
    fee_rate: String(state.feeRate),
    guild_discount: String(guildDiscount),
    guild_discount_rate: String(rate),
  });
  if (state.categoryKey) params.set("category_key", state.categoryKey);
  state.calculations = await api(`/api/meister/calculations?${params}`);
  renderCalculations();
  updateGuildSettingLabels();
  refreshFixedShopPricesForGuildRate().catch((error) => console.warn("fixed shop refresh failed", error));
};

function updateGuildDialogLabels() {
  const guildText = `길드 ${displayGuildDiscountRate()}%`;
  document.querySelectorAll("#recipeDialogBody .badge.fixed").forEach((badge) => {
    const next = badge.textContent.replace(/길드\s+[\d.]+%/, guildText);
    if (next !== badge.textContent) badge.textContent = next;
  });
}

function updateGuildSettingLabels() {
  const enabled = guildDiscountEnabled();
  const guildRate = displayGuildDiscountRate();
  const toggleLabel = document.querySelector("#guildDiscountLabel");
  if (toggleLabel) toggleLabel.textContent = `길드 상점 ${guildRate}% 적용`;

  const summary = document.querySelector("#summaryCards");
  const hints = summary?.querySelectorAll(".metric .hint");
  if (hints?.length) {
    hints[hints.length - 1].textContent = `이 브라우저에 저장 · 길드 할인 ${enabled ? `${guildRate}% 적용` : "미적용"}`;
  }

  const fixedRuleSummary = document.querySelector("#fixedRuleSummary");
  if (fixedRuleSummary) {
    fixedRuleSummary.textContent = fixedRuleSummary.textContent.replace(/길드 장사꾼 [\d.]+%/, `길드 장사꾼 ${guildRate}%`);
  }
  const fixedShopHelp = document.querySelector(".fixed-shop-card summary small");
  if (fixedShopHelp) {
    fixedShopHelp.textContent = `길드 장사꾼 ${guildRate}%는 계산 설정에서 변경 가능 · 기본 가격 수정 불가`;
  }
  updateGuildDialogLabels();
}

installGuildDiscountControl();
const summary = document.querySelector("#summaryCards");
if (summary) {
  const observer = new MutationObserver(updateGuildSettingLabels);
  observer.observe(summary, { childList: true, subtree: true });
}
const recipeDialogBody = document.querySelector("#recipeDialogBody");
if (recipeDialogBody) {
  const dialogObserver = new MutationObserver(updateGuildDialogLabels);
  dialogObserver.observe(recipeDialogBody, { childList: true, subtree: true });
}
updateGuildSettingLabels();

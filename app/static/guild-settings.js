const GUILD_DISCOUNT_STORAGE_KEY = "maple_guild_discount_enabled_v1";

function readGuildDiscountPreference() {
  const stored = localStorage.getItem(GUILD_DISCOUNT_STORAGE_KEY);
  if (stored === null) {
    return Boolean(state.gameRules?.default_guild_discount_enabled ?? true);
  }
  return stored === "true";
}

function guildDiscountEnabled() {
  const control = document.querySelector("#guildDiscount");
  return control ? control.checked : readGuildDiscountPreference();
}

function installGuildDiscountControl() {
  if (document.querySelector("#guildDiscount")) return;
  const grid = document.querySelector(".meister-filter-grid");
  if (!grid) return;

  const label = document.createElement("label");
  label.className = "toggle-field";
  label.innerHTML = `
    <input id="guildDiscount" type="checkbox" />
    <span>길드 상점 4% 적용</span>
  `;
  const refresh = document.querySelector("#refresh");
  grid.insertBefore(label, refresh || null);

  const control = label.querySelector("#guildDiscount");
  control.checked = readGuildDiscountPreference();
  control.addEventListener("change", async () => {
    localStorage.setItem(GUILD_DISCOUNT_STORAGE_KEY, String(control.checked));
    await loadCalculations();
    toast(control.checked ? "길드 상점 4% 할인을 적용합니다." : "길드 상점 할인을 제외합니다.");
  });
}

loadCalculations = async function loadCalculationsWithGuildSetting() {
  state.feeRate = Number($("#feeRate").value);
  const guildDiscount = guildDiscountEnabled();
  const params = new URLSearchParams({
    fee_rate: String(state.feeRate),
    guild_discount: String(guildDiscount),
  });
  if (state.categoryKey) params.set("category_key", state.categoryKey);
  state.calculations = await api(`/api/meister/calculations?${params}`);
  renderCalculations();
};

function updateGuildSettingLabels() {
  const enabled = guildDiscountEnabled();
  const guildRate = Math.round(Number(state.gameRules?.guild_shop_discount_rate || 0.04) * 100);
  const summary = document.querySelector("#summaryCards");
  const hints = summary?.querySelectorAll(".metric .hint");
  if (hints?.length) {
    hints[hints.length - 1].textContent = `이 브라우저에 저장 · 길드 할인 ${enabled ? `${guildRate}% 적용` : "미적용"}`;
  }
}

installGuildDiscountControl();
const summary = document.querySelector("#summaryCards");
if (summary) {
  const observer = new MutationObserver(updateGuildSettingLabels);
  observer.observe(summary, { childList: true, subtree: true });
}
updateGuildSettingLabels();

const state = {
  categories: [],
  meta: null,
  gameRules: null,
  fixedShopPrices: [],
  calculations: [],
  marketPrices: [],
  feeRate: 0.05,
  categoryKey: "",
  priceCategoryKey: "",
  dirtyPrices: new Map(),
  action: null,
  writeProtected: false,
};

const $ = (selector) => document.querySelector(selector);
const money = (value) => value === null || value === undefined ? "-" : Math.round(Number(value || 0)).toLocaleString("ko-KR");
const pct = (value) => value === null || value === undefined ? "-" : `${Number(value).toFixed(1)}%`;
const token = () => sessionStorage.getItem("maple_admin_token") || "";
const headers = (write) => {
  const result = { "Content-Type": "application/json" };
  if (write) result["X-Admin-Token"] = token();
  return result;
};
const esc = (value) => String(value ?? "").replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
}[char]));
const enc = (value) => encodeURIComponent(String(value));
const dec = (value) => decodeURIComponent(String(value));

function toast(message) {
  const element = document.createElement("div");
  element.className = "toast";
  element.textContent = message;
  document.body.appendChild(element);
  setTimeout(() => element.remove(), 2400);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try { message = (await response.json()).detail || message; } catch {}
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return response.json();
}

function categoryName(key) {
  return state.categories.find((category) => category.key === key)?.name || "전체";
}

function activateTab(name) {
  document.querySelectorAll(".tabs button").forEach((button) => button.classList.toggle("active", button.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === name));
  if (name === "prices") loadPrices();
  if (name === "records") loadRecords();
}

function activateTabs() {
  document.querySelectorAll(".tabs button").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tab));
  });
}

async function checkHealth() {
  try {
    await api("/api/health");
    $("#healthBadge").textContent = "서버 정상";
    $("#healthBadge").className = "status-badge";
  } catch {
    $("#healthBadge").textContent = "서버 확인 필요";
    $("#healthBadge").className = "status-badge error";
  }
}

function renderCategoryChips(target, selected, mode) {
  target.innerHTML = [
    `<button type="button" class="category-chip ${selected === "" ? "active" : ""}" data-key="">전체</button>`,
    ...state.categories.map((category) => (
      `<button type="button" class="category-chip ${selected === category.key ? "active" : ""}" data-key="${category.key}">${esc(category.name)} <small>${category.recipe_count}</small></button>`
    )),
  ].join("");

  target.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      if (mode === "calc") setCalcCategory(button.dataset.key);
      else setPriceCategory(button.dataset.key);
    });
  });
}

async function setCalcCategory(key) {
  state.categoryKey = key;
  renderCategoryChips($("#categoryChips"), state.categoryKey, "calc");
  $("#itemSearch").value = "";
  await loadCalculations();
}

async function setPriceCategory(key) {
  state.priceCategoryKey = key;
  renderCategoryChips($("#priceCategoryChips"), state.priceCategoryKey, "price");
  $("#priceSearch").value = "";
  await loadPrices();
}

async function loadCalculations() {
  state.feeRate = Number($("#feeRate").value);
  const params = new URLSearchParams({
    fee_rate: String(state.feeRate),
    guild_discount: "true",
  });
  if (state.categoryKey) params.set("category_key", state.categoryKey);
  state.calculations = await api(`/api/meister/calculations?${params}`);
  renderCalculations();
}

function filteredCalculations() {
  const query = $("#itemSearch").value.trim().toLowerCase();
  const profitableOnly = $("#profitableOnly").checked;
  return state.calculations.filter((row) => {
    if (query && !row.name.toLowerCase().includes(query)) return false;
    if (profitableOnly && !(row.price_complete && row.expected_profit > 0)) return false;
    return true;
  });
}

function renderCalculations() {
  const rows = filteredCalculations();
  const complete = rows.filter((row) => row.price_complete);
  const profitable = complete.filter((row) => row.expected_profit > 0);
  const top = profitable[0] || complete[0];
  const guildRate = Math.round(Number(state.gameRules?.guild_shop_discount_rate || 0.04) * 100);

  $("#resultTitle").textContent = `${categoryName(state.categoryKey)} 제작 수익 순위`;
  $("#resultCount").textContent = `${rows.length}개`;
  $("#summaryCards").innerHTML = `
    <div class="metric primary">
      <div class="label">최고 예상 수익</div>
      <div class="value ${top && top.expected_profit >= 0 ? "positive" : "negative"}">${top ? `${top.expected_profit >= 0 ? "+" : ""}${money(top.expected_profit)}` : "-"}</div>
      <div class="hint">${top ? esc(top.name) : "시세가 충분한 제작법 없음"}</div>
    </div>
    <div class="metric"><div class="label">계산 가능한 제작법</div><div class="value">${complete.length}개</div><div class="hint">필요 시세가 모두 입력됨</div></div>
    <div class="metric"><div class="label">이득인 제작</div><div class="value positive">${profitable.length}개</div><div class="hint">수수료 반영 후 0 초과</div></div>
    <div class="metric"><div class="label">현재 규칙</div><div class="value small-value">${esc(categoryName(state.categoryKey))}</div><div class="hint">수수료 ${Math.round(state.feeRate * 100)}% · 길드 상점 ${guildRate}%</div></div>`;

  $("#calcRows").innerHTML = rows.map((row, index) => {
    const missing = row.missing_prices || [];
    const completePrice = row.price_complete;
    return `
      <article class="profit-card ${completePrice && index === 0 && row.expected_profit > 0 ? "top-profit" : ""} ${!completePrice ? "incomplete" : ""}">
        <div class="rank">${completePrice ? index + 1 : "·"}</div>
        <div class="profit-name">
          <strong>${esc(row.name)}</strong>
          <div class="profit-meta">
            <span class="badge">${esc(row.profession)}</span>
            ${row.required_level ? `<span class="badge">Lv.${row.required_level}</span>` : ""}
            ${row.guild_discount_enabled ? `<span class="badge fixed">길드 상점 ${guildRate}%</span>` : ""}
            ${!completePrice ? `<span class="badge warning">시세 ${missing.length}개 필요</span>` : ""}
          </div>
        </div>
        <div class="profit-stat cost"><span>재료비</span><strong>${completePrice ? money(row.input_cost) : "시세 필요"}</strong></div>
        <div class="profit-stat sale"><span>판매 기대값</span><strong>${completePrice ? money(row.net_expected) : "시세 필요"}</strong></div>
        <div class="profit-stat profit-value"><span>예상 순이익</span><strong class="${completePrice ? (row.expected_profit >= 0 ? "positive" : "negative") : ""}">${completePrice ? `${row.expected_profit >= 0 ? "+" : ""}${money(row.expected_profit)} <small>(${pct(row.margin_rate)})</small>` : "계산 대기"}</strong></div>
        <div class="profit-actions">
          <button class="tiny secondary" onclick="showRecipe('${enc(row.recipe_key)}')">레시피</button>
          ${!completePrice && missing.length ? `<button class="tiny" onclick="goToPrice('${enc(missing[0])}')">시세 입력</button>` : ""}
        </div>
      </article>`;
  }).join("") || '<div class="empty-state card">조건에 맞는 제작법이 없습니다.</div>';
}

window.showRecipe = (encoded) => {
  const row = state.calculations.find((item) => item.recipe_key === dec(encoded));
  if (!row) return;
  const inputRows = row.inputs.map((item) => {
    const shopLabel = item.fixed_shop
      ? `<span class="badge fixed">상점 고정가${item.guild_discount_applied ? " · 길드 4%" : ""}</span>`
      : "";
    const priceText = item.price_known
      ? `${money(item.current_price)} / ${money(item.cost)}`
      : "시세 없음";
    return `<li><span>${esc(item.item_name)} × ${item.quantity} ${shopLabel}</span><strong>${priceText}</strong></li>`;
  }).join("");
  const outputRows = row.outputs.map((item) => `<li><span>${esc(item.item_name)} × ${item.quantity}${item.probability !== 100 ? ` · ${item.probability}%` : ""}</span><strong>${item.price_known ? `${money(item.current_price)} / 기대 ${money(item.expected_gross)}` : "시세 없음"}</strong></li>`).join("");
  $("#recipeDialogBody").innerHTML = `
    <p class="section-kicker">${esc(row.profession)}${row.required_level ? ` · Lv.${row.required_level}` : ""}</p>
    <h2>${esc(row.name)}</h2>
    <div class="recipe-block"><h3>필요 재료</h3><ul class="recipe-list">${inputRows}</ul></div>
    <div class="recipe-block"><h3>제작 결과</h3><ul class="recipe-list">${outputRows}</ul></div>
    <div class="recipe-totals">
      <div><span>재료비</span><strong>${row.price_complete ? money(row.input_cost) : "-"}</strong></div>
      <div><span>수수료 후 기대 회수</span><strong>${row.price_complete ? money(row.net_expected) : "-"}</strong></div>
      <div><span>예상 순이익</span><strong class="${row.price_complete ? (row.expected_profit >= 0 ? "positive" : "negative") : ""}">${row.price_complete ? `${row.expected_profit >= 0 ? "+" : ""}${money(row.expected_profit)}` : "시세 입력 필요"}</strong></div>
    </div>
    ${!row.price_complete ? `<button type="button" class="dialog-primary" onclick="goToPrice('${enc(row.missing_prices[0])}');document.querySelector('#recipeDialog').close()">누락 시세 입력하기</button>` : ""}`;
  $("#recipeDialog").showModal();
};

window.goToPrice = async (encoded) => {
  const name = dec(encoded);
  document.querySelectorAll(".tabs button").forEach((button) => button.classList.toggle("active", button.dataset.tab === "prices"));
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === "prices"));
  $("#priceSearch").value = name;
  await loadPrices();
  $("#priceSearch").focus();
};

function priceSourceLabel(source) {
  if (source === "manual") return "직접 입력";
  if (source === "legacy_material" || source === "legacy_item") return "기존 시세";
  return "시세 없음";
}

function renderFixedShopPrices() {
  const rows = state.fixedShopPrices || [];
  $("#fixedShopCount").textContent = `${rows.length}개`;
  $("#fixedShopList").innerHTML = rows.map((row) => `
    <div class="fixed-shop-row">
      <div>
        <strong>${esc(row.item_name)}</strong>
        <small>${esc(row.vendor || "마이스터빌 상점")} · 고정값</small>
      </div>
      <div class="fixed-shop-values">
        <span>기본 <strong>${money(row.regular_price)}</strong></span>
        <span class="guild-price">길드 <strong>${money(row.guild_price)}</strong></span>
      </div>
    </div>`).join("") || '<div class="empty-state">등록된 상점 고정가가 없습니다.</div>';
}

function renderPrices() {
  const query = $("#priceSearch").value.trim().toLowerCase();
  const rows = state.marketPrices.filter((row) => !query || row.item_name.toLowerCase().includes(query));
  $("#marketPriceCount").textContent = `${rows.length}개`;
  $("#marketPriceList").innerHTML = rows.map((row) => {
    const dirty = state.dirtyPrices.has(row.item_name);
    const value = dirty ? state.dirtyPrices.get(row.item_name) : row.current_price;
    return `
      <div class="edit-row unified-edit-row ${dirty ? "dirty" : ""}">
        <div class="name">
          <strong>${esc(row.item_name)}</strong>
          <div class="price-meta">
            ${row.role_labels.map((label) => `<span class="badge">${esc(label)}</span>`).join("")}
            ${row.categories.map((key) => `<span class="badge subtle">${esc(categoryName(key))}</span>`).join("")}
          </div>
          <small>${priceSourceLabel(row.source)}${row.updated_at ? ` · ${new Date(row.updated_at).toLocaleString("ko-KR")}` : ""}</small>
        </div>
        <div class="price-input-wrap"><input inputmode="numeric" value="${esc(value)}" data-price-name="${enc(row.item_name)}" aria-label="${esc(row.item_name)} 시세" /><span>메소</span></div>
      </div>`;
  }).join("") || '<div class="empty-state">검색 결과가 없습니다.</div>';

  $("#marketPriceList").querySelectorAll("input[data-price-name]").forEach((input) => {
    input.addEventListener("input", () => markPriceDirty(dec(input.dataset.priceName), input.value, input));
  });
}

async function loadPrices() {
  const params = new URLSearchParams();
  if (state.priceCategoryKey) params.set("category_key", state.priceCategoryKey);
  state.marketPrices = await api(`/api/market-prices${params.toString() ? `?${params}` : ""}`);
  renderPrices();
  updateSaveBar();
}

function markPriceDirty(name, raw, input) {
  const clean = String(raw).replaceAll(",", "").trim();
  const price = clean === "" ? NaN : Number(clean);
  const original = state.marketPrices.find((row) => row.item_name === name)?.current_price;
  const dirty = !(Number.isFinite(price) && price >= 0 && price === Number(original));
  if (dirty) state.dirtyPrices.set(name, clean);
  else state.dirtyPrices.delete(name);
  input?.closest(".edit-row")?.classList.toggle("dirty", dirty);
  updateSaveBar();
}

function updateSaveBar() {
  const count = state.dirtyPrices.size;
  $("#dirtyCount").textContent = count ? `변경된 시세 ${count}개` : "저장할 변경 없음";
  $("#dirtyHint").textContent = count ? "한 번 저장하면 수정한 값이 모두 반영됩니다." : "가격을 수정하면 여기에 저장 버튼이 활성화됩니다.";
  $("#saveAllPrices").disabled = count === 0;
  $("#saveAllPrices").textContent = count ? `변경된 ${count}개 저장` : "변경된 가격 저장";
}

function requestAdmin() {
  $("#adminSettings").open = true;
  setTimeout(() => $("#adminToken").focus(), 0);
  toast("관리 토큰을 저장하면 수정한 시세를 그대로 이어서 저장합니다.");
}

async function saveAllPrices() {
  if (!state.dirtyPrices.size) return;
  if (state.writeProtected && !token()) return requestAdmin();

  const prices = [];
  for (const [item_name, raw] of state.dirtyPrices) {
    const price = Number(String(raw).replaceAll(",", "").trim());
    if (!Number.isFinite(price) || price < 0) {
      toast(`${item_name} 가격을 확인하세요.`);
      return;
    }
    prices.push({ item_name, price });
  }

  const button = $("#saveAllPrices");
  button.disabled = true;
  button.textContent = "저장 중…";
  try {
    await api("/api/market-prices/bulk", {
      method: "PATCH",
      headers: headers(true),
      body: JSON.stringify({ prices }),
    });
    const count = prices.length;
    state.dirtyPrices.clear();
    toast(`${count}개 시세 저장 완료`);
    await Promise.all([loadPrices(), loadCalculations()]);
  } catch (error) {
    if (error.status === 401) return requestAdmin();
    toast(error.message);
  } finally {
    updateSaveBar();
  }
}

function openSale(craftId, itemId, remaining, name, price) {
  if (remaining <= 0) return toast("이미 모두 판매된 제작 기록입니다.");
  state.action = { craftId, itemId, remaining, name, price };
  $("#actionTitle").textContent = name;
  $("#actionQuantity").value = remaining;
  $("#actionQuantity").max = remaining;
  $("#actionPrice").value = price || "";
  $("#actionDialog").showModal();
}

function closeAction() {
  $("#actionDialog").close();
  state.action = null;
}

async function submitAction(event) {
  event.preventDefault();
  const action = state.action;
  if (!action) return;
  const quantity = Number($("#actionQuantity").value);
  const unit_sale_price = Number($("#actionPrice").value.replaceAll(",", ""));
  if (!Number.isFinite(quantity) || quantity <= 0 || quantity > action.remaining) return toast(`수량은 ${action.remaining} 이하여야 합니다.`);
  if (!Number.isFinite(unit_sale_price) || unit_sale_price < 0) return toast("판매가를 확인하세요.");
  if (state.writeProtected && !token()) return requestAdmin();
  try {
    await api("/api/sales", {
      method: "POST",
      headers: headers(true),
      body: JSON.stringify({ craft_id: action.craftId, item_id: action.itemId, quantity, unit_sale_price, fee_rate: state.feeRate }),
    });
    toast("판매 기록을 저장했습니다.");
    closeAction();
    await loadRecords();
  } catch (error) {
    if (error.status === 401) return requestAdmin();
    toast(error.message);
  }
}

async function loadRecords() {
  const [dashboard, crafts, sales] = await Promise.all([
    api("/api/dashboard?days=30"), api("/api/crafts"), api("/api/sales"),
  ]);
  $("#dashCards").innerHTML = `
    <div class="metric"><div class="label">30일 제작</div><div class="value">${dashboard.crafted_quantity}</div><div class="hint">기존 기록</div></div>
    <div class="metric"><div class="label">판매율</div><div class="value">${pct(dashboard.sell_through_rate)}</div><div class="hint">30일 기준</div></div>
    <div class="metric primary"><div class="label">실현 수익</div><div class="value ${dashboard.realized_profit >= 0 ? "positive" : "negative"}">${dashboard.realized_profit >= 0 ? "+" : ""}${money(dashboard.realized_profit)}</div><div class="hint">판매 완료 기준</div></div>`;

  $("#craftList").innerHTML = crafts.map((craft) => {
    const remaining = Number(craft.quantity) - Number(craft.sold_quantity);
    return `<div class="record"><div class="record-title"><h3>${esc(craft.item_name)} · ${craft.quantity}개</h3><span class="badge">남음 ${remaining}</span></div><p>제작단가 ${money(craft.unit_cost_snapshot)} · ${new Date(craft.crafted_at).toLocaleString("ko-KR")}</p><div class="record-actions"><button class="tiny" ${remaining <= 0 ? "disabled" : ""} data-craft-id="${craft.id}" data-item-id="${craft.item_id}" data-remaining="${remaining}" data-name="${enc(craft.item_name)}" data-price="${craft.sale_price_snapshot}">${remaining > 0 ? "판매 기록" : "판매 완료"}</button></div></div>`;
  }).join("") || '<p class="muted">제작 기록이 없습니다.</p>';

  $("#craftList").querySelectorAll("button[data-craft-id]").forEach((button) => {
    button.addEventListener("click", () => openSale(Number(button.dataset.craftId), Number(button.dataset.itemId), Number(button.dataset.remaining), dec(button.dataset.name), Number(button.dataset.price)));
  });

  $("#saleList").innerHTML = sales.map((sale) => `<div class="record"><div class="record-title"><h3>${esc(sale.item_name)} · ${sale.quantity}개</h3><strong class="${sale.realized_profit >= 0 ? "positive" : "negative"}">${sale.realized_profit >= 0 ? "+" : ""}${money(sale.realized_profit)}</strong></div><p>판매단가 ${money(sale.unit_sale_price)} · ${new Date(sale.sold_at).toLocaleString("ko-KR")}</p></div>`).join("") || '<p class="muted">판매 기록이 없습니다.</p>';
}

async function boot() {
  activateTabs();
  checkHealth();
  const [config, meta, categories, fixedShopPrices] = await Promise.all([
    api("/api/config"),
    api("/api/meister/meta"),
    api("/api/meister/categories"),
    api("/api/meister/fixed-shop-prices"),
  ]);
  state.writeProtected = Boolean(config.write_protected);
  state.meta = meta;
  state.gameRules = config.game_rules || meta.rules || {};
  state.categories = categories;
  state.fixedShopPrices = fixedShopPrices;
  $("#feeRate").value = String(config.default_fee_rate || 0.05);
  state.feeRate = Number($("#feeRate").value);
  $("#adminToken").value = token();
  $("#catalogStatus").textContent = `제작법 ${meta.total_recipe_count}개 · ${meta.synced_at ? new Date(meta.synced_at).toLocaleDateString("ko-KR") : "동기화 정보 없음"}`;
  const guildRate = Math.round(Number(state.gameRules.guild_shop_discount_rate || 0.04) * 100);
  const pcBonus = Math.round(Number(state.gameRules.pc_room_craft_success_bonus_max || 0.10) * 100);
  $("#fixedRuleSummary").textContent = `고정 규칙 · 일반 수수료 5% · PC방 정산 3% · 길드 장사꾼 ${guildRate}% · PC방 제작 성공률 보너스 최대 ${pcBonus}%는 기본 성공률이 검증된 레시피에만 반영`;
  renderCategoryChips($("#categoryChips"), state.categoryKey, "calc");
  renderCategoryChips($("#priceCategoryChips"), state.priceCategoryKey, "price");
  renderFixedShopPrices();

  $("#saveToken").addEventListener("click", async () => {
    sessionStorage.setItem("maple_admin_token", $("#adminToken").value.trim());
    $("#adminSettings").open = false;
    toast("관리 토큰을 저장했습니다.");
    if (state.dirtyPrices.size) await saveAllPrices();
  });
  $("#feeRate").addEventListener("change", loadCalculations);
  $("#itemSearch").addEventListener("input", renderCalculations);
  $("#profitableOnly").addEventListener("change", renderCalculations);
  $("#refresh").addEventListener("click", loadCalculations);
  $("#priceSearch").addEventListener("input", renderPrices);
  $("#saveAllPrices").addEventListener("click", saveAllPrices);
  $("#actionForm").addEventListener("submit", submitAction);
  $("#actionClose").addEventListener("click", closeAction);
  $("#actionCancel").addEventListener("click", closeAction);

  await loadCalculations();
}

boot().catch((error) => toast(error.message));

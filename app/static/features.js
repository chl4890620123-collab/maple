const FAVORITES_KEY = "maple_meister_favorites_v1";

function loadFavoriteKeys() {
  try {
    const value = JSON.parse(localStorage.getItem(FAVORITES_KEY) || "[]");
    return new Set(Array.isArray(value) ? value.map(String) : []);
  } catch {
    return new Set();
  }
}

const favoriteRecipeKeys = loadFavoriteKeys();

function saveFavoriteKeys() {
  localStorage.setItem(FAVORITES_KEY, JSON.stringify([...favoriteRecipeKeys]));
}

function quantity(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(2).replace(/0+$/, "").replace(/\.$/, "");
}

function recipeStats(row) {
  const inputs = row.inputs || [];
  const outputs = row.outputs || [];
  return {
    inputTypes: Number(row.input_type_count ?? inputs.length),
    inputQuantity: Number(row.input_total_quantity ?? inputs.reduce((sum, item) => sum + Number(item.quantity || 0), 0)),
    outputTypes: Number(row.output_type_count ?? outputs.length),
    outputQuantity: Number(row.output_expected_quantity ?? outputs.reduce((sum, item) => sum + Number(item.expected_quantity ?? item.quantity ?? 0), 0)),
    fixedShopInputs: inputs.filter((item) => item.fixed_shop).length,
    marketInputs: inputs.filter((item) => !item.fixed_shop).length,
    missingCount: (row.missing_prices || []).length,
  };
}

function sourcePriceLabel(item) {
  if (item.fixed_shop) return item.guild_discount_applied ? `마빌 상점 고정가 · 길드 ${displayGuildDiscountRate()}%` : "마빌 상점 고정가";
  if (item.source === "manual") return "직접 입력 · DB 저장";
  if (item.source === "legacy_material" || item.source === "legacy_item") return "기존 저장 시세";
  return item.price_known ? "저장 시세" : "직접 입력 필요";
}

function accessLabel(row) {
  const access = row.recipe_access || {};
  if (access.access_type === "permanent") return access.available ? "영구 · 사용 가능" : "영구 · 미보유";
  if (access.access_type === "daily") return access.available ? "일일 · 오늘 사용 가능" : "일일 · 오늘 미보유";
  if (access.access_type === "one_time") return access.available ? "1회 · 사용 가능" : "1회 · 소진/미보유";
  return "레시피 확인 필요";
}

function recommendationState(row) {
  const access = row.recipe_access || {};
  if (access.access_type === "unknown" || !access.access_type) return "unknown";
  return access.available ? "available" : "blocked";
}

function profitSort(a, b) {
  return Number(b.expected_profit ?? -Infinity) - Number(a.expected_profit ?? -Infinity) || String(a.name).localeCompare(String(b.name), "ko");
}

function ensureRecommendationPanel() {
  let panel = document.querySelector("#quickRecommendation");
  if (panel) return panel;
  const calc = document.querySelector("#calc");
  if (!calc) return null;
  panel = document.createElement("section");
  panel.id = "quickRecommendation";
  panel.className = "quick-recommendation card";
  calc.insertBefore(panel, calc.firstChild);
  return panel;
}

function recommendationCard(row, index, stateLabel) {
  const stats = recipeStats(row);
  return `
    <article class="quick-pick">
      <div class="quick-rank">${index + 1}</div>
      <div class="quick-main">
        <strong>${esc(row.name)}</strong>
        <div class="profit-meta">
          <span class="badge">${esc(row.profession)}</span>
          <span class="badge ${stateLabel === "지금 제작 가능" ? "fixed" : "warning"}">${stateLabel}</span>
          ${stats.fixedShopInputs ? `<span class="badge fixed">마빌 고정 ${stats.fixedShopInputs}종</span>` : ""}
        </div>
        <small>재료비 ${money(row.input_cost)} · 수수료 후 회수 ${money(row.net_expected)}</small>
      </div>
      <div class="quick-profit">
        <span>예상 순이익</span>
        <strong class="positive">+${money(row.expected_profit)}</strong>
      </div>
      <button type="button" class="tiny" onclick="showRecipe('${enc(row.recipe_key)}')">자세히 보기</button>
    </article>`;
}

function renderQuickRecommendations() {
  const panel = ensureRecommendationPanel();
  if (!panel) return;
  const profitable = state.calculations
    .filter((row) => row.price_complete && Number(row.expected_profit) > 0)
    .sort(profitSort);

  const available = profitable.filter((row) => recommendationState(row) === "available");
  const unknown = profitable.filter((row) => recommendationState(row) === "unknown");
  const blocked = profitable.filter((row) => recommendationState(row) === "blocked");
  const primary = (available.length ? available : unknown).slice(0, 3);
  const missing = state.calculations
    .filter((row) => !row.price_complete)
    .sort((a, b) => (a.missing_prices || []).length - (b.missing_prices || []).length)
    .slice(0, 3);

  if (!primary.length) {
    panel.innerHTML = `
      <div class="quick-heading">
        <div><p class="section-kicker">바로 결정하기</p><h2>지금 뭐 만들면 이득일까?</h2><p>저장된 가격이 부족해서 아직 수익 순위를 만들 수 없습니다.</p></div>
      </div>
      <div class="quick-empty">${missing.length ? `가격 ${Math.min(...missing.map((row) => (row.missing_prices || []).length))}개만 더 입력하면 계산할 수 있는 제작법이 있습니다.` : "시세를 입력하면 자동으로 추천합니다."}</div>`;
    return;
  }

  const usingFallback = !available.length;
  const prep = [...blocked.slice(0, 2), ...missing.slice(0, 2)].slice(0, 3);
  panel.innerHTML = `
    <div class="quick-heading">
      <div>
        <p class="section-kicker">바로 결정하기</p>
        <h2>지금 뭐 만들면 이득일까?</h2>
        <p>${usingFallback ? "레시피 보유 상태를 아직 확인하지 않은 항목 중" : "현재 제작 가능으로 저장한 항목 중"} 순이익이 높은 순서입니다.</p>
      </div>
      <span class="count-badge">TOP ${primary.length}</span>
    </div>
    <div class="quick-list">
      ${primary.map((row, index) => recommendationCard(row, index, recommendationState(row) === "available" ? "지금 제작 가능" : "레시피 확인 필요")).join("")}
    </div>
    ${prep.length ? `<details class="quick-prep"><summary>수익은 좋지만 준비가 필요한 제작 ${prep.length}개</summary><div>${prep.map((row) => `<button type="button" class="secondary tiny" onclick="showRecipe('${enc(row.recipe_key)}')">${esc(row.name)} · ${row.price_complete ? `+${money(row.expected_profit)}` : `가격 ${(row.missing_prices || []).length}개 필요`}</button>`).join("")}</div></details>` : ""}`;
}

function selectedSortLabel() {
  return document.querySelector("#sortMode option:checked")?.textContent || "순이익 높은순";
}

function compareRows(a, b, mode) {
  const value = (input, fallback) => input === null || input === undefined || Number.isNaN(Number(input)) ? fallback : Number(input);
  if (mode === "margin_desc") return value(b.margin_rate, -Infinity) - value(a.margin_rate, -Infinity) || profitSort(a, b);
  if (mode === "cost_asc") return value(a.input_cost, Infinity) - value(b.input_cost, Infinity) || profitSort(a, b);
  if (mode === "level_asc") return value(a.required_level, Infinity) - value(b.required_level, Infinity) || profitSort(a, b);
  if (mode === "name_asc") return String(a.name).localeCompare(String(b.name), "ko");
  return profitSort(a, b);
}

function enhancedFilteredCalculations() {
  const query = $("#itemSearch").value.trim().toLowerCase();
  const profitableOnly = $("#profitableOnly").checked;
  const favoritesOnly = Boolean($("#favoritesOnly")?.checked);
  const sortMode = $("#sortMode")?.value || "profit_desc";
  const limitValue = $("#rankLimit")?.value || "all";
  let rows = state.calculations.filter((row) => {
    if (query && !row.name.toLowerCase().includes(query)) return false;
    if (profitableOnly && !(row.price_complete && Number(row.expected_profit) > 0)) return false;
    if (favoritesOnly && !favoriteRecipeKeys.has(row.recipe_key)) return false;
    return true;
  });
  rows = [...rows].sort((a, b) => a.price_complete !== b.price_complete ? (a.price_complete ? -1 : 1) : compareRows(a, b, sortMode));
  return limitValue === "all" ? rows : rows.slice(0, Number(limitValue));
}

function renderInformationNotice() {
  const target = $("#sourceNotice");
  if (!target) return;
  const baseline = state.meta?.source_policy?.baseline || "메이플스토리 인벤 제작 DB";
  target.innerHTML = `<strong>정보 기준</strong><span>레시피·재료·수량은 ${esc(baseline)} 기준입니다. 마빌 상점 재료는 고정가, 나머지 가격은 직접 저장합니다. 상세 화면에서 아이템 가격을 바로 수정할 수 있습니다.</span>`;
}

function renderCalculationsEnhanced() {
  renderQuickRecommendations();
  const rows = enhancedFilteredCalculations();
  const complete = rows.filter((row) => row.price_complete);
  const profitable = complete.filter((row) => Number(row.expected_profit) > 0);
  const top = profitable[0] || complete[0];
  const favoriteCount = favoriteRecipeKeys.size;

  $("#resultTitle").textContent = `${categoryName(state.categoryKey)} 제작 순위 · ${selectedSortLabel()}`;
  $("#resultCount").textContent = `${rows.length}개`;
  if ($("#favoriteCount")) $("#favoriteCount").textContent = `${favoriteCount}개`;
  $("#summaryCards").innerHTML = `
    <div class="metric primary"><div class="label">현재 1위</div><div class="value">${top?.price_complete ? `${top.expected_profit >= 0 ? "+" : ""}${money(top.expected_profit)}` : "-"}</div><div class="hint">${top ? esc(top.name) : "계산 가능한 제작법 없음"}</div></div>
    <div class="metric"><div class="label">계산 가능</div><div class="value">${complete.length}개</div><div class="hint">필요 가격 입력 완료</div></div>
    <div class="metric"><div class="label">이득인 제작</div><div class="value positive">${profitable.length}개</div><div class="hint">수수료 반영</div></div>
    <div class="metric"><div class="label">즐겨찾기</div><div class="value">${favoriteCount}개</div><div class="hint">길드 ${displayGuildDiscountRate()}% 설정 저장</div></div>`;

  $("#calcRows").innerHTML = rows.map((row, index) => {
    const stats = recipeStats(row);
    const favorite = favoriteRecipeKeys.has(row.recipe_key);
    const missing = row.missing_prices || [];
    return `
      <article class="profit-card feature-profit-card ${!row.price_complete ? "incomplete" : ""}">
        <div class="rank-column"><div class="rank">${row.price_complete ? index + 1 : "·"}</div><button class="favorite-button ${favorite ? "active" : ""}" data-favorite-key="${enc(row.recipe_key)}">${favorite ? "★" : "☆"}</button></div>
        <div class="feature-profit-main">
          <div class="profit-name"><strong>${esc(row.name)}</strong><div class="profit-meta"><span class="badge">${esc(row.profession)}</span><span class="badge">${esc(accessLabel(row))}</span>${stats.fixedShopInputs ? `<span class="badge fixed">마빌 고정 재료 ${stats.fixedShopInputs}종</span>` : ""}${!row.price_complete ? `<span class="badge warning">직접 가격 ${stats.missingCount}개 필요</span>` : ""}</div></div>
          <div class="recipe-facts"><span><b>재료</b> ${stats.inputTypes}종 · 총 ${quantity(stats.inputQuantity)}개</span><span><b>가격</b> 마빌 고정 ${stats.fixedShopInputs}종 / 직접저장 ${stats.marketInputs}종</span></div>
          <div class="feature-metrics"><div><span>재료비</span><strong>${row.price_complete ? money(row.input_cost) : "가격 필요"}</strong></div><div><span>수수료 후 회수</span><strong>${row.price_complete ? money(row.net_expected) : "가격 필요"}</strong></div><div><span>예상 순이익</span><strong>${row.price_complete ? `${row.expected_profit >= 0 ? "+" : ""}${money(row.expected_profit)}` : "계산 대기"}</strong></div></div>
        </div>
        <div class="profit-actions feature-actions"><button class="tiny secondary" onclick="showRecipe('${enc(row.recipe_key)}')">상세/설정</button>${!row.price_complete && missing.length ? `<button class="tiny" onclick="showRecipe('${enc(row.recipe_key)}')">가격 바로 입력</button>` : ""}</div>
      </article>`;
  }).join("") || '<div class="empty-state card">조건에 맞는 제작법이 없습니다.</div>';

  $("#calcRows").querySelectorAll("button[data-favorite-key]").forEach((button) => button.addEventListener("click", () => {
    const key = dec(button.dataset.favoriteKey);
    if (favoriteRecipeKeys.has(key)) favoriteRecipeKeys.delete(key); else favoriteRecipeKeys.add(key);
    saveFavoriteKeys();
    renderCalculationsEnhanced();
  }));
}

async function latestMarketRow(itemName) {
  try {
    const rows = await api(`/api/market-prices?q=${encodeURIComponent(itemName)}`);
    return rows.find((row) => row.item_name === itemName) || null;
  } catch {
    return null;
  }
}

function formatUpdatedAt(value) {
  if (!value) return "저장 시각 없음";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "저장 시각 없음" : `${date.toLocaleString("ko-KR")} 저장`;
}

function itemPriceEditor(row, item) {
  const locked = Boolean(item.fixed_shop);
  return `<span class="inline-price" data-recipe-key="${enc(row.recipe_key)}" data-item-name="${enc(item.item_name)}"><button type="button" class="tiny secondary inline-price-open">${esc(item.item_name)} · ${item.price_known ? money(item.current_price) : "가격 입력"}</button><small>${esc(sourcePriceLabel(item))}${locked ? " · 수정 불가" : ""}</small></span>`;
}

async function openInlinePriceEditor(container) {
  const recipeKey = dec(container.dataset.recipeKey);
  const itemName = dec(container.dataset.itemName);
  const row = state.calculations.find((entry) => entry.recipe_key === recipeKey);
  if (!row) return;
  const item = [...(row.inputs || []), ...(row.outputs || [])].find((entry) => entry.item_name === itemName);
  if (!item) return;
  if (item.fixed_shop) {
    toast(`${item.item_name} · ${money(item.current_price)} 메소 · 마이스터빌 고정가`);
    return;
  }

  const latest = await latestMarketRow(item.item_name);
  const current = latest?.price_known ? latest.current_price : item.current_price;
  const updated = formatUpdatedAt(latest?.updated_at);
  container.innerHTML = `<div class="inline-price-form"><strong>${esc(item.item_name)}</strong><input class="inline-price-input" inputmode="numeric" value="${latest?.price_known || item.price_known ? Math.round(Number(current || 0)) : ""}" placeholder="가격 입력"><span>메소</span><button type="button" class="tiny inline-price-save">저장</button><button type="button" class="tiny secondary inline-price-cancel">취소</button></div><small>${esc(updated)}</small>`;
  container.querySelector(".inline-price-input").focus();
  container.querySelector(".inline-price-cancel").onclick = () => detailedRecipeDialog(enc(recipeKey));
  container.querySelector(".inline-price-save").onclick = async () => {
    const raw = container.querySelector(".inline-price-input").value.replaceAll(",", "").trim();
    const price = Number(raw);
    if (!Number.isFinite(price) || price < 0) return toast("가격을 0 이상의 숫자로 입력하세요.");
    if (state.writeProtected && !token()) return requestAdmin();
    try {
      await api("/api/market-prices/bulk", {method: "PATCH", headers: headers(true), body: JSON.stringify({prices: [{item_name: item.item_name, price: Math.round(price)}]})});
      toast(`${item.item_name} · ${money(price)} 메소 저장 완료`);
      await loadCalculations();
      detailedRecipeDialog(enc(recipeKey));
    } catch (error) {
      if (error.status === 401) return requestAdmin();
      toast(error.message);
    }
  };
}

function bindInlinePriceEditors() {
  document.querySelectorAll("#recipeDialogBody .inline-price").forEach((container) => {
    const button = container.querySelector(".inline-price-open");
    if (button) button.onclick = () => openInlinePriceEditor(container);
  });
}

async function saveRecipeAccess(row) {
  if (state.writeProtected && !token()) return requestAdmin();
  const type = $("#recipeAccessType").value;
  const owned = $("#recipeOwned").checked;
  try {
    await api(`/api/meister/recipes/${enc(row.recipe_key)}/state`, {method: "PATCH", headers: headers(true), body: JSON.stringify({access_type: type, is_owned: owned})});
    toast("레시피 사용 상태를 DB에 저장했습니다.");
    await loadCalculations();
    detailedRecipeDialog(enc(row.recipe_key));
  } catch (error) {
    if (error.status === 401) return requestAdmin();
    toast(error.message);
  }
}

async function consumeRecipe(row) {
  if (!confirm("1회 레시피를 사용 처리할까요?")) return;
  if (state.writeProtected && !token()) return requestAdmin();
  try {
    await api(`/api/meister/recipes/${enc(row.recipe_key)}/consume`, {method: "POST", headers: headers(true)});
    toast("1회 레시피를 사용 처리했습니다.");
    await loadCalculations();
    detailedRecipeDialog(enc(row.recipe_key));
  } catch (error) {
    toast(error.message);
  }
}

function detailedRecipeDialog(encoded) {
  const row = state.calculations.find((item) => item.recipe_key === dec(encoded));
  if (!row) return;
  const access = row.recipe_access || {};
  const inputs = row.inputs.map((item) => `<tr><td>${itemPriceEditor(row, item)}</td><td>${quantity(item.quantity)}</td><td>${item.price_known ? money(item.current_price) : "-"}</td><td>${item.price_known ? money(item.cost) : "-"}</td></tr>`).join("");
  const outputs = row.outputs.map((item) => `<tr><td>${itemPriceEditor(row, item)}</td><td>${quantity(item.quantity)}</td><td>${item.price_known ? money(item.current_price) : "-"}</td></tr>`).join("");

  $("#recipeDialogBody").innerHTML = `
    <p class="section-kicker">${esc(row.profession)}</p><h2>${esc(row.name)}</h2>
    <div class="recipe-block"><h3>레시피 사용 상태</h3><p class="muted">확인한 상태만 저장하세요. 일일은 오늘만, 영구는 계속, 1회는 사용 처리 전까지만 제작 가능으로 봅니다.</p><div class="meister-filter-grid"><div class="search-field"><label for="recipeAccessType">사용 형태</label><select id="recipeAccessType"><option value="unknown">확인 필요</option><option value="permanent">영구</option><option value="daily">일일</option><option value="one_time">1회</option></select></div><label class="toggle-field"><input id="recipeOwned" type="checkbox"><span>현재 보유/사용 가능</span></label><button id="saveRecipeAccess" type="button">상태 저장</button>${access.access_type === "one_time" && access.available ? '<button id="consumeRecipe" type="button" class="secondary">1회 사용 처리</button>' : ""}</div></div>
    <div class="recipe-block"><h3>필요 재료</h3><p class="muted">아이템 이름/가격을 누르면 이 자리에서 바로 수정할 수 있습니다. 마빌 상점 고정가는 읽기 전용입니다.</p><div class="table-scroll"><table class="recipe-table"><thead><tr><th>재료</th><th>수량</th><th>개당 가격</th><th>합계</th></tr></thead><tbody>${inputs}</tbody></table></div></div>
    <div class="recipe-block"><h3>제작 결과</h3><div class="table-scroll"><table class="recipe-table"><thead><tr><th>결과물</th><th>수량</th><th>시세</th></tr></thead><tbody>${outputs}</tbody></table></div></div>
    <div class="recipe-totals"><div><span>재료비</span><strong>${row.input_cost != null ? money(row.input_cost) : "-"}</strong></div><div><span>수수료 후 회수</span><strong>${row.net_expected != null ? money(row.net_expected) : "-"}</strong></div><div><span>예상 순이익</span><strong class="${row.expected_profit >= 0 ? "positive" : "negative"}">${row.expected_profit != null ? `${row.expected_profit >= 0 ? "+" : ""}${money(row.expected_profit)}` : "가격 입력 필요"}</strong></div></div>`;

  $("#recipeAccessType").value = access.access_type || "unknown";
  $("#recipeOwned").checked = Boolean(access.is_owned);
  $("#saveRecipeAccess").onclick = () => saveRecipeAccess(row);
  if ($("#consumeRecipe")) $("#consumeRecipe").onclick = () => consumeRecipe(row);
  bindInlinePriceEditors();
  if (!$("#recipeDialog").open) $("#recipeDialog").showModal();
}

renderCalculations = renderCalculationsEnhanced;
window.showRecipe = detailedRecipeDialog;

function bindFeatureControls() {
  ["sortMode", "rankLimit", "favoritesOnly"].forEach((id) => {
    const element = $(`#${id}`);
    if (element) element.addEventListener("change", renderCalculationsEnhanced);
  });
  renderInformationNotice();
}

bindFeatureControls();
const featureReadyTimer = setInterval(() => {
  if (state.meta && state.calculations.length) {
    clearInterval(featureReadyTimer);
    renderInformationNotice();
    renderCalculationsEnhanced();
  }
}, 100);
setTimeout(() => clearInterval(featureReadyTimer), 10000);

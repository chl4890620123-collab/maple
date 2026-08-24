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
  const inputs = Array.isArray(row.inputs) ? row.inputs : [];
  const outputs = Array.isArray(row.outputs) ? row.outputs : [];
  return {
    inputTypes: Number(row.input_type_count ?? inputs.length),
    inputQuantity: Number(row.input_total_quantity ?? inputs.reduce((sum, item) => sum + Number(item.quantity || 0), 0)),
    outputTypes: Number(row.output_type_count ?? outputs.length),
    outputQuantity: Number(row.output_expected_quantity ?? outputs.reduce((sum, item) => sum + Number(item.expected_quantity ?? item.quantity ?? 0), 0)),
    fixedShopInputs: inputs.filter((item) => item.fixed_shop).length,
    marketInputs: inputs.filter((item) => !item.fixed_shop).length,
    missingCount: Array.isArray(row.missing_prices) ? row.missing_prices.length : 0,
  };
}

function verificationLabel(status) {
  if (status === "official_override") return "공식 보정";
  return "인벤 제작 DB 기준";
}

function recipeSourceLabel(row) {
  return row.source_label || verificationLabel(row.verification_status);
}

function sourcePriceLabel(item) {
  if (item.fixed_shop) return item.guild_discount_applied ? "상점 고정가 · 길드 4%" : "상점 고정가";
  if (item.source === "manual") return "직접 입력 시세";
  if (item.source === "legacy_material" || item.source === "legacy_item") return "기존 저장 시세";
  return item.price_known ? "경매장 시세" : "시세 미입력";
}

function selectedSortLabel() {
  return document.querySelector("#sortMode option:checked")?.textContent || "순이익 높은순";
}

function compareRows(a, b, mode) {
  const av = (value, fallback) => value === null || value === undefined || Number.isNaN(Number(value)) ? fallback : Number(value);
  if (mode === "margin_desc") {
    return av(b.margin_rate, -Infinity) - av(a.margin_rate, -Infinity) || av(b.expected_profit, -Infinity) - av(a.expected_profit, -Infinity);
  }
  if (mode === "cost_asc") {
    return av(a.input_cost, Infinity) - av(b.input_cost, Infinity) || av(b.expected_profit, -Infinity) - av(a.expected_profit, -Infinity);
  }
  if (mode === "level_asc") {
    return av(a.required_level, Infinity) - av(b.required_level, Infinity) || av(a.item_level, Infinity) - av(b.item_level, Infinity) || av(b.expected_profit, -Infinity) - av(a.expected_profit, -Infinity);
  }
  if (mode === "name_asc") return String(a.name).localeCompare(String(b.name), "ko");
  return av(b.expected_profit, -Infinity) - av(a.expected_profit, -Infinity) || String(a.name).localeCompare(String(b.name), "ko");
}

function enhancedFilteredCalculations() {
  const query = $("#itemSearch").value.trim().toLowerCase();
  const profitableOnly = $("#profitableOnly").checked;
  const favoritesOnly = Boolean($("#favoritesOnly")?.checked);
  const sortMode = $("#sortMode")?.value || "profit_desc";
  const limitValue = $("#rankLimit")?.value || "all";

  let rows = state.calculations.filter((row) => {
    if (query && !row.name.toLowerCase().includes(query)) return false;
    if (profitableOnly && !(row.price_complete && row.expected_profit > 0)) return false;
    if (favoritesOnly && !favoriteRecipeKeys.has(row.recipe_key)) return false;
    return true;
  });

  rows = [...rows].sort((a, b) => {
    if (a.price_complete !== b.price_complete) return a.price_complete ? -1 : 1;
    return compareRows(a, b, sortMode);
  });

  if (limitValue !== "all") rows = rows.slice(0, Number(limitValue));
  return rows;
}

function renderInformationNotice() {
  const target = $("#sourceNotice");
  if (!target) return;
  const policy = state.meta?.source_policy || {};
  const baseline = policy.baseline || "메이플스토리 인벤 제작 DB";
  const guide = policy.official_guide;
  target.innerHTML = `
    <strong>정보 기준</strong>
    <span>전체 레시피·재료·수량·아이템 레벨은 ${esc(baseline)}를 기준선으로 사용하고, 검증된 공식 변경만 별도 보정합니다.</span>
    ${guide ? `<a href="${esc(guide)}" target="_blank" rel="noopener noreferrer">공식 전문기술 가이드</a>` : ""}`;
}

function renderCalculationsEnhanced() {
  const rows = enhancedFilteredCalculations();
  const complete = rows.filter((row) => row.price_complete);
  const profitable = complete.filter((row) => Number(row.expected_profit) > 0);
  const top = profitable[0] || complete[0];
  const favoriteCount = favoriteRecipeKeys.size;
  const guildRate = Math.round(Number(state.gameRules?.guild_shop_discount_rate || 0.04) * 100);

  $("#resultTitle").textContent = `${categoryName(state.categoryKey)} 제작 순위 · ${selectedSortLabel()}`;
  $("#resultCount").textContent = `${rows.length}개`;
  if ($("#favoriteCount")) $("#favoriteCount").textContent = `${favoriteCount}개`;
  $("#summaryCards").innerHTML = `
    <div class="metric primary">
      <div class="label">현재 1위</div>
      <div class="value ${top && top.expected_profit >= 0 ? "positive" : "negative"}">${top && top.price_complete ? `${top.expected_profit >= 0 ? "+" : ""}${money(top.expected_profit)}` : "-"}</div>
      <div class="hint">${top ? esc(top.name) : "계산 가능한 제작법 없음"}</div>
    </div>
    <div class="metric"><div class="label">계산 가능한 제작법</div><div class="value">${complete.length}개</div><div class="hint">필요 시세가 모두 입력됨</div></div>
    <div class="metric"><div class="label">이득인 제작</div><div class="value positive">${profitable.length}개</div><div class="hint">수수료 반영 후 순이익 0 초과</div></div>
    <div class="metric"><div class="label">즐겨찾기</div><div class="value">${favoriteCount}개</div><div class="hint">이 브라우저에 저장 · 길드 상점 ${guildRate}% 자동 반영</div></div>`;

  $("#calcRows").innerHTML = rows.map((row, index) => {
    const stats = recipeStats(row);
    const missing = row.missing_prices || [];
    const completePrice = row.price_complete;
    const favorite = favoriteRecipeKeys.has(row.recipe_key);
    const rankText = completePrice ? index + 1 : "·";
    const grossText = completePrice ? money(row.gross_expected) : "시세 필요";
    return `
      <article class="profit-card feature-profit-card ${completePrice && index === 0 && Number(row.expected_profit) > 0 ? "top-profit" : ""} ${!completePrice ? "incomplete" : ""}">
        <div class="rank-column">
          <div class="rank">${rankText}</div>
          <button type="button" class="favorite-button ${favorite ? "active" : ""}" data-favorite-key="${enc(row.recipe_key)}" aria-label="${favorite ? "즐겨찾기 해제" : "즐겨찾기 추가"}" title="${favorite ? "즐겨찾기 해제" : "즐겨찾기 추가"}">${favorite ? "★" : "☆"}</button>
        </div>
        <div class="feature-profit-main">
          <div class="profit-name">
            <strong>${esc(row.name)}</strong>
            <div class="profit-meta">
              <span class="badge">${esc(row.profession)}</span>
              ${row.item_level ? `<span class="badge">아이템 Lv.${row.item_level}</span>` : ""}
              ${row.required_level ? `<span class="badge">전문기술 Lv.${row.required_level}</span>` : ""}
              <span class="badge source">${esc(recipeSourceLabel(row))}</span>
              ${stats.fixedShopInputs ? `<span class="badge fixed">상점 재료 ${stats.fixedShopInputs}종</span>` : ""}
              ${!completePrice ? `<span class="badge warning">시세 ${stats.missingCount}개 필요</span>` : ""}
            </div>
          </div>
          <div class="recipe-facts">
            <span><b>재료</b> ${stats.inputTypes}종 · 총 ${quantity(stats.inputQuantity)}개</span>
            <span><b>결과</b> ${stats.outputTypes}종 · 기대 ${quantity(stats.outputQuantity)}개</span>
            <span><b>가격 기준</b> 상점 ${stats.fixedShopInputs}종 / 경매장 ${stats.marketInputs}종</span>
          </div>
          <div class="feature-metrics">
            <div><span>재료비</span><strong>${completePrice ? money(row.input_cost) : "시세 필요"}</strong></div>
            <div><span>수수료 전 매출</span><strong>${grossText}</strong></div>
            <div><span>수수료 후 회수</span><strong>${completePrice ? money(row.net_expected) : "시세 필요"}</strong></div>
            <div><span>예상 순이익</span><strong class="${completePrice ? (row.expected_profit >= 0 ? "positive" : "negative") : ""}">${completePrice ? `${row.expected_profit >= 0 ? "+" : ""}${money(row.expected_profit)} <small>${pct(row.margin_rate)}</small>` : "계산 대기"}</strong></div>
          </div>
        </div>
        <div class="profit-actions feature-actions">
          <button class="tiny secondary" onclick="showRecipe('${enc(row.recipe_key)}')">상세 정보</button>
          ${!completePrice && missing.length ? `<button class="tiny" onclick="goToPrice('${enc(missing[0])}')">시세 입력</button>` : ""}
        </div>
      </article>`;
  }).join("") || '<div class="empty-state card">조건에 맞는 제작법이 없습니다.</div>';

  $("#calcRows").querySelectorAll("button[data-favorite-key]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = dec(button.dataset.favoriteKey);
      if (favoriteRecipeKeys.has(key)) favoriteRecipeKeys.delete(key);
      else favoriteRecipeKeys.add(key);
      saveFavoriteKeys();
      renderCalculationsEnhanced();
      toast(favoriteRecipeKeys.has(key) ? "즐겨찾기에 추가했습니다." : "즐겨찾기에서 제거했습니다.");
    });
  });
}

function detailedRecipeDialog(encoded) {
  const row = state.calculations.find((item) => item.recipe_key === dec(encoded));
  if (!row) return;
  const stats = recipeStats(row);
  const feePercent = Math.round(Number(row.fee_rate || state.feeRate) * 100);
  const breakEvenGross = row.input_cost === null || row.input_cost === undefined
    ? null
    : Number(row.input_cost) / (1 - Number(row.fee_rate || state.feeRate));
  const inputRows = row.inputs.map((item) => `
    <tr>
      <td><strong>${esc(item.item_name)}</strong><small>${esc(sourcePriceLabel(item))}</small></td>
      <td>${quantity(item.quantity)}</td>
      <td>${item.price_known ? money(item.current_price) : "-"}</td>
      <td>${item.price_known ? money(item.cost) : "-"}</td>
    </tr>`).join("");
  const outputRows = row.outputs.map((item) => `
    <tr>
      <td><strong>${esc(item.item_name)}</strong></td>
      <td>${quantity(item.quantity)}</td>
      <td>${pct(item.probability)}</td>
      <td>${quantity(item.expected_quantity)}</td>
      <td>${item.price_known ? money(item.current_price) : "-"}</td>
      <td>${item.price_known ? money(item.expected_gross) : "-"}</td>
    </tr>`).join("");
  const favorite = favoriteRecipeKeys.has(row.recipe_key);
  const sourceUrl = row.source_url;
  $("#recipeDialogBody").innerHTML = `
    <div class="dialog-title-row">
      <div>
        <p class="section-kicker">${esc(row.profession)}${row.item_level ? ` · 아이템 Lv.${row.item_level}` : ""}${row.required_level ? ` · 전문기술 Lv.${row.required_level}` : ""}</p>
        <h2>${esc(row.name)}</h2>
      </div>
      <button type="button" id="dialogFavorite" class="favorite-button large ${favorite ? "active" : ""}">${favorite ? "★ 찜 해제" : "☆ 찜하기"}</button>
    </div>
    <div class="recipe-info-strip">
      <span>재료 ${stats.inputTypes}종 · 총 ${quantity(stats.inputQuantity)}개</span>
      <span>결과 ${stats.outputTypes}종 · 기대 ${quantity(stats.outputQuantity)}개</span>
      <span>수수료 ${feePercent}%</span>
      <span>${esc(recipeSourceLabel(row))}</span>
    </div>
    <div class="recipe-block">
      <h3>필요 재료</h3>
      <div class="table-scroll"><table class="recipe-table"><thead><tr><th>재료</th><th>수량</th><th>개당 가격</th><th>합계</th></tr></thead><tbody>${inputRows}</tbody></table></div>
    </div>
    <div class="recipe-block">
      <h3>제작 결과</h3>
      <div class="table-scroll"><table class="recipe-table output-table"><thead><tr><th>결과물</th><th>수량</th><th>확률</th><th>기대 수량</th><th>시세</th><th>기대 매출</th></tr></thead><tbody>${outputRows}</tbody></table></div>
    </div>
    <div class="recipe-totals feature-totals">
      <div><span>총 재료비</span><strong>${row.input_cost !== null ? money(row.input_cost) : "-"}</strong></div>
      <div><span>수수료 전 기대 매출</span><strong>${row.gross_expected !== null ? money(row.gross_expected) : "-"}</strong></div>
      <div><span>수수료 후 기대 회수</span><strong>${row.net_expected !== null ? money(row.net_expected) : "-"}</strong></div>
      <div><span>손익분기 총매출</span><strong>${breakEvenGross !== null ? money(breakEvenGross) : "-"}</strong></div>
      <div><span>예상 순이익</span><strong class="${row.price_complete ? (row.expected_profit >= 0 ? "positive" : "negative") : ""}">${row.price_complete ? `${row.expected_profit >= 0 ? "+" : ""}${money(row.expected_profit)}` : "-"}</strong></div>
      <div><span>원가 대비 마진</span><strong>${row.price_complete ? pct(row.margin_rate) : "-"}</strong></div>
    </div>
    <div class="source-box">
      <strong>정보 출처</strong>
      <span>${esc(recipeSourceLabel(row))}. 전체 목록은 제작 DB 기준선이며 검증된 공식 변경만 override로 보정합니다.</span>
      ${sourceUrl ? `<a href="${esc(sourceUrl)}" target="_blank" rel="noopener noreferrer">원본 제작 정보 보기</a>` : ""}
    </div>
    ${!row.price_complete && row.missing_prices?.length ? `<button type="button" class="dialog-primary" onclick="goToPrice('${enc(row.missing_prices[0])}');document.querySelector('#recipeDialog').close()">누락 시세 입력하기</button>` : ""}`;

  $("#dialogFavorite").addEventListener("click", () => {
    if (favoriteRecipeKeys.has(row.recipe_key)) favoriteRecipeKeys.delete(row.recipe_key);
    else favoriteRecipeKeys.add(row.recipe_key);
    saveFavoriteKeys();
    renderCalculationsEnhanced();
    detailedRecipeDialog(encoded);
  }, { once: true });
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

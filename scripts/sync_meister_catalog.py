from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag


ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://maple.inven.co.kr/dataninfo/recipe/list.php?retype={}"
OUTPUT_PATH = ROOT / "data" / "meister_catalog.json"
OVERRIDE_PATH = ROOT / "data" / "meister_overrides.json"
USER_AGENT = "Mozilla/5.0 (compatible; MapleCraftAnalytics/1.0; +https://github.com/chl4890620123-collab/maple)"


@dataclass(frozen=True)
class Category:
    key: str
    name: str
    retype: int
    level_labels: tuple[str, ...]


CATEGORIES = (
    Category("herbalism", "약초채집", 1, ("약초채집",)),
    Category("mining", "채광", 2, ("광물채집", "채광")),
    Category("equipment", "장비제작", 3, ("장비제작", "장비 제작")),
    Category("accessory", "장신구제작", 4, ("장신구제작", "장신구 제작")),
    Category("alchemy", "연금술", 5, ("연금술",)),
)

QTY_RE = re.compile(r"(?:x|×)\s*([0-9]+(?:\.[0-9]+)?)", re.I)
PROB_RE = re.compile(r"\(([0-9]+(?:\.[0-9]+)?)%\)")
ITEM_LEVEL_RE = re.compile(r"^Lv\.\s*([0-9]+)", re.I)
ITEM_LEVEL_PREFIX_RE = re.compile(r"^Lv\.\s*[0-9]+\s+")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_quantity(text: str) -> float:
    match = QTY_RE.search(text)
    return float(match.group(1)) if match else 1.0


def parse_probability(text: str) -> float:
    match = PROB_RE.search(text)
    return float(match.group(1)) if match else 100.0


def parse_item_level(text: str) -> int | None:
    match = ITEM_LEVEL_RE.search(text)
    return int(match.group(1)) if match else None


def parse_required_level(text: str, category: Category) -> int | None:
    for label in category.level_labels:
        match = re.search(rf"{re.escape(label)}\s*Lv\.\s*([0-9]+)", text)
        if match:
            return int(match.group(1))
    return None


def text_anchor(container: Tag) -> str | None:
    for anchor in reversed(container.find_all("a")):
        text = clean_text(anchor.get_text(" ", strip=True))
        if text:
            return text
    return None


def parse_entries(cell: Tag, *, outputs: bool) -> list[dict]:
    entries: list[dict] = []
    blocks = cell.find_all("li")
    if not blocks:
        blocks = [node for node in cell.find_all(["div", "p"], recursive=False) if clean_text(node.get_text(" ", strip=True))]

    for block in blocks:
        name = text_anchor(block)
        text = clean_text(block.get_text(" ", strip=True))
        if not name or not text:
            continue
        entry = {"name": name, "quantity": parse_quantity(text)}
        if outputs:
            entry["probability"] = parse_probability(text)
        entries.append(entry)

    if entries:
        return entries

    seen: set[str] = set()
    for anchor in cell.find_all("a"):
        name = clean_text(anchor.get_text(" ", strip=True))
        if not name or name in seen:
            continue
        seen.add(name)
        parent_text = clean_text(anchor.parent.get_text(" ", strip=True)) if anchor.parent else name
        entry = {"name": name, "quantity": parse_quantity(parent_text)}
        if outputs:
            entry["probability"] = parse_probability(parent_text)
        entries.append(entry)
    return entries


def find_recipe_table(soup: BeautifulSoup) -> Tag:
    for table in soup.find_all("table"):
        text = clean_text(table.get_text(" ", strip=True))
        if "제작법" in text and "재료" in text and "완성품" in text:
            return table
    raise RuntimeError("제작법/재료/완성품 테이블을 찾지 못했습니다.")


def make_recipe_key(category_key: str, required_level: int | None, inputs: list[dict], outputs: list[dict]) -> str:
    # Keep the key independent from display-only metadata such as item_level.
    # This preserves market-price links, overrides and browser favorites across catalog refreshes.
    identity = {"category": category_key, "required_level": required_level, "inputs": inputs, "outputs": outputs}
    raw = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{category_key}-{hashlib.sha256(raw).hexdigest()[:16]}"


def parse_category(category: Category) -> dict:
    url = BASE_URL.format(category.retype)
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    soup = BeautifulSoup(response.text, "lxml")
    table = find_recipe_table(soup)
    recipes: list[dict] = []
    seen_keys: set[str] = set()

    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        title_text = clean_text(cells[0].get_text(" ", strip=True))
        inputs = parse_entries(cells[1], outputs=False)
        outputs = parse_entries(cells[2], outputs=True)
        if not inputs or not outputs:
            continue
        item_level = parse_item_level(title_text)
        required_level = parse_required_level(title_text, category)
        primary_name = outputs[0]["name"]
        display_name = ITEM_LEVEL_PREFIX_RE.sub("", primary_name).strip() or primary_name
        recipe_key = make_recipe_key(category.key, required_level, inputs, outputs)
        if recipe_key in seen_keys:
            continue
        seen_keys.add(recipe_key)
        recipes.append({
            "recipe_key": recipe_key,
            "name": display_name,
            "category_key": category.key,
            "profession": category.name,
            "item_level": item_level,
            "required_level": required_level,
            "inputs": inputs,
            "outputs": outputs,
            "source_url": url,
            "source_label": "메이플스토리 인벤 제작 DB",
            "verification_status": "third_party_baseline",
        })

    if not recipes:
        raise RuntimeError(f"{category.name} 레시피가 0개로 파싱되었습니다.")
    return {"key": category.key, "name": category.name, "source_url": url, "recipe_count": len(recipes), "recipes": recipes}


def apply_overrides(categories: list[dict]) -> list[dict]:
    if not OVERRIDE_PATH.exists():
        return categories
    overrides = json.loads(OVERRIDE_PATH.read_text(encoding="utf-8"))
    disabled = set(overrides.get("disable", []))
    replacements = {recipe["recipe_key"]: recipe for recipe in overrides.get("replace", [])}
    by_category = {category["key"]: category for category in categories}

    for category in categories:
        merged = []
        for recipe in category["recipes"]:
            key = recipe["recipe_key"]
            if key in disabled:
                continue
            if key in replacements:
                replacement = replacements[key]
                if replacement.get("category_key") != category["key"]:
                    raise RuntimeError(f"override category mismatch: {key}")
                merged.append(replacement)
            else:
                merged.append(recipe)
        category["recipes"] = merged

    for recipe in overrides.get("add", []):
        category_key = recipe.get("category_key")
        if category_key not in by_category:
            raise RuntimeError(f"override add category mismatch: {category_key}")
        if not recipe.get("recipe_key"):
            recipe["recipe_key"] = make_recipe_key(category_key, recipe.get("required_level"), recipe["inputs"], recipe["outputs"])
        recipe.setdefault("verification_status", "official_override")
        by_category[category_key]["recipes"].append(recipe)

    for category in categories:
        category["recipe_count"] = len(category["recipes"])
    return categories


def validate_catalog(categories: list[dict]) -> None:
    expected = {category.key for category in CATEGORIES}
    actual = {category["key"] for category in categories}
    if actual != expected:
        raise RuntimeError(f"카테고리 불일치: expected={sorted(expected)}, actual={sorted(actual)}")
    all_keys: list[str] = []
    total = 0
    for category in categories:
        count = len(category["recipes"])
        total += count
        if count < 5:
            raise RuntimeError(f"{category['name']} 레시피가 비정상적으로 적습니다: {count}")
        for recipe in category["recipes"]:
            if not recipe.get("inputs") or not recipe.get("outputs"):
                raise RuntimeError(f"입출력이 비어 있는 레시피: {recipe.get('recipe_key')}")
            item_level = recipe.get("item_level")
            if item_level is not None and int(item_level) <= 0:
                raise RuntimeError(f"잘못된 아이템 레벨: {recipe['recipe_key']} = {item_level}")
            for entry in recipe["inputs"]:
                if float(entry.get("quantity", 0)) <= 0:
                    raise RuntimeError(f"잘못된 재료 수량: {recipe['recipe_key']} = {entry}")
            for output in recipe["outputs"]:
                if float(output.get("quantity", 0)) <= 0:
                    raise RuntimeError(f"잘못된 결과 수량: {recipe['recipe_key']} = {output}")
                probability = float(output.get("probability", 100))
                if probability <= 0 or probability > 100:
                    raise RuntimeError(f"잘못된 제작 확률: {recipe['recipe_key']} = {probability}")
            all_keys.append(recipe["recipe_key"])
    if total < 50:
        raise RuntimeError(f"전체 레시피 수가 비정상적으로 적습니다: {total}")
    if len(all_keys) != len(set(all_keys)):
        raise RuntimeError("전체 카탈로그에 recipe_key 중복이 있습니다.")


def main() -> int:
    categories = [parse_category(category) for category in CATEGORIES]
    categories = apply_overrides(categories)
    validate_catalog(categories)
    total = sum(len(category["recipes"]) for category in categories)
    for category in categories:
        print(f"{category['name']}: {len(category['recipes'])} recipes")

    payload = {
        "schema_version": 4,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "source_policy": {
            "baseline": "메이플스토리 인벤 제작 DB",
            "official_guide": "https://maplestory.nexon.com/Guide/N23GameInformation/Articles/379",
            "override_file": "data/meister_overrides.json",
            "note": "제3자 제작 DB를 전체 목록 기준선으로 사용하고, 검증된 최신 공식 변경만 override로 보정합니다. 시세 데이터는 제작 카탈로그와 분리합니다.",
        },
        "total_recipe_count": total,
        "categories": categories,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {total} recipes -> {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"catalog sync failed: {exc}", file=sys.stderr)
        raise

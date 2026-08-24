from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup, Tag


BASE_URL = "https://maple.inven.co.kr/dataninfo/recipe/list.php?retype={}"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "meister_catalog.json"
USER_AGENT = "Mozilla/5.0 (compatible; MapleCraftAnalytics/1.0; +https://github.com/chl4890620123-collab/maple)"


@dataclass(frozen=True)
class Category:
    key: str
    name: str
    retype: int


CATEGORIES = (
    Category("herbalism", "약초채집", 1),
    Category("mining", "채광", 2),
    Category("equipment", "장비제작", 3),
    Category("accessory", "장신구제작", 4),
    Category("alchemy", "연금술", 5),
)


QTY_RE = re.compile(r"(?:x|×)\s*([0-9]+(?:\.[0-9]+)?)", re.I)
PROB_RE = re.compile(r"\(([0-9]+(?:\.[0-9]+)?)%\)")
LEVEL_RE = re.compile(r"(?:약초채집|채광|장비제작|장신구제작|연금술)\s*Lv\.\s*([0-9]+)")
ITEM_LEVEL_PREFIX_RE = re.compile(r"^Lv\.\s*[0-9]+\s+")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def parse_quantity(text: str) -> float:
    match = QTY_RE.search(text)
    return float(match.group(1)) if match else 1.0


def parse_probability(text: str) -> float:
    match = PROB_RE.search(text)
    return float(match.group(1)) if match else 100.0


def text_anchor(container: Tag) -> str | None:
    anchors = container.find_all("a")
    for anchor in reversed(anchors):
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
        entry = {
            "name": name,
            "quantity": parse_quantity(text),
        }
        if outputs:
            entry["probability"] = parse_probability(text)
        entries.append(entry)

    if entries:
        return entries

    # Fallback for table cells that do not use list elements.
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


def parse_category(category: Category) -> dict:
    url = BASE_URL.format(category.retype)
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"

    soup = BeautifulSoup(response.text, "lxml")
    table = find_recipe_table(soup)
    recipes: list[dict] = []
    signatures: set[str] = set()

    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue

        title_text = clean_text(cells[0].get_text(" ", strip=True))
        inputs = parse_entries(cells[1], outputs=False)
        outputs = parse_entries(cells[2], outputs=True)
        if not inputs or not outputs:
            continue

        level_match = LEVEL_RE.search(title_text)
        required_level = int(level_match.group(1)) if level_match else None
        primary_name = outputs[0]["name"]
        display_name = ITEM_LEVEL_PREFIX_RE.sub("", primary_name).strip() or primary_name

        recipe = {
            "name": display_name,
            "profession": category.name,
            "required_level": required_level,
            "inputs": inputs,
            "outputs": outputs,
            "source_url": url,
            "source_label": "메이플스토리 인벤 제작 DB",
        }
        signature = json.dumps(recipe, ensure_ascii=False, sort_keys=True)
        if signature in signatures:
            continue
        signatures.add(signature)
        recipes.append(recipe)

    if not recipes:
        raise RuntimeError(f"{category.name} 레시피가 0개로 파싱되었습니다.")

    return {
        "key": category.key,
        "name": category.name,
        "source_url": url,
        "recipe_count": len(recipes),
        "recipes": recipes,
    }


def main() -> int:
    categories = []
    total = 0
    for category in CATEGORIES:
        parsed = parse_category(category)
        categories.append(parsed)
        total += parsed["recipe_count"]
        print(f"{category.name}: {parsed['recipe_count']} recipes")

    payload = {
        "schema_version": 1,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "source_policy": {
            "catalog": "메이플스토리 인벤 제작 DB",
            "official_guide": "https://maplestory.nexon.com/Guide/N23GameInformation/Articles/379",
            "note": "시세는 별도 가격 테이블에서 관리하며 제작 카탈로그와 분리합니다.",
        },
        "total_recipe_count": total,
        "categories": categories,
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {total} recipes -> {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"catalog sync failed: {exc}", file=sys.stderr)
        raise

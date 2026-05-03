from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from funnel_app.config import db_path  # noqa: E402
from funnel_app.db import connect, init_db, now_iso  # noqa: E402


DEFAULT_CONFIG = ROOT / "config" / "company_import_priority.json"


@dataclass(frozen=True)
class Candidate:
    symbol: str
    name: str
    sector: str
    industry: str
    country: str
    market_cap: float
    priority_key: str
    priority_label: str
    priority_rank: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a prioritized company universe.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input", type=Path, help="Optional Nasdaq screener JSON file.")
    parser.add_argument("--db", type=Path, default=db_path())
    parser.add_argument("--limit", type=int, help="Override target_count from config.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_json_source(config: dict[str, Any], input_path: Path | None) -> dict[str, Any]:
    if input_path:
        return json.loads(input_path.read_text(encoding="utf-8"))
    request = Request(
        config["source_url"],
        headers={
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 StockPickingFunnel/0.1",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def normalize(value: Any) -> str:
    return str(value or "").strip()


def parse_market_cap(value: Any) -> float:
    text = normalize(value).replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def contains_any(haystack: str, needles: list[str]) -> bool:
    lowered = haystack.lower()
    return any(needle.lower() in lowered for needle in needles)


def is_excluded(row: dict[str, Any], config: dict[str, Any]) -> bool:
    symbol = normalize(row.get("symbol"))
    name = f" {normalize(row.get('name')).lower()} "
    industry = normalize(row.get("industry")).lower()
    market_cap = parse_market_cap(row.get("marketCap"))

    if config.get("exclude_zero_market_cap", True) and market_cap <= 0:
        return True
    if contains_any(symbol, config.get("exclude_symbol_contains", [])):
        return True
    if contains_any(name, config.get("exclude_name_contains", [])):
        return True
    if contains_any(industry, config.get("exclude_industry_contains", [])):
        return True
    return False


def match_category(row: dict[str, Any], categories: list[dict[str, Any]]) -> tuple[int, dict[str, Any]] | None:
    sector = normalize(row.get("sector"))
    industry = normalize(row.get("industry"))
    name = normalize(row.get("name"))
    searchable = f"{sector} {industry} {name}"

    for index, category in enumerate(categories):
        if sector in category.get("sector_any", []):
            return index, category
        if industry in category.get("industry_any", []):
            return index, category
        if contains_any(searchable, category.get("industry_contains", [])):
            return index, category
    return None


def build_candidates(payload: dict[str, Any], config: dict[str, Any], limit: int) -> list[Candidate]:
    rows = payload.get("data", {}).get("rows", [])
    categories = config.get("priority_categories", [])
    by_symbol: dict[str, Candidate] = {}

    for row in rows:
        if is_excluded(row, config):
            continue
        match = match_category(row, categories)
        if not match:
            continue
        rank, category = match
        symbol = normalize(row.get("symbol")).upper()
        if not symbol:
            continue
        candidate = Candidate(
            symbol=symbol,
            name=normalize(row.get("name")) or symbol,
            sector=normalize(row.get("sector")),
            industry=normalize(row.get("industry")),
            country=normalize(row.get("country")),
            market_cap=parse_market_cap(row.get("marketCap")),
            priority_key=category["key"],
            priority_label=category["label"],
            priority_rank=rank,
        )
        current = by_symbol.get(symbol)
        if current is None or (candidate.priority_rank, -candidate.market_cap) < (
            current.priority_rank,
            -current.market_cap,
        ):
            by_symbol[symbol] = candidate

    ordered = sorted(
        by_symbol.values(),
        key=lambda item: (item.priority_rank, -item.market_cap, item.symbol),
    )
    return ordered[:limit]


def insert_candidates(
    conn: sqlite3.Connection,
    candidates: list[Candidate],
    source_name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    timestamp = now_iso()
    inserted = 0
    skipped = 0
    by_category: dict[str, int] = {}

    for candidate in candidates:
        exists = conn.execute(
            "SELECT id FROM companies WHERE ticker = ?", (candidate.symbol,)
        ).fetchone()
        if exists:
            skipped += 1
            continue
        by_category[candidate.priority_label] = by_category.get(candidate.priority_label, 0) + 1
        notes = (
            f"Universe seed: {source_name}. "
            f"Priority bucket: {candidate.priority_label}. "
            f"Sector: {candidate.sector or 'n/a'}. "
            f"Industry: {candidate.industry or 'n/a'}. "
            f"Country: {candidate.country or 'n/a'}. "
            f"Market cap at import: {candidate.market_cap:,.0f}."
        )
        inserted += 1
        if dry_run:
            continue
        conn.execute(
            """
            INSERT INTO companies (ticker, name, bucket, current_stage_id, notes, created_at, updated_at)
            VALUES (?, ?, 'pool', NULL, ?, ?, ?)
            """,
            (candidate.symbol, candidate.name, notes, timestamp, timestamp),
        )

    if not dry_run:
        conn.commit()
    return {
        "selected": len(candidates),
        "inserted": inserted,
        "skipped_existing": skipped,
        "inserted_by_category": by_category,
    }


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    limit = args.limit or int(config.get("target_count", 1000))
    payload = load_json_source(config, args.input)
    candidates = build_candidates(payload, config, limit)

    conn = connect(args.db)
    try:
        init_db(conn)
        summary = insert_candidates(
            conn,
            candidates,
            source_name=config.get("source_name", "company universe source"),
            dry_run=args.dry_run,
        )
    finally:
        conn.close()

    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()


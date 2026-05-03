from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from funnel_app.config import db_path  # noqa: E402
from funnel_app.db import connect, dump_json, guard_template_structure_change, init_db, now_iso  # noqa: E402
from funnel_app.template_parser import parse_markdown_template  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a markdown report template into a funnel stage.")
    parser.add_argument("--stage-key", required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--db", type=Path, default=db_path())
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--yes-i-understand", action="store_true")
    parser.add_argument("--yes-backup-then-apply", action="store_true")
    return parser.parse_args()


def import_template(
    conn: sqlite3.Connection,
    stage_key: str,
    source: Path,
    name: str,
    description: str,
    activate: bool,
    *,
    auto_confirm: bool = False,
    input_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
    backup_root: Path | None = None,
) -> dict[str, object]:
    stage = conn.execute("SELECT id FROM stages WHERE key = ?", (stage_key,)).fetchone()
    if not stage:
        raise ValueError(f"Stage not found: {stage_key}")
    if not source.exists():
        raise FileNotFoundError(source)

    stage_id = int(stage["id"])
    markdown = source.read_text(encoding="utf-8")
    schema = parse_markdown_template(markdown)
    active = conn.execute(
        """
        SELECT id, markdown, version FROM templates
        WHERE stage_id = ? AND is_active = 1
        ORDER BY version DESC, id DESC
        LIMIT 1
        """,
        (stage_id,),
    ).fetchone()

    timestamp = now_iso()
    if active and active["markdown"] == markdown:
        conn.execute(
            """
            UPDATE templates
            SET name = ?, description = ?, schema_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, description, dump_json(schema), timestamp, int(active["id"])),
        )
        conn.commit()
        return {
            "template_id": int(active["id"]),
            "action": "updated_existing_active",
            "field_count": schema["field_count"],
        }

    summary_lines = [
        f"Stage: {stage_key}",
        f"Source: {source}",
        f"Incoming structure: {schema['section_count']} sections / {schema['field_count']} fields",
        f"Active template will be replaced for future reports: {'yes' if activate else 'no'}",
    ]
    if active:
        summary_lines.append(
            f"Current active template: id={int(active['id'])}, version={int(active['version'])}"
        )
    backup = guard_template_structure_change(
        conn,
        action=f"Import template for stage '{stage_key}'",
        summary_lines=summary_lines,
        auto_confirm=auto_confirm,
        input_fn=input_fn,
        output_fn=output_fn,
        backup_root=backup_root,
        backup_metadata={
            "stage_key": stage_key,
            "source": str(source),
            "name": name,
            "description": description,
            "activate": bool(activate),
            "current_active_template_id": int(active["id"]) if active else None,
            "incoming_field_count": schema["field_count"],
            "incoming_section_count": schema["section_count"],
        },
    )

    if activate:
        conn.execute("UPDATE templates SET is_active = 0, updated_at = ? WHERE stage_id = ?", (timestamp, stage_id))

    next_version = conn.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 FROM templates WHERE stage_id = ?", (stage_id,)
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO templates
        (stage_id, name, version, description, markdown, schema_json, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            stage_id,
            name,
            int(next_version),
            description,
            markdown,
            dump_json(schema),
            1 if activate else 0,
            timestamp,
            timestamp,
        ),
    )
    template_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
    conn.commit()
    return {
        "template_id": template_id,
        "action": "created",
        "version": int(next_version),
        "active": bool(activate),
        "field_count": schema["field_count"],
        "section_count": schema["section_count"],
        "backup": backup,
    }


def main() -> None:
    args = parse_args()
    conn = connect(args.db)
    try:
        init_db(conn)
        result = import_template(
            conn,
            stage_key=args.stage_key,
            source=args.source.expanduser().resolve(),
            name=args.name,
            description=args.description,
            activate=args.activate,
            auto_confirm=bool(args.yes_i_understand and args.yes_backup_then_apply),
        )
    finally:
        conn.close()
    print(result)


if __name__ == "__main__":
    main()

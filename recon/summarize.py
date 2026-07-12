"""Summarize captured/redacted records into an endpoint inventory."""
from __future__ import annotations

import json
import sys
from pathlib import Path


def inventory(records: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str, str], dict] = {}
    for rec in records:
        key = (rec["method"], rec["host"], rec["path"])
        entry = grouped.setdefault(
            key, {"method": rec["method"], "host": rec["host"], "path": rec["path"],
                  "count": 0, "_statuses": set()}
        )
        entry["count"] += 1
        entry["_statuses"].add(rec["status"])
    rows = []
    for entry in grouped.values():
        entry["statuses"] = sorted(entry.pop("_statuses"))
        rows.append(entry)
    rows.sort(key=lambda r: (r["host"], r["path"], r["method"]))
    return rows


def format_inventory(rows: list[dict]) -> str:
    lines = ["| Method | Host | Path | Count | Statuses |",
             "| --- | --- | --- | --- | --- |"]
    for r in rows:
        statuses = ", ".join(str(s) for s in r["statuses"])
        lines.append(f"| {r['method']} | {r['host']} | {r['path']} | {r['count']} | {statuses} |")
    return "\n".join(lines)


def load_records(directory: Path) -> list[dict]:
    records = []
    for path in sorted(directory.glob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("recon/fixtures")
    print(format_inventory(inventory(load_records(target))))

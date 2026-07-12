# tests/test_summarize.py
from recon.summarize import format_inventory, inventory


def _rec(method, host, path, status):
    return {"method": method, "host": host, "path": path, "status": status,
            "url": f"https://{host}{path}", "request": {}, "response": {}}


def test_inventory_groups_and_counts():
    records = [
        _rec("GET", "api.alf.se", "/devices", 200),
        _rec("GET", "api.alf.se", "/devices", 200),
        _rec("GET", "api.alf.se", "/devices", 401),
        _rec("POST", "api.alf.se", "/login", 200),
    ]
    rows = inventory(records)
    devices = next(r for r in rows if r["path"] == "/devices")
    assert devices["count"] == 3
    assert devices["statuses"] == [200, 401]
    assert len(rows) == 2


def test_inventory_sorted_by_host_then_path():
    records = [_rec("GET", "b.host", "/z", 200), _rec("GET", "a.host", "/a", 200)]
    rows = inventory(records)
    assert [r["host"] for r in rows] == ["a.host", "b.host"]


def test_format_inventory_renders_markdown_table():
    rows = inventory([_rec("GET", "api.alf.se", "/devices", 200)])
    table = format_inventory(rows)
    assert "| Method | Host | Path | Count | Statuses |" in table
    assert "| GET | api.alf.se | /devices | 1 | 200 |" in table

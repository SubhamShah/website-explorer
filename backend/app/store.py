import json
import sqlite3
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "explorer.db"


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS scans (
        id TEXT PRIMARY KEY, url TEXT NOT NULL, status TEXT NOT NULL,
        max_pages INTEGER NOT NULL, max_depth INTEGER NOT NULL,
        created_at TEXT NOT NULL, completed_at TEXT, summary_json TEXT NOT NULL DEFAULT '{}', error TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS pages (
        id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, url TEXT NOT NULL, status INTEGER,
        title TEXT, h1 TEXT, meta_description TEXT, load_ms INTEGER, screenshot_path TEXT,
        console_json TEXT NOT NULL DEFAULT '[]', network_json TEXT NOT NULL DEFAULT '[]',
        links_json TEXT NOT NULL DEFAULT '[]', final_url TEXT, depth INTEGER NOT NULL DEFAULT 0,
        error_type TEXT, error_detail TEXT, redirect_chain_json TEXT NOT NULL DEFAULT '[]'
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS findings (
        id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, page_url TEXT, severity TEXT NOT NULL,
        category TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL
    )""")
    conn.commit()
    page_columns = {row["name"] for row in conn.execute("PRAGMA table_info(pages)").fetchall()}
    migrations = {
        "final_url": "ALTER TABLE pages ADD COLUMN final_url TEXT",
        "depth": "ALTER TABLE pages ADD COLUMN depth INTEGER NOT NULL DEFAULT 0",
        "error_type": "ALTER TABLE pages ADD COLUMN error_type TEXT",
        "error_detail": "ALTER TABLE pages ADD COLUMN error_detail TEXT",
        "redirect_chain_json": "ALTER TABLE pages ADD COLUMN redirect_chain_json TEXT NOT NULL DEFAULT '[]'",
    }
    for column, statement in migrations.items():
        if column not in page_columns:
            conn.execute(statement)
    conn.commit()
    return conn


def row_to_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    for key in ("summary_json", "console_json", "network_json", "links_json", "redirect_chain_json"):
        if key in result:
            raw_value = result.pop(key)
            fallback = "{}" if key == "summary_json" else "[]"
            result[key.removesuffix("_json")] = json.loads(raw_value or fallback)
    return result


def create_scan(url: str, max_pages: int, max_depth: int) -> dict:
    from datetime import datetime, timezone
    scan = {"id": str(uuid4()), "url": url, "status": "queued", "max_pages": max_pages, "max_depth": max_depth, "created_at": datetime.now(timezone.utc).isoformat()}
    with connection() as conn:
        conn.execute("INSERT INTO scans(id,url,status,max_pages,max_depth,created_at) VALUES(:id,:url,:status,:max_pages,:max_depth,:created_at)", scan)
    return scan


def update_scan(scan_id: str, **values: object) -> None:
    if not values:
        return
    values = {key: json.dumps(value) if key == "summary" else value for key, value in values.items()}
    values["id"] = scan_id
    assignments = ", ".join(f"{key}{'_json' if key == 'summary' else ''}=:{key}" for key in values if key != "id")
    with connection() as conn:
        conn.execute(f"UPDATE scans SET {assignments} WHERE id=:id", values)


def save_page(scan_id: str, page: dict) -> None:
    page = {**page, "id": str(uuid4()), "scan_id": scan_id}
    for key in ("console", "network", "links", "redirect_chain"):
        page[f"{key}_json"] = json.dumps(page.pop(key, []))
    with connection() as conn:
        conn.execute("""INSERT INTO pages(
            id,scan_id,url,final_url,depth,status,title,h1,meta_description,load_ms,screenshot_path,
            error_type,error_detail,redirect_chain_json,console_json,network_json,links_json
        ) VALUES(
            :id,:scan_id,:url,:final_url,:depth,:status,:title,:h1,:meta_description,:load_ms,:screenshot_path,
            :error_type,:error_detail,:redirect_chain_json,:console_json,:network_json,:links_json
        )""", page)


def save_finding(scan_id: str, finding: dict) -> None:
    with connection() as conn:
        conn.execute("INSERT INTO findings(id,scan_id,page_url,severity,category,title,detail) VALUES(?,?,?,?,?,?,?)", (str(uuid4()), scan_id, finding.get("page_url"), finding["severity"], finding["category"], finding["title"], finding["detail"]))


def get_scan(scan_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
    return row_to_dict(row) if row else None


def list_scans() -> list[dict]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM scans ORDER BY created_at DESC").fetchall()
    return [row_to_dict(row) for row in rows]


def scan_details(scan_id: str) -> dict | None:
    scan = get_scan(scan_id)
    if not scan:
        return None
    with connection() as conn:
        pages = conn.execute("SELECT * FROM pages WHERE scan_id=? ORDER BY url", (scan_id,)).fetchall()
        findings = conn.execute("SELECT * FROM findings WHERE scan_id=? ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END", (scan_id,)).fetchall()
    scan["pages"] = [row_to_dict(row) for row in pages]
    scan["findings"] = [dict(row) for row in findings]
    return scan

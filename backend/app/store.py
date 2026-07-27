import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from .insights import build_issue_groups, compare_issue_groups, enrich_finding, finding_metadata, infer_page_priority

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "explorer.db"


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS scans (
        id TEXT PRIMARY KEY, url TEXT NOT NULL, status TEXT NOT NULL,
        max_pages INTEGER NOT NULL, max_depth INTEGER NOT NULL,
        created_at TEXT NOT NULL, completed_at TEXT, summary_json TEXT NOT NULL DEFAULT '{}', error TEXT,
        agency_name TEXT, report_title TEXT, brand_color TEXT NOT NULL DEFAULT '#187249',
        content_checks_json TEXT NOT NULL DEFAULT '{}', site_analysis_json TEXT NOT NULL DEFAULT '{}'
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS pages (
        id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, url TEXT NOT NULL, status INTEGER,
        title TEXT, h1 TEXT, meta_description TEXT, load_ms INTEGER, screenshot_path TEXT,
        console_json TEXT NOT NULL DEFAULT '[]', network_json TEXT NOT NULL DEFAULT '[]',
        links_json TEXT NOT NULL DEFAULT '[]', final_url TEXT, depth INTEGER NOT NULL DEFAULT 0,
        error_type TEXT, error_detail TEXT, redirect_chain_json TEXT NOT NULL DEFAULT '[]',
        priority TEXT NOT NULL DEFAULT 'standard', responsive_json TEXT NOT NULL DEFAULT '{}',
        quality_json TEXT NOT NULL DEFAULT '{}'
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS findings (
        id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, page_url TEXT, severity TEXT NOT NULL,
        category TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}'
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS page_priorities (
        site_url TEXT NOT NULL, page_url TEXT NOT NULL, priority TEXT NOT NULL,
        updated_at TEXT NOT NULL, PRIMARY KEY(site_url, page_url)
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS report_shares (
        token TEXT PRIMARY KEY, scan_id TEXT NOT NULL, report_kind TEXT NOT NULL,
        comparison_scan_id TEXT, created_at TEXT NOT NULL, expires_at TEXT NOT NULL
    )""")
    conn.commit()
    page_columns = {row["name"] for row in conn.execute("PRAGMA table_info(pages)").fetchall()}
    migrations = {
        "final_url": "ALTER TABLE pages ADD COLUMN final_url TEXT",
        "depth": "ALTER TABLE pages ADD COLUMN depth INTEGER NOT NULL DEFAULT 0",
        "error_type": "ALTER TABLE pages ADD COLUMN error_type TEXT",
        "error_detail": "ALTER TABLE pages ADD COLUMN error_detail TEXT",
        "redirect_chain_json": "ALTER TABLE pages ADD COLUMN redirect_chain_json TEXT NOT NULL DEFAULT '[]'",
        "priority": "ALTER TABLE pages ADD COLUMN priority TEXT NOT NULL DEFAULT 'standard'",
        "responsive_json": "ALTER TABLE pages ADD COLUMN responsive_json TEXT NOT NULL DEFAULT '{}'",
        "quality_json": "ALTER TABLE pages ADD COLUMN quality_json TEXT NOT NULL DEFAULT '{}'",
    }
    for column, statement in migrations.items():
        if column not in page_columns:
            conn.execute(statement)
    finding_columns = {row["name"] for row in conn.execute("PRAGMA table_info(findings)").fetchall()}
    if "metadata_json" not in finding_columns:
        conn.execute("ALTER TABLE findings ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
    scan_columns = {row["name"] for row in conn.execute("PRAGMA table_info(scans)").fetchall()}
    scan_migrations = {
        "agency_name": "ALTER TABLE scans ADD COLUMN agency_name TEXT",
        "report_title": "ALTER TABLE scans ADD COLUMN report_title TEXT",
        "brand_color": "ALTER TABLE scans ADD COLUMN brand_color TEXT NOT NULL DEFAULT '#187249'",
        "content_checks_json": "ALTER TABLE scans ADD COLUMN content_checks_json TEXT NOT NULL DEFAULT '{}'",
        "site_analysis_json": "ALTER TABLE scans ADD COLUMN site_analysis_json TEXT NOT NULL DEFAULT '{}'",
    }
    for column, statement in scan_migrations.items():
        if column not in scan_columns:
            conn.execute(statement)
    manually_prioritized = """NOT EXISTS (
        SELECT 1 FROM page_priorities pp JOIN scans priority_scan ON priority_scan.url=pp.site_url
        WHERE priority_scan.id=pages.scan_id AND pp.page_url=pages.url
    )"""
    conn.execute(
        f"""UPDATE pages SET priority='critical' WHERE priority='standard' AND {manually_prioritized}
        AND (
            lower(url) LIKE '%/checkout%' OR lower(url) LIKE '%/cart%' OR
            lower(url) LIKE '%/payment%' OR lower(url) LIKE '%/login%' OR
            lower(url) LIKE '%/signin%' OR lower(url) LIKE '%/sign-in%' OR
            lower(url) LIKE '%/signup%' OR lower(url) LIKE '%/sign-up%' OR
            lower(url) LIKE '%/register%' OR lower(url) LIKE '%/pricing%'
        )"""
    )
    conn.execute(
        f"""UPDATE pages SET priority='high_value' WHERE priority='standard' AND {manually_prioritized}
        AND (
            lower(url) LIKE '%/product%' OR lower(url) LIKE '%/service%' OR
            lower(url) LIKE '%/solution%' OR lower(url) LIKE '%/feature%' OR
            lower(url) LIKE '%/plans%'
        )"""
    )
    conn.commit()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row) -> dict:
    result = dict(row)
    for key in ("summary_json", "console_json", "network_json", "links_json", "redirect_chain_json", "metadata_json", "responsive_json", "quality_json", "content_checks_json", "site_analysis_json"):
        if key in result:
            raw_value = result.pop(key)
            fallback = "{}" if key in {"summary_json", "metadata_json", "responsive_json", "quality_json", "content_checks_json", "site_analysis_json"} else "[]"
            result[key.removesuffix("_json")] = json.loads(raw_value or fallback)
    return result


def create_scan(url: str, max_pages: int, max_depth: int, content_checks: dict | None = None) -> dict:
    from datetime import datetime, timezone
    scan = {"id": str(uuid4()), "url": url, "status": "queued", "max_pages": max_pages, "max_depth": max_depth, "created_at": datetime.now(timezone.utc).isoformat(), "content_checks_json": json.dumps(content_checks or {})}
    with connection() as conn:
        conn.execute("INSERT INTO scans(id,url,status,max_pages,max_depth,created_at,content_checks_json) VALUES(:id,:url,:status,:max_pages,:max_depth,:created_at,:content_checks_json)", scan)
    scan["content_checks"] = json.loads(scan.pop("content_checks_json"))
    return scan


def update_scan(scan_id: str, **values: object) -> None:
    if not values:
        return
    values = {key: json.dumps(value) if key in {"summary", "site_analysis"} else value for key, value in values.items()}
    values["id"] = scan_id
    assignments = ", ".join(f"{key}{'_json' if key in {'summary', 'site_analysis'} else ''}=:{key}" for key in values if key != "id")
    with connection() as conn:
        conn.execute(f"UPDATE scans SET {assignments} WHERE id=:id", values)


def save_page(scan_id: str, page: dict) -> None:
    page = {**page, "id": str(uuid4()), "scan_id": scan_id}
    for key in ("console", "network", "links", "redirect_chain"):
        page[f"{key}_json"] = json.dumps(page.pop(key, []))
    page["responsive_json"] = json.dumps(page.pop("responsive", {}))
    page["quality_json"] = json.dumps(page.pop("quality", {}))
    with connection() as conn:
        scan = conn.execute("SELECT url FROM scans WHERE id=?", (scan_id,)).fetchone()
        saved_priority = (
            conn.execute(
                "SELECT priority FROM page_priorities WHERE site_url=? AND page_url=?",
                (scan["url"], page["url"]),
            ).fetchone()
            if scan
            else None
        )
        page["priority"] = saved_priority["priority"] if saved_priority else infer_page_priority(page["url"])
        conn.execute("""INSERT INTO pages(
            id,scan_id,url,final_url,depth,status,title,h1,meta_description,load_ms,screenshot_path,
            error_type,error_detail,redirect_chain_json,console_json,network_json,links_json,priority,responsive_json,quality_json
        ) VALUES(
            :id,:scan_id,:url,:final_url,:depth,:status,:title,:h1,:meta_description,:load_ms,:screenshot_path,
            :error_type,:error_detail,:redirect_chain_json,:console_json,:network_json,:links_json,:priority,:responsive_json,:quality_json
        )""", page)


def set_page_priority(scan_id: str, page_url: str, priority: str) -> bool:
    if priority not in {"critical", "high_value", "standard"}:
        raise ValueError("Invalid page priority")
    with connection() as conn:
        scan = conn.execute("SELECT url FROM scans WHERE id=?", (scan_id,)).fetchone()
        page = conn.execute("SELECT 1 FROM pages WHERE scan_id=? AND url=?", (scan_id, page_url)).fetchone()
        if not scan or not page:
            return False
        conn.execute(
            """INSERT INTO page_priorities(site_url,page_url,priority,updated_at)
            VALUES(?,?,?,?)
            ON CONFLICT(site_url,page_url) DO UPDATE SET
                priority=excluded.priority, updated_at=excluded.updated_at""",
            (scan["url"], page_url, priority, datetime.now(timezone.utc).isoformat()),
        )
        conn.execute(
            """UPDATE pages SET priority=?
            WHERE url=? AND scan_id IN (SELECT id FROM scans WHERE url=?)""",
            (priority, page_url, scan["url"]),
        )
    return True


def update_report_settings(scan_id: str, agency_name: str | None, report_title: str | None, brand_color: str) -> bool:
    with connection() as conn:
        cursor = conn.execute(
            "UPDATE scans SET agency_name=?, report_title=?, brand_color=? WHERE id=?",
            (agency_name, report_title, brand_color, scan_id),
        )
    return cursor.rowcount > 0


def create_report_share(
    token: str,
    scan_id: str,
    report_kind: str,
    comparison_scan_id: str | None,
    expires_at: str,
) -> None:
    with connection() as conn:
        conn.execute(
            """INSERT INTO report_shares(
                token,scan_id,report_kind,comparison_scan_id,created_at,expires_at
            ) VALUES(?,?,?,?,?,?)""",
            (
                token,
                scan_id,
                report_kind,
                comparison_scan_id,
                datetime.now(timezone.utc).isoformat(),
                expires_at,
            ),
        )


def get_report_share(token: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM report_shares WHERE token=?", (token,)).fetchone()
    return dict(row) if row else None


def save_finding(scan_id: str, finding: dict) -> None:
    metadata = finding_metadata(finding)
    with connection() as conn:
        conn.execute(
            """INSERT INTO findings(
                id,scan_id,page_url,severity,category,title,detail,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                scan_id,
                finding.get("page_url"),
                finding["severity"],
                finding["category"],
                finding["title"],
                finding["detail"],
                json.dumps(metadata),
            ),
        )


def get_scan(scan_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
    return row_to_dict(row) if row else None


def list_scans() -> list[dict]:
    with connection() as conn:
        rows = conn.execute("SELECT * FROM scans ORDER BY created_at DESC").fetchall()
    return [row_to_dict(row) for row in rows]


def scan_status(scan_id: str) -> dict | None:
    scan = get_scan(scan_id)
    if not scan:
        return None
    return {
        key: scan.get(key)
        for key in (
            "id", "url", "status", "max_pages", "max_depth", "created_at",
            "completed_at", "summary", "error",
        )
    }


def page_summaries(scan_id: str, offset: int = 0, limit: int = 50) -> dict:
    with connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE scan_id=?",
            (scan_id,),
        ).fetchone()[0]
        rows = conn.execute(
            """SELECT id,scan_id,url,final_url,depth,status,title,h1,meta_description,
                load_ms,screenshot_path,error_type,error_detail,priority,
                (SELECT COUNT(*) FROM json_each(pages.responsive_json)) AS responsive_viewport_count
            FROM pages WHERE scan_id=? ORDER BY url LIMIT ? OFFSET ?""",
            (scan_id, limit, offset),
        ).fetchall()
    return {
        "items": [dict(row) for row in rows],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(rows) < total,
    }


def findings_page(
    scan_id: str,
    offset: int = 0,
    limit: int = 250,
    severity: str = "all",
    category: str = "all",
    query: str = "",
) -> dict:
    ordering = """ORDER BY
        CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2
            WHEN 'low' THEN 3 WHEN 'info' THEN 4 ELSE 5 END,
        CASE category WHEN 'network' THEN 1 ELSE 0 END, title"""
    clauses = ["scan_id=?"]
    parameters: list[object] = [scan_id]
    if severity == "issues":
        clauses.append("severity<>'info'")
    elif severity != "all":
        clauses.append("severity=?")
        parameters.append(severity)
    if category != "all":
        clauses.append("category=?")
        parameters.append(category)
    if query.strip():
        clauses.append(
            "lower(title || ' ' || detail || ' ' || coalesce(page_url,'')) LIKE ?"
        )
        parameters.append(f"%{query.strip().lower()}%")
    where_clause = " AND ".join(clauses)
    with connection() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM findings WHERE {where_clause}",
            parameters,
        ).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM findings WHERE {where_clause} {ordering} LIMIT ? OFFSET ?",
            [*parameters, limit, offset],
        ).fetchall()
        page_rows = conn.execute(
            "SELECT url,priority,links_json FROM pages WHERE scan_id=?",
            (scan_id,),
        ).fetchall()
    pages = [
        {"url": row["url"], "priority": row["priority"], "links": json.loads(row["links_json"] or "[]")}
        for row in page_rows
    ]
    priority_by_url = {page["url"]: page["priority"] for page in pages}
    findings = [
        {
            **enrich_finding(row_to_dict(row)),
            "page_priority": priority_by_url.get(row["page_url"], "standard"),
        }
        for row in rows
    ]
    findings = attach_discovery_sources(pages, findings)
    return {
        "items": findings,
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(findings) < total,
    }


def page_details(scan_id: str, page_id: str) -> dict | None:
    with connection() as conn:
        row = conn.execute(
            "SELECT * FROM pages WHERE scan_id=? AND id=?",
            (scan_id, page_id),
        ).fetchone()
        if not row:
            return None
        page = row_to_dict(row)
        finding_rows = conn.execute(
            """SELECT * FROM findings WHERE scan_id=? AND page_url=?
            ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                WHEN 'medium' THEN 2 WHEN 'low' THEN 3 ELSE 4 END, title""",
            (scan_id, page["url"]),
        ).fetchall()
        source_rows = conn.execute(
            "SELECT url,links_json FROM pages WHERE scan_id=?",
            (scan_id,),
        ).fetchall()
    source_pages = [
        {"url": source["url"], "links": json.loads(source["links_json"] or "[]")}
        for source in source_rows
    ]
    findings = [
        {**enrich_finding(row_to_dict(finding)), "page_priority": page.get("priority", "standard")}
        for finding in finding_rows
    ]
    page["findings"] = attach_discovery_sources(source_pages, findings)
    return page


def scan_overview(scan_id: str) -> dict | None:
    scan = get_scan(scan_id)
    if not scan:
        return None
    with connection() as conn:
        findings = conn.execute(
            "SELECT * FROM findings WHERE scan_id=?",
            (scan_id,),
        ).fetchall()
        priorities = conn.execute(
            "SELECT url,priority FROM pages WHERE scan_id=?",
            (scan_id,),
        ).fetchall()
        baseline = conn.execute(
            """SELECT id, created_at, completed_at, summary_json
            FROM scans
            WHERE url=? AND id<>? AND status='completed' AND created_at<?
            ORDER BY created_at DESC LIMIT 1""",
            (scan["url"], scan_id, scan["created_at"]),
        ).fetchone()
        baseline_findings = (
            conn.execute("SELECT * FROM findings WHERE scan_id=?", (baseline["id"],)).fetchall()
            if baseline
            else []
        )
    priority_by_url = {row["url"]: row["priority"] for row in priorities}
    enriched = [
        {
            **enrich_finding(row_to_dict(row)),
            "page_priority": priority_by_url.get(row["page_url"], "standard"),
        }
        for row in findings
    ]
    scan["issue_groups"] = build_issue_groups(enriched)
    scan["page_count"] = len(priorities)
    scan["finding_count"] = len(findings)
    if baseline and scan["status"] == "completed":
        baseline_groups = build_issue_groups(
            [enrich_finding(row_to_dict(row)) for row in baseline_findings]
        )
        comparison = compare_issue_groups(scan["issue_groups"], baseline_groups)
        baseline_summary = json.loads(baseline["summary_json"] or "{}")
        comparison["baseline"] = {
            "id": baseline["id"],
            "created_at": baseline["created_at"],
            "completed_at": baseline["completed_at"],
            "health_score": baseline_summary.get("health_score"),
        }
        scan["comparison"] = comparison
    elif scan["status"] == "completed":
        scan["comparison"] = {
            "baseline": None,
            "counts": {"new": 0, "fixed": 0, "recurring": 0, "unchanged": 0},
            "items": [],
        }
    else:
        scan["comparison"] = None
    return scan


def delete_scan(scan_id: str) -> tuple[bool, list[str]]:
    with connection() as conn:
        exists = conn.execute("SELECT 1 FROM scans WHERE id=?", (scan_id,)).fetchone()
        if not exists:
            return False, []
        screenshot_rows = conn.execute(
            "SELECT screenshot_path, responsive_json FROM pages WHERE scan_id=?",
            (scan_id,),
        ).fetchall()
        conn.execute("DELETE FROM findings WHERE scan_id=?", (scan_id,))
        conn.execute("DELETE FROM pages WHERE scan_id=?", (scan_id,))
        conn.execute("DELETE FROM scans WHERE id=?", (scan_id,))
    screenshots = []
    for row in screenshot_rows:
        if row["screenshot_path"]:
            screenshots.append(row["screenshot_path"])
        responsive = json.loads(row["responsive_json"] or "{}")
        screenshots.extend(
            viewport["screenshot_path"]
            for viewport in responsive.values()
            if viewport.get("screenshot_path")
        )
    return True, sorted(set(screenshots))


def attach_discovery_sources(pages: list[dict], findings: list[dict]) -> list[dict]:
    sources_by_url: dict[str, set[str]] = {}
    for page in pages:
        source_url = page["url"]
        for link in page.get("links", []):
            if isinstance(link, str) and link != source_url:
                sources_by_url.setdefault(link, set()).add(source_url)
    return [
        {
            **finding,
            "discovered_on": (
                sorted(sources_by_url.get(finding.get("page_url"), set()))
                if finding.get("category") in {"page", "content", "indexing"}
                else []
            ),
        }
        for finding in findings
    ]


def scan_details(scan_id: str) -> dict | None:
    scan = get_scan(scan_id)
    if not scan:
        return None
    with connection() as conn:
        pages = conn.execute("SELECT * FROM pages WHERE scan_id=? ORDER BY url", (scan_id,)).fetchall()
        findings = conn.execute(
            """SELECT * FROM findings WHERE scan_id=?
            ORDER BY
                CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'low' THEN 3 WHEN 'info' THEN 4 ELSE 5 END,
                CASE category WHEN 'network' THEN 1 ELSE 0 END,
                title""",
            (scan_id,),
        ).fetchall()
        baseline = conn.execute(
            """SELECT id, created_at, completed_at, summary_json
            FROM scans
            WHERE url=? AND id<>? AND status='completed' AND created_at<?
            ORDER BY created_at DESC LIMIT 1""",
            (scan["url"], scan_id, scan["created_at"]),
        ).fetchone()
        baseline_findings = (
            conn.execute("SELECT * FROM findings WHERE scan_id=?", (baseline["id"],)).fetchall()
            if baseline
            else []
        )
    scan["pages"] = [row_to_dict(row) for row in pages]
    enriched_findings = [enrich_finding(row_to_dict(row)) for row in findings]
    priority_by_url = {page["url"]: page.get("priority", "standard") for page in scan["pages"]}
    enriched_findings = [
        {**finding, "page_priority": priority_by_url.get(finding.get("page_url"), "standard")}
        for finding in enriched_findings
    ]
    scan["findings"] = attach_discovery_sources(scan["pages"], enriched_findings)
    scan["issue_groups"] = build_issue_groups(scan["findings"])
    if baseline and scan["status"] == "completed":
        baseline_groups = build_issue_groups([enrich_finding(row_to_dict(row)) for row in baseline_findings])
        comparison = compare_issue_groups(scan["issue_groups"], baseline_groups)
        baseline_summary = json.loads(baseline["summary_json"] or "{}")
        comparison["baseline"] = {
            "id": baseline["id"],
            "created_at": baseline["created_at"],
            "completed_at": baseline["completed_at"],
            "health_score": baseline_summary.get("health_score"),
        }
        scan["comparison"] = comparison
    elif scan["status"] == "completed":
        scan["comparison"] = {"baseline": None, "counts": {"new": 0, "fixed": 0, "recurring": 0, "unchanged": 0}, "items": []}
    else:
        scan["comparison"] = None
    return scan

from pathlib import Path
from datetime import datetime, timedelta, timezone
import re
import secrets
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import store
from .crawler import SCREENSHOTS, cancel_scan, normalize_url, pause_scan, resume_scan, start_scan
from .health import (
    HEALTH_METHOD_VERSION,
    calculate_health_score,
    category_coverage,
    health_summary_payload,
)
from .insights import build_issue_groups, compare_issue_groups
from .quality import DEFAULT_CONTENT_CHECKS
from .reports import REPORT_KINDS, build_csv, build_html, build_pdf, build_xlsx, report_filename

app = FastAPI(title="BugBuster Website Explorer", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"], allow_methods=["*"], allow_headers=["*"])
SCREENSHOTS.mkdir(parents=True, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=SCREENSHOTS), name="evidence")


class ContentChecks(BaseModel):
    duplicate_titles: bool = True
    duplicate_descriptions: bool = True
    headings: bool = True
    broken_internal_links: bool = True
    empty_pages: bool = True
    placeholder_text: bool = True
    short_content: bool = True
    missing_image_alt: bool = True
    canonical_tags: bool = True
    short_content_words: int = Field(default=100, ge=20, le=500)


class ScanOptions(BaseModel):
    page_health: bool = True
    performance: bool = True
    seo: bool = True
    content_quality: bool = True
    screenshots: bool = True
    responsive: bool = False
    accessibility: bool = False
    console: bool = False
    network: bool = False
    sitemap_indexing: bool = False
    template_intelligence: bool = False
    passive_security: bool = False


class ScanRequest(BaseModel):
    url: str
    authorized: bool
    max_pages: int = Field(default=25, ge=1, le=250)
    max_depth: int = Field(default=3, ge=0, le=8)
    content_checks: ContentChecks = Field(default_factory=ContentChecks)
    scan_options: ScanOptions = Field(default_factory=ScanOptions)


class PagePriorityRequest(BaseModel):
    page_url: str
    priority: str


class ReportSettingsRequest(BaseModel):
    agency_name: str | None = Field(default=None, max_length=100)
    report_title: str | None = Field(default=None, max_length=140)
    brand_color: str = "#187249"


class ShareReportRequest(BaseModel):
    report_kind: str = "executive"
    expires_hours: int = Field(default=168, ge=1, le=720)
    comparison_scan_id: str | None = None


def report_comparison(scan: dict, comparison_scan_id: str | None) -> dict | None:
    if not comparison_scan_id:
        return None
    if comparison_scan_id == "__previous__":
        return scan.get("comparison")
    baseline = store.scan_details(comparison_scan_id)
    if not baseline:
        raise HTTPException(404, "Comparison scan not found.")
    if baseline["url"] != scan["url"]:
        raise HTTPException(400, "Reports can only compare scans of the same normalized website URL.")
    scoped_baseline_groups = build_issue_groups(
        store.filter_findings_for_scope(baseline.get("findings", []), scan)
    )
    comparison = compare_issue_groups(scan.get("issue_groups", []), scoped_baseline_groups)
    comparison["baseline"] = {
        "id": baseline["id"],
        "created_at": baseline["created_at"],
        "completed_at": baseline.get("completed_at"),
        "health_score": baseline.get("summary", {}).get("health_score"),
    }
    comparison["score"] = store.score_comparison(scan, baseline)
    return comparison


def recalculate_scan_health(scan_id: str) -> dict:
    scan = store.scan_details(scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found.")
    summary = dict(scan.get("summary") or {})
    options = scan.get("scan_options") or {}
    checks = scan.get("content_checks") or {}
    score, details = calculate_health_score(
        scan.get("findings", []),
        summary.get("pages_scanned", len(scan.get("pages", []))),
        summary.get("network_requests", 0),
        summary.get("actionable_failed_requests", summary.get("failed_requests", 0)),
        page_priorities={page["url"]: page.get("priority", "standard") for page in scan.get("pages", [])},
        scan_options=options,
        content_checks=checks,
        max_pages=scan.get("max_pages"),
    )
    score_enabled = any(value > 0 for value in category_coverage(options, checks).values())
    summary.update(health_summary_payload(score, details, score_enabled))
    store.update_scan(scan_id, summary=summary)
    return summary


@app.get("/health")
def health() -> dict:
    return {"status": "healthy"}


@app.get("/api/scans")
def list_scans() -> list[dict]:
    return store.list_scans()


@app.post("/api/scans")
async def create_scan(request: ScanRequest) -> dict:
    parsed = urlparse(request.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(400, "Enter a full http:// or https:// website URL.")
    if parsed.username or parsed.password:
        raise HTTPException(400, "URLs containing credentials are not allowed.")
    if not request.authorized:
        raise HTTPException(400, "You must confirm authorization to scan this website.")
    try:
        normalized_url = normalize_url(request.url)
    except ValueError:
        raise HTTPException(400, "The URL contains an invalid port.") from None
    content_checks = {**DEFAULT_CONTENT_CHECKS, **request.content_checks.model_dump()}
    scan_options = request.scan_options.model_dump()
    scan = store.create_scan(
        normalized_url,
        request.max_pages,
        request.max_depth,
        content_checks,
        scan_options,
    )
    start_scan(
        scan["id"], scan["url"], scan["max_pages"], scan["max_depth"],
        content_checks, scan_options,
    )
    return scan


@app.get("/api/scans/{scan_id}")
def get_scan(scan_id: str) -> dict:
    stored_scan = store.get_scan(scan_id)
    if not stored_scan:
        raise HTTPException(404, "Scan not found.")
    if (
        stored_scan["status"] == "completed"
        and stored_scan.get("summary", {}).get("health_method_version") != HEALTH_METHOD_VERSION
    ):
        recalculate_scan_health(scan_id)
    return store.scan_overview(scan_id)


@app.get("/api/scans/{scan_id}/status")
def get_scan_status(scan_id: str) -> dict:
    scan = store.scan_status(scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found.")
    return scan


@app.post("/api/scans/{scan_id}/pause")
async def pause_active_scan(scan_id: str) -> dict:
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found.")
    if scan["status"] == "paused":
        return store.scan_status(scan_id)
    if scan["status"] not in {"queued", "running"}:
        raise HTTPException(409, "Only a queued or running scan can be paused.")
    if not pause_scan(scan_id):
        raise HTTPException(409, "This scan is no longer active in the current backend process.")
    return store.scan_status(scan_id)


@app.post("/api/scans/{scan_id}/resume")
async def resume_paused_scan(scan_id: str) -> dict:
    scan = store.get_scan(scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found.")
    if scan["status"] in {"queued", "running"}:
        return store.scan_status(scan_id)
    if scan["status"] != "paused":
        raise HTTPException(409, "Only a paused scan can be resumed.")
    if not resume_scan(scan_id):
        raise HTTPException(
            409,
            "This paused scan cannot be resumed because its original backend process is no longer running.",
        )
    return store.scan_status(scan_id)


@app.get("/api/scans/{scan_id}/pages")
def get_scan_pages(
    scan_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> dict:
    if not store.get_scan(scan_id):
        raise HTTPException(404, "Scan not found.")
    return store.page_summaries(scan_id, offset, limit)


@app.get("/api/scans/{scan_id}/findings")
def get_scan_findings(
    scan_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(250, ge=1, le=500),
    severity: str = Query("all"),
    category: str = Query("all"),
    query: str = Query("", max_length=200),
) -> dict:
    if not store.get_scan(scan_id):
        raise HTTPException(404, "Scan not found.")
    if severity not in {"all", "issues", "critical", "high", "medium", "low", "info"}:
        raise HTTPException(400, "Invalid finding severity.")
    return store.findings_page(scan_id, offset, limit, severity, category, query)


@app.get("/api/scans/{scan_id}/pages/{page_id}")
def get_scan_page(scan_id: str, page_id: str) -> dict:
    page = store.page_details(scan_id, page_id)
    if not page:
        raise HTTPException(404, "Page not found.")
    return page


@app.put("/api/scans/{scan_id}/pages/priority")
def update_page_priority(scan_id: str, request: PagePriorityRequest) -> dict:
    if request.priority not in {"critical", "high_value", "standard"}:
        raise HTTPException(400, "Priority must be critical, high_value, or standard.")
    if not store.set_page_priority(scan_id, request.page_url, request.priority):
        raise HTTPException(404, "Scan page not found.")
    scan = store.get_scan(scan_id)
    summary = recalculate_scan_health(scan_id) if scan and scan.get("status") == "completed" else None
    return {
        "page_url": request.page_url,
        "priority": request.priority,
        "health_score": summary.get("health_score") if summary else None,
    }


@app.put("/api/scans/{scan_id}/report-settings")
def update_report_settings(scan_id: str, request: ReportSettingsRequest) -> dict:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", request.brand_color):
        raise HTTPException(400, "Brand color must be a six-digit hexadecimal color.")
    if not store.update_report_settings(
        scan_id,
        request.agency_name.strip() if request.agency_name else None,
        request.report_title.strip() if request.report_title else None,
        request.brand_color.lower(),
    ):
        raise HTTPException(404, "Scan not found.")
    return request.model_dump()


@app.get("/api/scans/{scan_id}/reports/{file_format}")
def download_report(
    scan_id: str,
    file_format: str,
    kind: str = Query(default="executive"),
    compare_to: str | None = Query(default=None),
) -> Response:
    if kind not in REPORT_KINDS:
        raise HTTPException(400, "Report kind must be executive, qa, or developer.")
    scan = store.scan_details(scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found.")
    comparison = report_comparison(scan, compare_to)
    builders = {
        "pdf": (build_pdf, "application/pdf"),
        "csv": (build_csv, "text/csv; charset=utf-8"),
        "xlsx": (build_xlsx, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    }
    if file_format not in builders:
        raise HTTPException(400, "Report format must be pdf, csv, or xlsx.")
    builder, media_type = builders[file_format]
    content = builder(scan, kind, comparison)
    filename = report_filename(scan, kind, file_format)
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/scans/{scan_id}/report-shares")
def share_report(scan_id: str, payload: ShareReportRequest, request: Request) -> dict:
    if payload.report_kind not in REPORT_KINDS:
        raise HTTPException(400, "Report kind must be executive, qa, or developer.")
    scan = store.scan_details(scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found.")
    report_comparison(scan, payload.comparison_scan_id)
    token = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=payload.expires_hours)
    store.create_report_share(
        token,
        scan_id,
        payload.report_kind,
        payload.comparison_scan_id,
        expires_at.isoformat(),
    )
    return {
        "url": str(request.url_for("shared_report", token=token)),
        "expires_at": expires_at.isoformat(),
        "read_only": True,
    }


@app.get("/reports/shared/{token}", response_class=HTMLResponse, name="shared_report")
def shared_report(token: str) -> HTMLResponse:
    share = store.get_report_share(token)
    if not share:
        raise HTTPException(404, "Shared report not found.")
    expires_at = datetime.fromisoformat(share["expires_at"])
    if expires_at <= datetime.now(timezone.utc):
        raise HTTPException(410, "This shared report link has expired.")
    scan = store.scan_details(share["scan_id"])
    if not scan:
        raise HTTPException(404, "The scan for this shared report no longer exists.")
    comparison = report_comparison(scan, share.get("comparison_scan_id"))
    return HTMLResponse(build_html(scan, share["report_kind"], comparison))


@app.delete("/api/scans/{scan_id}")
async def delete_scan(scan_id: str) -> dict:
    await cancel_scan(scan_id)
    deleted, screenshots = store.delete_scan(scan_id)
    if not deleted:
        raise HTTPException(404, "Scan not found.")
    for screenshot in screenshots:
        (SCREENSHOTS / Path(screenshot).name).unlink(missing_ok=True)
    return {"deleted": scan_id}

from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import store
from .crawler import SCREENSHOTS, normalize_url, start_scan

app = FastAPI(title="BugBuster Website Explorer", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5174", "http://127.0.0.1:5174"], allow_methods=["*"], allow_headers=["*"])
SCREENSHOTS.mkdir(parents=True, exist_ok=True)
app.mount("/evidence", StaticFiles(directory=SCREENSHOTS), name="evidence")


class ScanRequest(BaseModel):
    url: str
    authorized: bool
    max_pages: int = Field(default=25, ge=1, le=250)
    max_depth: int = Field(default=3, ge=0, le=8)


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
    scan = store.create_scan(normalized_url, request.max_pages, request.max_depth)
    start_scan(scan["id"], scan["url"], scan["max_pages"], scan["max_depth"])
    return scan


@app.get("/api/scans/{scan_id}")
def get_scan(scan_id: str) -> dict:
    scan = store.scan_details(scan_id)
    if not scan:
        raise HTTPException(404, "Scan not found.")
    return scan

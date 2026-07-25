# BugBuster Website Explorer

An authorized, read-only website health scanner. It crawls same-domain public pages and reports broken links, page-quality issues, browser console errors, failed network requests, and screenshots.

## Safety defaults

- Scan only the submitted domain.
- Never log in, submit a form, make a purchase, or click destructive actions.
- Use only on websites you own or are authorized to test.
- Default limit: 25 pages and a maximum crawl depth of 3.
- Published `robots.txt` rules and crawl delays are respected.
- Navigation is rate-limited to at least 750 ms between pages.
- Cross-domain redirects are blocked and reported as evidence.

## Run locally

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
python -m uvicorn app.main:app --reload --port 8100
```

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open the URL shown by Vite, usually `http://localhost:5174`.

### Tests

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v

cd ..\frontend
npm test
npm run build
```

## MVP capabilities

- Add an authorized website URL and scan limits.
- Crawl same-domain pages with Playwright.
- Capture screenshots, console errors, failed network requests, titles, H1s, and meta descriptions.
- Report broken links, failed page loads, page metadata issues, console/network errors, and slow pages.
- Filter findings by severity, category, or search text.
- Open a page evidence view with metadata, redirects, errors, console messages, failed requests, and its screenshot.

## Crawl policy decisions

- The original normalized scheme, host, and port define the allowed navigation boundary. A redirect outside that boundary is stopped and reported.
- A missing `robots.txt` means no rules were published. A `401`, `403`, `5xx`, or unreadable robots file stops the crawl conservatively.
- URL fragments, default ports, tracking parameters, duplicate trailing slashes, dot segments, and query ordering are normalized before queueing.
- Page navigation times out after 30 seconds and the timeout is stored separately from HTTP failures.

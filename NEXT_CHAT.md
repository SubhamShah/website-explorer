# Next Codex chat handoff

We are building a separate product named **BugBuster Website Explorer** in this folder. It must remain independent from BugBuster AI Recorder.

The MVP phases 1–4 have been scaffolded:

- FastAPI backend on port `8100`.
- Playwright same-domain, read-only crawler.
- SQLite scan, page, and finding storage for local development.
- React/Vite dashboard on port `5174`.
- Crawl results: pages, screenshots, console warnings/errors, failed network requests, metadata findings, slow-page warnings, and a health score.

Safety requirements:

- Only scan websites the customer owns or is authorized to test.
- Stay on the original domain.
- Never log in, submit forms, purchase, delete, publish, or create accounts.
- Keep limits for pages and crawl depth.

Next implementation work:

1. Install and run the project using `README.md`.
2. Test scanning an authorized public website.
3. Improve crawler resilience: robots policy decision, redirect handling, timeout reporting, rate limiting, and duplicate URL normalization.
4. Add a clearer findings filter and page-detail evidence view.
5. Add tests before expanding to accessibility and scheduled scans.

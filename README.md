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

Large scans use lightweight status polling and never start a second refresh while the previous one is active. Completed results load as a compact overview, 50 page summaries, and 250 filtered findings at a time. Full console, network, responsive, and content evidence is fetched only when a page is expanded, while reports continue to use all saved evidence.

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
- Choose scan coverage before starting. Common checks are recommended by default, while responsive testing, accessibility/ARIA, console messages, network/API recording, passive security posture, sitemap/indexing, and template intelligence are opt-in.
- Unchecked result categories are not collected and do not appear in the dashboard or generated reports. Content-quality checks have their own detailed checkboxes.
- Crawl same-domain pages with Playwright.
- Capture screenshots, console errors, complete network activity, titles, H1s, and meta descriptions.
- Report broken links, failed page loads, page metadata issues, console/network errors, and slow pages.
- Review passed and failed API/resource responses as network findings and page evidence.
- Classify network activity as first-party, third-party functional, advertising/analytics, security challenge, live chat, scanner-blocked, or browser-aborted before assigning severity.
- Correlate generic browser-console resource errors with their network request, downgrade scanner-generated Turnstile warnings, and avoid penalizing the same failure twice.
- Default to actionable SEO, performance, console, page, and network issues while keeping passed requests available through the findings filter.
- Filter findings on the backend by severity, category, or search text and load them in manageable batches inside an independently scrollable panel.
- Browse paginated crawled pages in a separate scrollable panel and fetch full evidence only when a page is expanded inline.
- Follow the live scanned-page count in the progress banner and delete scans with their stored evidence from scan history.
- Mark pages as Critical, High value, or Standard. Checkout, login, signup, registration, payment, and pricing paths are suggested as Critical; product and service paths are suggested as High value.
- Preserve manual page-importance choices for the same URL in future scans and rank root causes using severity plus page importance.
- Create audience-specific Executive, QA, or Developer reports with optional agency name, report title, and brand color.
- Download reports as PDF, UTF-8 CSV, or native `.xlsx` workbooks, including New/Fixed/Recurring/Unchanged status when two scans are compared.
- Create read-only HTML report links that expire after 24 hours, 7 days, or 30 days. A link is publicly reachable only when the backend itself is hosted on a public HTTPS address.
- Render every successfully loaded page at Desktop (1440×900), Tablet (768×1024), and Mobile (390×844) sizes and retain a full-page screenshot for each viewport.
- Detect responsive horizontal overflow, hidden primary content, overlapping interactive elements, text below 12px, navigation that disappears without a menu control, and images extending outside the viewport.
- Run established axe-core accessibility checks and retain the WCAG criteria and level, affected selector, DOM snippet, screenshot context, plain-language impact, and recommended repair.
- Recognize likely shared page templates and global components, then turn repeated symptoms into one developer task with affected-page count and confidence.

## Responsive testing

Responsive findings are stored under the `responsive` category and appear in grouped findings, page evidence, exports, and scan comparisons. Expand any page to compare its three viewport screenshots and review individual pass/fail signals.

The checks are diagnostic rather than visual guesses:

- Horizontal overflow compares rendered document width with viewport width and names likely overflowing elements.
- Overlap detection checks visible interactive controls and ignores parent-child element pairs.
- Hidden-content detection checks primary `main` and `h1` landmarks.
- Broken-navigation detection compares tablet/mobile navigation with desktop and does not report a failure when a visible menu control is available.
- Small-text detection reports visible rendered text below 12px.
- Off-screen image detection reports visible images crossing the horizontal viewport boundary.

Responsive findings contribute to the Responsive Experience category when that optional check is selected. They are prioritized using severity and the page’s Critical, High value, or Standard importance.

## Accessibility testing

Each successfully rendered page is inspected using the established `axe-core` engine through `axe-playwright-python`. The scanner runs automated WCAG 2.0, 2.1, and 2.2 Level A/AA checks plus axe best-practice rules. Accessibility findings include:

- axe rule identifier, impact, WCAG criteria, and conformance level.
- The affected CSS selector and a bounded DOM snippet.
- The desktop screenshot as visual context when available.
- A quick locator for nontechnical users: the exact problem, nearby page section, readable element name, affected-user impact, and shortest recommended fix.
- A cropped image of the affected element when its axe selector can be replayed; selector, DOM, raw axe output, and WCAG data remain collapsed under developer details.
- Plain-language user impact, recommended action, verification method, and official axe rule guidance.
- Affected-page grouping in the root-cause view and accessibility evidence inside each expanded page.

The crawler retains at most 30 affected elements per rule on a page and reports how many additional elements were omitted, preventing extremely repetitive pages from creating unbounded results. Automated testing does not replace keyboard, screen-reader, zoom, and end-to-end task testing.

After pulling this feature, install the updated backend dependency before restarting:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Template and component intelligence

The crawler records a bounded structural signature from rendered landmarks such as the header, navigation, main content, article, forms, and footer. URL families identify likely blog articles, blog categories, products, services, news, and other repeated detail-page layouts.

When the same root cause appears on at least two pages with the same structural template signature, the grouped finding identifies the likely shared template. Accessibility selectors that point to a repeated header, navigation, footer, or consent control are identified as likely shared components. The dashboard presents a **fix once, verify all affected pages** task with High or Medium inference confidence; it does not claim to know a source-code filename without repository integration.

## Sitemap, indexing, and content quality

Each scan reads same-domain sitemap locations published in `robots.txt` and checks the conventional `/sitemap.xml`. Sitemap indexes are followed up to eight documents and 5,000 discovered URLs. Sitemap-discovered pages may be added to the crawl queue, but the configured maximum-page and depth limits still apply.

The completed scan reconciles:

- Crawled pages with XML sitemap URLs.
- Canonical tags and page-level `noindex` directives.
- Sitemap URLs blocked by the published robots policy.
- Sitemap URLs that returned errors within the configured scan limit.
- Sitemap pages with no internal links from another crawled page.
- Internally linked pages missing from the sitemap.
- Sitemap pages that also declare `noindex`.

The start-scan form exposes configurable checks for duplicate titles, duplicate descriptions, missing or multiple H1 headings, broken internal links, empty pages, placeholder text, extremely short content, missing image alternative text, and incorrect canonical tags. The short-content word threshold is configurable from 20 to 500 visible words.

The dashboard distinguishes a valid sitemap from an empty or invalid response, a missing sitemap, and a sitemap request failure. When no valid page URLs can be parsed, comparison-dependent metrics show **Not available** instead of a misleading zero, while independent checks such as broken links and `noindex` pages remain available. Sitemap URLs outside the maximum-page limit are counted as **unchecked** rather than reported as passing. Content and indexing findings appear in grouped findings, page evidence, scan comparisons, and every report format.

## Important-page monitoring

Page importance changes prioritization without hiding lower-value evidence:

- **Critical:** checkout, cart, payment, login, pricing, signup, and registration journeys.
- **High value:** product, service, solution, feature, and plan pages.
- **Standard:** articles, documentation, and general informational content.

Users can override every suggestion from the Pages section. Overrides persist for future scans of the same normalized website and page URL.

## Reports

- **Executive:** grouped root causes, business impact, ownership, affected-page counts, and recommended actions.
- **QA:** actionable findings, page importance, affected URL, impact, and verification guidance.
- **Developer:** all captured findings, including informational network and console evidence.

The comparison selector defaults to **Current scan only**. Users can instead choose the immediately previous completed scan or a specific older scan of the same normalized URL; each option shows its scan date, health score, and page count. Expiring share links are unguessable, read-only, marked `noindex`, and become unavailable after their stored expiry time.

PDF reports use an audience-specific document layout rather than dense table rows. Every issue has a separate heading, wrapped evidence, labeled impact and remediation fields, an affected-pages section, visual dividers, and automatic page headers, footers, and page breaks.

## Health score

**BugBuster Health Score 2.1** is a transparent product score, not an international standard. It combines seven separately visible categories: Reliability, Performance, SEO and Indexing, Accessibility, Content Quality, Responsive Experience, and Passive Security. Only checks selected for that scan participate in the calculation.

Passive security posture is deliberately read-only. It inspects HTTPS use, common protective response headers, insecure page resources and form destinations, first-party sensitive-cookie protections, and unnecessary server-version disclosure. It does not send attack payloads, submit forms, test credentials, bypass access controls, or attempt injection; those active capabilities belong in a separately authorized security-scanner product.

Each actionable finding receives a severity weight and a business-page multiplier:

- Critical pages multiply risk by 3.
- High-value pages multiply risk by 2.
- Standard pages multiply risk by 1.

Category scores combine issue prevalence with the highest individual business impact, then normalize by pages scanned. The overall score is a weighted average of the checked categories. The dashboard shows check coverage, whether the crawl reached its page limit, the three largest score impacts, and the scoring-method version. Informational findings and console messages already linked to a network failure do not reduce the score.

Health-score changes are shown between scans only when page limits, depth, selected checks, content-check settings, and scoring versions match. Issue-level changes remain available when score comparison is incompatible.

## Crawl policy decisions

- The original normalized scheme, host, and port define the allowed navigation boundary. A redirect outside that boundary is stopped and reported.
- A missing `robots.txt` means no rules were published. A `401`, `403`, `5xx`, or unreadable robots file stops the crawl conservatively.
- URL fragments, default ports, tracking parameters, duplicate trailing slashes, dot segments, and query ordering are normalized before queueing.
- Page navigation times out after 30 seconds and the timeout is stored separately from HTTP failures.

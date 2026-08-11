from pathlib import Path


VIEWPORTS = (
    ("desktop", "Desktop", 1440, 900),
    ("tablet", "Tablet", 768, 1024),
    ("mobile", "Mobile", 390, 844),
)

LAYOUT_ANALYSIS_SCRIPT = r"""
() => {
  const width = window.innerWidth;
  const ancestors = (node) => {
    const result = [];
    for (let current = node; current instanceof Element; current = current.parentElement) {
      result.push(current);
    }
    return result;
  };
  const visible = (node) => {
    if (!(node instanceof Element)) return false;
    const rect = node.getBoundingClientRect();
    if (rect.width <= 1 || rect.height <= 1) return false;
    return ancestors(node).every(current => {
      const style = getComputedStyle(current);
      return !current.hidden && style.display !== 'none' &&
        style.visibility !== 'hidden' && style.visibility !== 'collapse' &&
        Number(style.opacity || 1) > 0.02;
    });
  };
  const describe = (node) => {
    const id = node.id ? `#${node.id}` : '';
    const classes = [...node.classList].slice(0, 2).map(value => `.${value}`).join('');
    const text = (node.getAttribute('aria-label') || node.textContent || '')
      .trim().replace(/\s+/g, ' ').slice(0, 70);
    return `${node.tagName.toLowerCase()}${id}${classes}${text ? ` "${text}"` : ''}`;
  };
  const all = [...document.querySelectorAll('body *')];
  const visibleNodes = all.filter(visible);
  const documentWidth = Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0);
  const clipsHorizontally = (node) => ancestors(node).slice(1).some(ancestor => {
    const style = getComputedStyle(ancestor);
    if (!['hidden', 'clip'].includes(style.overflowX)) return false;
    const outer = ancestor.getBoundingClientRect();
    const inner = node.getBoundingClientRect();
    return inner.left < outer.left - 3 || inner.right > outer.right + 3;
  });
  const visibleRect = (node) => {
    const source = node.getBoundingClientRect();
    const rect = {left: source.left, right: source.right, top: source.top, bottom: source.bottom};
    for (const ancestor of ancestors(node).slice(1)) {
      const style = getComputedStyle(ancestor);
      if (!['hidden', 'clip', 'auto', 'scroll'].includes(style.overflowX) &&
          !['hidden', 'clip', 'auto', 'scroll'].includes(style.overflowY)) continue;
      const clip = ancestor.getBoundingClientRect();
      if (['hidden', 'clip', 'auto', 'scroll'].includes(style.overflowX)) {
        rect.left = Math.max(rect.left, clip.left);
        rect.right = Math.min(rect.right, clip.right);
      }
      if (['hidden', 'clip', 'auto', 'scroll'].includes(style.overflowY)) {
        rect.top = Math.max(rect.top, clip.top);
        rect.bottom = Math.min(rect.bottom, clip.bottom);
      }
    }
    rect.width = Math.max(0, rect.right - rect.left);
    rect.height = Math.max(0, rect.bottom - rect.top);
    return rect;
  };
  const overflowElements = visibleNodes
    .filter(node => {
      const rect = node.getBoundingClientRect();
      return rect.left < -3 || rect.right > width + 3;
    })
    .slice(0, 10)
    .map(describe);
  const unreadable = visibleNodes
    .filter(node => {
      const text = (node.textContent || '').trim();
      if (text.length < 2 || node.children.length > 3) return false;
      return Number.parseFloat(getComputedStyle(node).fontSize || '16') < 12;
    })
    .slice(0, 10)
    .map(node => `${describe(node)} (${getComputedStyle(node).fontSize})`);
  const outsideImages = [...document.images]
    .filter(visible)
    .filter(image => {
      const rect = image.getBoundingClientRect();
      const extendsOutside = rect.left < -3 || rect.right > width + 3;
      // Carousels commonly position upcoming slides beyond their clipped track.
      // Only report an image when it contributes to real page-level scrolling.
      return extendsOutside && documentWidth > width + 4 && !clipsHorizontally(image);
    })
    .slice(0, 10)
    .map(describe);
  const interactive = [...document.querySelectorAll(
    'a[href],button,input,select,textarea,[role="button"],[role="link"]'
  )].filter(visible).slice(0, 140);
  const actionIdentity = (node) => {
    const href = node instanceof HTMLAnchorElement ? node.href : '';
    const label = (node.getAttribute('aria-label') || node.textContent || node.getAttribute('name') || '')
      .trim().replace(/\s+/g, ' ').toLowerCase();
    return `${node.tagName.toLowerCase()}|${href}|${label}`;
  };
  const overlaps = [];
  for (let first = 0; first < interactive.length && overlaps.length < 10; first += 1) {
    const a = interactive[first];
    const ar = visibleRect(a);
    if (ar.width <= 1 || ar.height <= 1) continue;
    for (let second = first + 1; second < interactive.length && overlaps.length < 10; second += 1) {
      const b = interactive[second];
      if (a.contains(b) || b.contains(a)) continue;
      const br = visibleRect(b);
      if (br.width <= 1 || br.height <= 1) continue;
      const overlapWidth = Math.max(0, Math.min(ar.right, br.right) - Math.max(ar.left, br.left));
      const overlapHeight = Math.max(0, Math.min(ar.bottom, br.bottom) - Math.max(ar.top, br.top));
      const overlapArea = overlapWidth * overlapHeight;
      const smallerArea = Math.min(ar.width * ar.height, br.width * br.height);
      const sameAction = actionIdentity(a) === actionIdentity(b);
      const effectivelyStacked = Math.abs(ar.left - br.left) <= 2 &&
        Math.abs(ar.top - br.top) <= 2 && Math.abs(ar.width - br.width) <= 2 &&
        Math.abs(ar.height - br.height) <= 2;
      if (sameAction && effectivelyStacked) continue;
      if (overlapWidth >= 8 && overlapHeight >= 8 && smallerArea > 0 && overlapArea / smallerArea >= 0.25) {
        overlaps.push(`${describe(a)} overlaps ${describe(b)}`);
      }
    }
  }
  const menuControl = [...document.querySelectorAll('button,[role="button"],summary')]
    .filter(visible)
    .some(node => /menu|navigation|nav/i.test(
      `${node.getAttribute('aria-label') || ''} ${node.getAttribute('title') || ''} ${node.textContent || ''}`
    ));
  const hiddenLandmarks = ['h1', 'main']
    .filter(selector => {
      const matches = [...document.querySelectorAll(selector)];
      return matches.length > 0 && !matches.some(visible);
    });
  return {
    document_width: documentWidth,
    viewport_width: width,
    overflow_elements: overflowElements,
    unreadable_text: unreadable,
    overlapping_elements: overlaps,
    images_outside_viewport: outsideImages,
    hidden_content: hiddenLandmarks,
    visible_nav_links: [...document.querySelectorAll('nav a[href],header a[href]')].filter(visible).length,
    visible_interactive_elements: interactive.length,
    menu_control_visible: menuControl,
  };
}
"""


async def capture_responsive_evidence(page: object, screenshot_dir: Path, filename_prefix: str) -> dict:
    evidence = {}
    for key, label, width, height in VIEWPORTS:
        await page.set_viewport_size({"width": width, "height": height})
        await page.wait_for_timeout(180)
        analysis = await page.evaluate(LAYOUT_ANALYSIS_SCRIPT)
        filename = f"{filename_prefix}-{key}.png"
        await page.screenshot(path=str(screenshot_dir / filename), full_page=True)
        evidence[key] = {
            "label": label,
            "width": width,
            "height": height,
            "screenshot_path": filename,
            **analysis,
        }
    return evidence


def responsive_findings(page_url: str, evidence: dict) -> list[dict]:
    findings = []
    desktop = evidence.get("desktop", {})
    desktop_nav_links = desktop.get("visible_nav_links", 0)
    for key, label, _, _ in VIEWPORTS:
        result = evidence.get(key)
        if not result:
            continue
        viewport = f"{label} ({result['width']}x{result['height']})"
        overflow = max(0, result.get("document_width", 0) - result.get("viewport_width", 0))
        if overflow > 4:
            samples = "; ".join(result.get("overflow_elements", [])[:4]) or "No single element was isolated."
            findings.append(
                {
                    "page_url": page_url,
                    "severity": "high" if key == "mobile" and overflow > 20 else "medium",
                    "category": "responsive",
                    "title": f"Horizontal overflow on {label}",
                    "detail": f"{viewport} is {overflow}px wider than its viewport. Likely elements: {samples}",
                }
            )
        if result.get("hidden_content"):
            findings.append(
                {
                    "page_url": page_url,
                    "severity": "high",
                    "category": "responsive",
                    "title": f"Primary content hidden on {label}",
                    "detail": f"{viewport} contains hidden primary landmarks: {', '.join(result['hidden_content'])}.",
                }
            )
        if result.get("overlapping_elements"):
            findings.append(
                {
                    "page_url": page_url,
                    "severity": "medium",
                    "category": "responsive",
                    "title": f"Elements overlap on {label}",
                    "detail": f"{viewport}: {'; '.join(result['overlapping_elements'][:4])}",
                }
            )
        if result.get("unreadable_text"):
            findings.append(
                {
                    "page_url": page_url,
                    "severity": "medium" if len(result["unreadable_text"]) >= 5 else "low",
                    "category": "responsive",
                    "title": f"Small text on {label}",
                    "detail": f"{viewport} has text below 12px: {'; '.join(result['unreadable_text'][:5])}",
                }
            )
        # An image crossing the viewport is actionable only when the document itself
        # overflows. Clipped carousel slides are intentional and should not affect health.
        if result.get("images_outside_viewport") and overflow > 4:
            findings.append(
                {
                    "page_url": page_url,
                    "severity": "medium",
                    "category": "responsive",
                    "title": f"Images extend outside {label} viewport",
                    "detail": f"{viewport}: {'; '.join(result['images_outside_viewport'][:5])}",
                }
            )
        if (
            key != "desktop"
            and desktop_nav_links >= 3
            and result.get("visible_nav_links", 0) < max(1, desktop_nav_links // 2)
            and not result.get("menu_control_visible")
        ):
            findings.append(
                {
                    "page_url": page_url,
                    "severity": "high" if key == "mobile" else "medium",
                    "category": "responsive",
                    "title": f"Navigation may be broken on {label}",
                    "detail": (
                        f"Desktop exposes {desktop_nav_links} navigation links, but {viewport} exposes "
                        f"{result.get('visible_nav_links', 0)} and no visible menu control."
                    ),
                }
            )
    return findings

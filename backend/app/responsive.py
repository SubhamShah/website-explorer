from pathlib import Path


VIEWPORTS = (
    ("desktop", "Desktop", 1440, 900),
    ("tablet", "Tablet", 768, 1024),
    ("mobile", "Mobile", 390, 844),
)

LAYOUT_ANALYSIS_SCRIPT = r"""
() => {
  const width = window.innerWidth;
  const visible = (node) => {
    if (!(node instanceof Element)) return false;
    const style = getComputedStyle(node);
    const rect = node.getBoundingClientRect();
    return style.display !== 'none' && style.visibility !== 'hidden' &&
      Number(style.opacity || 1) > 0.01 && rect.width > 1 && rect.height > 1;
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
      return rect.left < -3 || rect.right > width + 3;
    })
    .slice(0, 10)
    .map(describe);
  const interactive = [...document.querySelectorAll(
    'a[href],button,input,select,textarea,[role="button"],[role="link"]'
  )].filter(visible).slice(0, 140);
  const overlaps = [];
  for (let first = 0; first < interactive.length && overlaps.length < 10; first += 1) {
    const a = interactive[first];
    const ar = a.getBoundingClientRect();
    for (let second = first + 1; second < interactive.length && overlaps.length < 10; second += 1) {
      const b = interactive[second];
      if (a.contains(b) || b.contains(a)) continue;
      const br = b.getBoundingClientRect();
      const overlapWidth = Math.max(0, Math.min(ar.right, br.right) - Math.max(ar.left, br.left));
      const overlapHeight = Math.max(0, Math.min(ar.bottom, br.bottom) - Math.max(ar.top, br.top));
      const overlapArea = overlapWidth * overlapHeight;
      const smallerArea = Math.min(ar.width * ar.height, br.width * br.height);
      if (smallerArea > 0 && overlapArea / smallerArea >= 0.25) {
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
    document_width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0),
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
        if result.get("images_outside_viewport"):
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

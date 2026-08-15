from __future__ import annotations

import re
from urllib.parse import urlparse


SENSITIVE_COOKIE_NAME = re.compile(r"auth|login|session|sessid|token|jwt|connect\.sid", re.I)
VERSION_DISCLOSURE = re.compile(r"(?:/|\s)v?\d+(?:\.\d+)+", re.I)


def _finding(page_url: str, severity: str, title: str, detail: str) -> dict:
    return {
        "page_url": page_url,
        "severity": severity,
        "category": "security",
        "title": title,
        "detail": detail,
    }


def _first_party_cookie(cookie: dict, hostname: str) -> bool:
    domain = str(cookie.get("domain") or "").lower().lstrip(".")
    return bool(domain) and (hostname == domain or hostname.endswith(f".{domain}"))


def _sensitive_cookie(name: str) -> bool:
    lowered = name.lower()
    return not any(term in lowered for term in ("csrf", "xsrf")) and bool(SENSITIVE_COOKIE_NAME.search(name))


def passive_security_findings(
    page_url: str,
    final_url: str,
    response_headers: dict | None,
    page_evidence: dict | None,
    cookies: list[dict] | None = None,
    *,
    check_cookies: bool = False,
) -> list[dict]:
    """Create read-only, common security-posture findings from an already loaded page."""
    findings: list[dict] = []
    parsed = urlparse(final_url)
    headers = {str(key).lower(): str(value) for key, value in (response_headers or {}).items()}
    evidence = page_evidence or {}

    if parsed.scheme != "https":
        findings.append(_finding(
            page_url,
            "high",
            "Website is not using HTTPS",
            "This page is delivered without an encrypted HTTPS connection. Information viewed or entered on the page can be exposed or changed in transit.",
        ))
    else:
        missing: list[str] = []
        if not headers.get("strict-transport-security"):
            missing.append("HTTPS enforcement (HSTS)")
        csp = headers.get("content-security-policy", "")
        if not csp:
            missing.append("content restrictions (Content-Security-Policy)")
        if not headers.get("x-frame-options") and "frame-ancestors" not in csp.lower():
            missing.append("protection from deceptive page embedding")
        if headers.get("x-content-type-options", "").lower() != "nosniff":
            missing.append("file-type protection (X-Content-Type-Options)")
        if not headers.get("referrer-policy"):
            missing.append("referrer privacy policy")
        if missing:
            findings.append(_finding(
                page_url,
                "medium" if "HTTPS enforcement (HSTS)" in missing else "low",
                "Common browser security protections are incomplete",
                "The server response is missing: " + "; ".join(missing) + ". These are preventive browser protections, not proof that the website has been attacked.",
            ))

    mixed = [str(item) for item in evidence.get("insecure_resources", []) if item]
    if mixed:
        examples = "; ".join(mixed[:3])
        findings.append(_finding(
            page_url,
            "high" if evidence.get("active_insecure_resource_count", 0) else "medium",
            "Secure page loads content over an insecure connection",
            f"The HTTPS page references {len(mixed)} HTTP resource(s). Examples: {examples}. Browsers may block these files or attackers may alter them in transit.",
        ))

    insecure_forms = [str(item) for item in evidence.get("insecure_form_actions", []) if item]
    if insecure_forms:
        findings.append(_finding(
            page_url,
            "high",
            "A form sends information over an insecure connection",
            "A form submits to HTTP instead of HTTPS: " + "; ".join(insecure_forms[:3]) + ". Do not enter information until the form action uses HTTPS.",
        ))
    if parsed.scheme != "https" and evidence.get("password_input_count", 0):
        findings.append(_finding(
            page_url,
            "critical",
            "Password field is shown without HTTPS",
            f"The page contains {evidence['password_input_count']} password field(s) on an unencrypted connection. Passwords could be intercepted.",
        ))

    if check_cookies:
        hostname = (parsed.hostname or "").lower()
        for cookie in cookies or []:
            name = str(cookie.get("name") or "")
            if not name or not _first_party_cookie(cookie, hostname) or not _sensitive_cookie(name):
                continue
            if parsed.scheme == "https" and not cookie.get("secure"):
                findings.append(_finding(
                    page_url,
                    "high",
                    "Sensitive cookie can travel without encryption",
                    f"The first-party cookie “{name}” appears related to login or session state but does not use the Secure protection.",
                ))
            if not cookie.get("httpOnly"):
                findings.append(_finding(
                    page_url,
                    "medium",
                    "Sensitive cookie is readable by page scripts",
                    f"The first-party cookie “{name}” appears related to login or session state but does not use HttpOnly protection.",
                ))

    disclosures = []
    for header_name in ("server", "x-powered-by"):
        value = headers.get(header_name, "")
        if value and VERSION_DISCLOSURE.search(value):
            disclosures.append(f"{header_name}: {value[:80]}")
    if disclosures:
        findings.append(_finding(
            page_url,
            "low",
            "Software version is publicly disclosed",
            "The response identifies a specific software version (" + "; ".join(disclosures) + "). Hiding exact versions reduces unnecessary information available to attackers.",
        ))

    return findings

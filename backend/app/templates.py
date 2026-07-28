import hashlib
import re
from urllib.parse import urlsplit


def _path_family(url: str) -> tuple[str, str, str]:
    segments = [segment for segment in urlsplit(url).path.lower().split("/") if segment]
    if not segments:
        return "home", "Homepage layout", "high"
    if segments[0] == "blog":
        if len(segments) >= 3 and segments[1] == "category":
            return "blog-category", "Blog category template", "high"
        if len(segments) >= 2:
            return "blog-article", "Blog article template", "high"
        return "blog-index", "Blog index layout", "high"
    families = {
        "product": "Product page template",
        "products": "Product page template",
        "service": "Service page template",
        "services": "Service page template",
        "news": "News article template",
        "article": "Article template",
        "articles": "Article template",
    }
    if segments[0] in families and len(segments) >= 2:
        return f"{segments[0]}-detail", families[segments[0]], "high"
    if len(segments) >= 2:
        section = re.sub(r"[-_]+", " ", segments[0]).title()
        return f"{segments[0]}-detail", f"{section} page template", "medium"
    return f"standard-{segments[0]}", "Standard page layout", "medium"


def template_metadata(url: str, structure_tokens: list[str] | None = None) -> dict:
    family, label, confidence = _path_family(url)
    normalized_tokens = [
        re.sub(r"\b\d+\b", ":n", " ".join(str(token).lower().split()))
        for token in (structure_tokens or [])
        if str(token).strip()
    ]
    structure_signature = hashlib.sha1(
        "|".join(normalized_tokens).encode("utf-8")
    ).hexdigest()[:12] if normalized_tokens else ""
    return {
        "template_id": family,
        "template_label": label,
        "template_confidence": confidence,
        "structure_signature": structure_signature,
    }


def attach_template_metadata(findings: list[dict], pages: list[dict]) -> None:
    templates = {
        page["url"]: (page.get("quality", {}).get("template") or {})
        for page in pages
    }
    for finding in findings:
        template = templates.get(finding.get("page_url"))
        if not template:
            continue
        metadata = dict(finding.get("metadata") or {})
        for key in (
            "template_id",
            "template_label",
            "template_confidence",
            "structure_signature",
        ):
            if template.get(key):
                metadata.setdefault(key, template[key])
        finding["metadata"] = metadata

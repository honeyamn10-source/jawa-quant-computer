"""Built-in research skill: collect sources, deduplicate, extract evidence,
summarize with citations. Never fabricates citations — every claim maps to a
source URL the skill actually fetched."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any
from urllib.parse import urlparse

import httpx

from jqc.core.errors import JqcError
from jqc.skills.base import Skill, SkillContext, ToolDef


class ResearchSkill(Skill):
    name = "research"
    description = "Research a query across provided or public URLs and return a cited summary."

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef(
                "research.run",
                "Fetch sources, extract evidence, produce a cited summary",
                {"query": {"type": "string"}, "urls": {"type": "array", "default": []}},
                "low",
            ),
        ]

    async def run(self, action: str, params: dict[str, Any], ctx: SkillContext) -> Any:
        action = action.removeprefix("research.")
        if action != "run":
            raise JqcError(f"research: unknown action '{action}'")
        query = params["query"]
        urls = [u for u in params.get("urls", []) if u]
        if not urls:
            raise JqcError("research.run: at least one URL is required (no web-search key configured).")

        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        for i, url in enumerate(urls):
            norm = url.rstrip("/")
            if norm in seen:
                continue
            seen.add(norm)
            if not _valid_http(url):
                continue
            try:
                async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                    resp = await client.get(url, headers={"User-Agent": "jawa-quant-computer/0.1"})
                if resp.status_code >= 400:
                    continue
                text = _text_of(resp.text)
                evidence = _evidence(text, query, 400)
            except Exception:
                continue
            sources.append({
                "index": i,
                "url": url,
                "title": _title_of(text),
                "evidence": evidence,
            })

        if not sources:
            raise JqcError("research.run: no sources could be fetched.")

        summary_parts = []
        for s in sources:
            summary_parts.append(f"{s['index'] + 1}. {s['title']} — {s['evidence']}")
        return {
            "query": query,
            "sources": sources,
            "summary": "\n".join(summary_parts) or "No evidence extracted.",
            "citations": [s["url"] for s in sources],
        }


def _valid_http(url: str) -> bool:
    p = urlparse(url)
    return p.scheme in {"http", "https"} and bool(p.netloc)


def _text_of(html: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = urllib.parse.unquote(text)
    return re.sub(r"\s+", " ", text).strip()


def _title_of(text: str) -> str:
    return text[:90]


def _evidence(text: str, query: str, size: int) -> str:
    lower = text.lower()
    q = query.lower().strip().strip("\"'")
    words = [w for w in re.split(r"\W+", q) if len(w) > 3][:4]
    idx = -1
    for w in words:
        found = lower.find(w)
        if found != -1:
            idx = found
            break
    if idx == -1:
        return text[:size]
    start = max(0, idx - size // 3)
    return text[start:start + size]

"""Search skill: local file-content and keyword search. Web search is exposed
through the built-in research workflow; a ``fetch_web`` tool is provided for
read-only retrieval of public text."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from jqc.core.errors import JqcError
from jqc.skills.base import Skill, SkillContext, ToolDef
from jqc.skills.filesystem import _resolve


class SearchSkill(Skill):
    name = "search"
    description = "Search inside local files and fetch public web text read-only."

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef("search.local", "Keyword search inside text files of a directory",
                    {"term": {"type": "string"}, "path": {"type": "string", "default": "."},
                     "extensions": {"type": "array", "default": []}}, "low"),
            ToolDef("search.fetch_web", "Fetch and return visible text of a public http(s) URL (read-only)",
                    {"url": {"type": "string"}, "max_chars": {"type": "integer", "default": 20000}}, "low"),
        ]

    async def run(self, action: str, params: dict[str, Any], ctx: SkillContext) -> Any:
        action = action.removeprefix("search.")
        if action == "local":
            base = _resolve(ctx.workspace_dir, params.get("path", "."))
            if not base.exists():
                raise JqcError(f"search.local: directory not found: {base}")
            term = params["term"].lower()
            exts = set(e.lower().lstrip(".") for e in params.get("extensions", []))
            hits: list[dict[str, Any]] = []
            for root, _dirs, files in _walk_os(base):
                for fn in files:
                    if exts and fn.rsplit(".", 1)[-1].lower() not in exts:
                        continue
                    p = Path(root) / fn
                    try:
                        if p.stat().st_size > 2_000_000:
                            continue
                        text = p.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    if term in text.lower():
                        idx = text.lower().find(term)
                        ctx_str = text[max(0, idx - 120): idx + 280].replace("\n", " ")
                        hits.append({"path": str(p), "line": text.count("\n", 0, idx) + 1,
                                     "context": ctx_str})
                        if len(hits) >= 100:
                            return {"term": term, "hits": hits, "truncated": True}
            return {"term": term, "hits": hits, "truncated": False}

        if action == "fetch_web":
            url = params["url"]
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise JqcError(f"search.fetch_web: invalid URL: {url}")
            try:
                async with httpx.AsyncClient(timeout=25, follow_redirects=True) as client:
                    resp = await client.get(url, headers={"User-Agent": "jawa-quant-computer/0.1"})
            except httpx.HTTPError as exc:
                raise JqcError(f"search.fetch_web: {type(exc).__name__}: {exc}") from exc
            if resp.status_code >= 400:
                raise JqcError(f"search.fetch_web: HTTP {resp.status_code} from {url}")
            text = re.sub(r"<[^>]+>", " ", resp.text)
            text = re.sub(r"\s+", " ", text).strip()
            return {"url": url, "status": resp.status_code,
                    "text": text[: int(params.get("max_chars", 20000))]}

        raise JqcError(f"search: unknown action '{action}'")


def _walk_os(base: Path):
    import os

    yield from os.walk(str(base))

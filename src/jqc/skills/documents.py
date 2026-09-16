"""Documents skill: extract text from PDF/DOCX/txt/markdown/csv and OCR-free
metadata. Lightweight: prefers files already on disk; heavy dependencies are
optional (pdfminer/docx)."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from jqc.core.errors import JqcError
from jqc.skills.base import Skill, SkillContext, ToolDef


class DocumentsSkill(Skill):
    name = "documents"
    description = "Extract text and metadata from documents (PDF, DOCX, TXT, MD, CSV, JSON)."

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef("documents.read", "Extract text content of a document",
                    {"path": {"type": "string"}}, "low"),
            ToolDef("documents.metadata", "Extract metadata (title, size, type, pages if available)",
                    {"path": {"type": "string"}}, "low"),
        ]

    async def run(self, action: str, params: dict[str, Any], ctx: SkillContext) -> Any:
        action = action.removeprefix("documents.")
        p = _resolve(Path(ctx.workspace_dir), params["path"])
        if not p.exists():
            raise JqcError(f"documents: file not found: {p}")
        if action == "metadata":
            return {"path": str(p), "name": p.name, "suffix": p.suffix,
                    "bytes": p.stat().st_size, "is_dir": p.is_dir()}
        if action == "read":
            return {"path": str(p), "content": _extract(p)}
        raise JqcError(f"documents: unknown action '{action}'")


def _resolve(ws: Path, path: str) -> Path:
    p = Path(path)
    return (ws / p if not p.is_absolute() else p).resolve()


def _extract(path: Path) -> str:
    suffix = path.suffix.lower()
    data = path.read_bytes()
    try:
        if suffix == ".txt" or suffix == ".md":
            return data.decode("utf-8", errors="replace")
        if suffix == ".json":
            return json.dumps(json.loads(data.decode("utf-8")), indent=2)
        if suffix == ".csv":
            return _csv_text(data)
        if suffix == ".pdf":
            return _pdf_text(path)
        if suffix in {".docx", ".doc"}:
            return _docx_text(data)
        return f"[No text extractor for {suffix or 'unknown type'} — binary file of {len(data)} bytes]"
    except Exception as exc:
        return f"[Failed to extract {path.name}: {exc.__class__.__name__}]"


def _csv_text(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    try:
        rows = list(csv.reader(io.StringIO(text)))
        return "\n".join(" | ".join(row) for row in rows[:500])
    except Exception:
        return text[:20000]


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            return "[PDF text extraction requires 'pypdf' — install with: pip install pypdf]"
    reader = PdfReader(str(path))
    pages = [page.extract_text() or "" for page in reader.pages[:200]]
    return "\n\n".join(pages)[:100000]


def _docx_text(data: bytes) -> str:
    try:
        import docx
    except ImportError:
        return "[DOCX text extraction requires 'python-docx' — install with: pip install python-docx]"
    bio = io.BytesIO(data)
    doc = docx.Document(bio)
    return "\n".join(p.text for p in doc.paragraphs)[:100000]

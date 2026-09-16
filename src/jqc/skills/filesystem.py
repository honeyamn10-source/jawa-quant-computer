"""Filesystem skill: safe local file operations scoped to the workspace."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from jqc.core.errors import JqcError
from jqc.skills.base import Skill, SkillContext, ToolDef


def _resolve(workspace_dir: Path, path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = workspace_dir / p
    p = p.resolve()
    if not str(p).startswith(str(workspace_dir.resolve())) and workspace_dir not in p.parents:
        raise JqcError(f"Path '{path}' is outside the active workspace and was not allowed.")
    return p


def safe_write(path: Path, content: str | bytes) -> None:
    if content and not isinstance(content, (str, bytes, bytearray)):
        content = str(content)
    mode = "wb" if isinstance(content, (bytes, bytearray)) else "w"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode, encoding=None if mode == "wb" else "utf-8") as fh:
        fh.write(content if isinstance(content, bytes) else content)


class FilesystemSkill(Skill):
    name = "filesystem"
    description = "Create, read, write, copy, move, rename, search and list local files."

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef("filesystem.read", "Read a text/UTF-8 file and return its contents",
                    {"path": {"type": "string"}}, "low"),
            ToolDef("filesystem.write", "Create or overwrite a file with text content",
                    {"path": {"type": "string"}, "content": {"type": "string"}}, "medium"),
            ToolDef("filesystem.create", "Create an empty file",
                    {"path": {"type": "string"}}, "medium"),
            ToolDef("filesystem.mkdir", "Create a directory (parent creation implied)",
                    {"path": {"type": "string"}, "parents": {"type": "boolean", "default": True}}, "medium"),
            ToolDef("filesystem.list", "List entries inside a directory",
                    {"path": {"type": "string", "default": "."}}, "low"),
            ToolDef("filesystem.stat", "Metadata for a path (size, mtime, is_dir)",
                    {"path": {"type": "string"}}, "low"),
            ToolDef("filesystem.move", "Move/rename a file or directory",
                    {"source": {"type": "string"}, "destination": {"type": "string"}}, "medium"),
            ToolDef("filesystem.copy", "Copy a file or directory",
                    {"source": {"type": "string"}, "destination": {"type": "string"}}, "medium"),
            ToolDef("filesystem.delete", "Permanently delete a file or directory (high risk)",
                    {"path": {"type": "string"}}, "high"),
            ToolDef("filesystem.search", "Find files by name glob under a directory",
                    {"query": {"type": "string"}, "path": {"type": "string", "default": "."}}, "low"),
        ]

    async def run(self, action: str, params: dict[str, Any], ctx: SkillContext) -> Any:
        ws = ctx.workspace_dir
        action = action.removeprefix(f"{self.name}.")
        ctx.check_cancelled()
        if action == "read":
            p = _resolve(ws, params["path"])
            if not p.exists():
                raise JqcError(f"File not found: {p}")
            with open(p, encoding="utf-8", errors="replace") as fh:
                content = fh.read()
            return {"path": str(p), "content": content, "bytes": len(content.encode("utf-8"))}

        if action in {"write", "create"}:
            p = _resolve(ws, params["path"])
            safe_write(p, params.get("content", "") if action == "write" else "")
            return {"path": str(p), "created": True}

        if action == "mkdir":
            p = _resolve(ws, params["path"])
            p.mkdir(parents=params.get("parents", True), exist_ok=True)
            return {"path": str(p), "is_dir": True}

        if action == "list":
            p = _resolve(ws, params.get("path", "."))
            if not p.exists() or not p.is_dir():
                raise JqcError(f"Directory not found: {p}")
            entries = [
                {"name": e.name, "is_dir": e.is_dir(), "bytes": e.stat().st_size if e.is_file() else None}
                for e in sorted(p.iterdir(), key=lambda x: x.name)
            ]
            return {"path": str(p), "entries": entries, "count": len(entries)}

        if action == "stat":
            p = _resolve(ws, params["path"])
            if not p.exists():
                raise JqcError(f"Path not found: {p}")
            st = p.stat()
            return {"path": str(p), "is_dir": p.is_dir(), "bytes": st.st_size,
                    "mtime": st.st_mtime, "modified_at": st.st_mtime}

        if action == "move":
            src = _resolve(ws, params["source"])
            dst = _resolve(ws, params["destination"])
            if not src.exists():
                raise JqcError(f"Source not found: {src}")
            shutil.move(str(src), str(dst))
            return {"source": str(src), "destination": str(dst)}

        if action == "copy":
            src = _resolve(ws, params["source"])
            dst = _resolve(ws, params["destination"])
            if not src.exists():
                raise JqcError(f"Source not found: {src}")
            if src.is_dir():
                shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
            return {"source": str(src), "destination": str(dst)}

        if action == "delete":
            p = _resolve(ws, params["path"])
            if not p.exists():
                raise JqcError(f"Path not found: {p}")
            if p.is_dir():
                shutil.rmtree(str(p))
            else:
                p.unlink()
            return {"deleted": str(p)}

        if action == "search":
            base = _resolve(ws, params.get("path", "."))
            if not base.exists():
                raise JqcError(f"Directory not found: {base}")
            query = params["query"].lower()
            hits = []
            for root, _dirs, files in os.walk(str(base)):
                for fn in files:
                    low = fn.lower()
                    if query in low or glob_match(query, fn):
                        full = Path(root) / fn
                        hits.append({"path": str(full), "bytes": full.stat().st_size})
                    if len(hits) >= 200:
                        return {"query": query, "hits": hits, "truncated": True}
            return {"query": query, "hits": hits, "truncated": False}

        raise JqcError(f"filesystem: unknown action '{action}'")


def glob_match(pattern: str, name: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(name.lower(), pattern.lower())

"""Browser skill with pluggable drivers.

Production driver: Playwright (DOM/accessibility first, screenshots, download
tracking). Test/dev driver: deterministic ``MockDriver`` for offline runs —
used by demo mode and CI so acceptance flows never depend on a browser
download or external site.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from jqc.core.errors import JqcError
from jqc.skills.base import Skill, SkillContext, ToolDef


class BrowserDriver:
    """Controller interface implemented by Playwright and the mock."""

    async def open(self, url: str, **kw: Any) -> dict[str, Any]: ...
    async def title(self) -> str: ...
    async def screenshot(self, path: str, ctx: SkillContext) -> dict[str, Any]: ...
    async def snippet(self, selector: str | None = None) -> str: ...
    async def click(self, selector: str) -> dict[str, Any]: ...
    async def type(self, selector: str, text: str) -> dict[str, Any]: ...
    async def download(self, url: str, destination: str, ctx: SkillContext) -> dict[str, Any]: ...
    async def extract_links(self) -> list[str]: ...
    async def close(self) -> None: ...
    async def health(self) -> tuple[bool, str]: ...


def _downloads_dir(data_dir: Path) -> Path:
    d = data_dir / "downloads"
    d.mkdir(parents=True, exist_ok=True)
    return d


DEFAULTS = {"www.example.com": "Example Domain", "example.com": "Example Domain"}


class MockDriver(BrowserDriver):
    """Deterministic driver; no network, no browser. For demo/CI only."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.current_url: str | None = None

    async def open(self, url: str, **kw: Any) -> dict[str, Any]:
        self.current_url = url
        return {"url": url, "driver": "mock", "title": await self.title()}

    async def title(self) -> str:
        if not self.current_url:
            return ""
        host = self.current_url.split("/")[2] if "://" in self.current_url else self.current_url
        return DEFAULTS.get(host, f"Title of {host}")

    async def screenshot(self, path: str, ctx: SkillContext) -> dict[str, Any]:
        img = Path(path)
        img.parent.mkdir(parents=True, exist_ok=True)
        img.write_bytes(b"mock-screenshot")
        return {"path": str(img), "driver": "mock", "bytes": img.stat().st_size}

    async def snippet(self, selector: str | None = None) -> str:
        return "Mock DOM fragment (demo mode)"

    async def click(self, selector: str) -> dict[str, Any]:
        return {"selector": selector, "clicked": True}

    async def type(self, selector: str, text: str) -> dict[str, Any]:
        return {"selector": selector, "submitted": True}

    async def download(self, url: str, destination: str, ctx: SkillContext) -> dict[str, Any]:
        dst = Path(destination)
        dst.parent.mkdir(parents=True, exist_ok=True)
        content = f"mock download from {url}\n"
        dst.write_text(content)
        return {"path": str(dst), "driver": "mock", "bytes": dst.stat().st_size}

    async def extract_links(self) -> list[str]:
        return []

    async def close(self) -> None:
        self.current_url = None

    async def health(self) -> tuple[bool, str]:
        return True, "Mock browser driver (demo mode, no real browser)"


class PlaywrightDriver(BrowserDriver):
    def __init__(self, data_dir: Path, headless: bool = True) -> None:
        self.data_dir = data_dir
        self.headless = headless
        self._page = None
        self._browser = None
        self.playwright = None
        _ensure_browser_cache()

    async def open(self, url: str, **kw: Any) -> dict[str, Any]:
        pw = await _load_playwright(self.data_dir)
        browser = await pw.chromium.launch(headless=self.headless)
        page = await browser.new_page()
        await page.goto(url, timeout=int(kw.get("timeout", 45000)), wait_until="domcontentloaded")
        self._browser, self._page = browser, page
        return {"url": url, "driver": "playwright", "title": await page.title()}

    async def title(self) -> str:
        if not self._page:
            raise JqcError("browser: no page open")
        return await self._page.title()

    async def screenshot(self, path: str, ctx: SkillContext) -> dict[str, Any]:
        if not self._page:
            raise JqcError("browser: no page open")
        img = Path(path)
        img.parent.mkdir(parents=True, exist_ok=True)
        await self._page.screenshot(path=str(img))
        return {"path": str(img), "driver": "playwright", "bytes": img.stat().st_size}

    async def snippet(self, selector: str | None = None) -> str:
        if not self._page:
            raise JqcError("browser: no page open")
        if selector:
            els = self._page.locator(selector)
            n = await els.count()
            return f"{n} element(s) match selector '{selector}'"
        return (await self._page.locator("body").inner_text())[:4000]

    async def click(self, selector: str) -> dict[str, Any]:
        if not self._page:
            raise JqcError("browser: no page open")
        await self._page.locator(selector).click(timeout=15000)
        return {"selector": selector, "clicked": True}

    async def type(self, selector: str, text: str) -> dict[str, Any]:
        if not self._page:
            raise JqcError("browser: no page open")
        await self._page.locator(selector).fill(text)
        return {"selector": selector, "submitted": True}

    async def download(self, url: str, destination: str, ctx: SkillContext) -> dict[str, Any]:
        if not self._page:
            raise JqcError("browser: no page open")
        async with self._page.expect_download(timeout=45000) as dl_info:
            await self._page.goto(url, wait_until="domcontentloaded")
        dl = await dl_info.value
        dst = Path(destination)
        dst.parent.mkdir(parents=True, exist_ok=True)
        await dl.save_as(str(dst))
        return {"path": str(dst), "driver": "playwright", "bytes": dst.stat().st_size}

    async def extract_links(self) -> list[str]:
        if not self._page:
            return []
        return await self._page.eval_on_selector_all("a[href]", "els => els.map(e => e.href)")

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
        self._browser = self._page = None

    async def health(self) -> tuple[bool, str]:
        try:
            pw = await _load_playwright(self.data_dir)
            browser = await pw.chromium.launch(headless=True)
            await browser.close()
            return True, "Playwright Chromium is installed and launchable"
        except Exception as exc:
            return False, f"Playwright browser missing or broken: {exc.__class__.__name__}: {exc}"


async def _load_playwright(data_dir: Path) -> Any:
    from playwright.async_api import async_playwright

    pw = await async_playwright().start()
    return pw


def _ensure_browser_cache() -> None:
    """Pin the browser cache to ~/.cache/ms-playwright unless the user set
    PLAYWRIGHT_BROWSERS_PATH explicitly."""
    if "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
        default = str(Path.home() / ".cache" / "ms-playwright")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = default
        if "PLAYWRIGHT_DOWNLOAD_BROWSERS_PATH" not in os.environ:
            os.environ.setdefault("PLAYWRIGHT_DOWNLOAD_BROWSERS_PATH", default)


def make_driver(data_dir: Path, headless: bool, force: str | None = None) -> BrowserDriver:
    """Pick a driver: explicit, then Playwright if browser binaries exist, else mock."""
    force = force or os.environ.get("JQC_BROWSER_DRIVER")
    if force == "mock":
        return MockDriver(data_dir)
    if force == "playwright":
        return PlaywrightDriver(data_dir, headless)
    try:
        from playwright.async_api import async_playwright  # noqa: F401

        cache = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "~/.cache/ms-playwright"
        try:
            import glob

            if any(glob.glob(str(Path(cache).expanduser()) + "/*")):
                return PlaywrightDriver(data_dir, headless)
        except Exception:
            pass
    except Exception:
        pass
    return MockDriver(data_dir)


DRIVERS = {"mock": MockDriver, "playwright": PlaywrightDriver}


class BrowserSkill(Skill):
    name = "browser"
    description = "Open web pages, read titles/content, screenshot, download files, follow links."

    def __init__(self, data_dir: Path, headless: bool = True, driver: str | None = None) -> None:
        self.controller = make_driver(data_dir, headless, driver)

    def tools(self) -> list[ToolDef]:
        return [
            ToolDef("browser.open", "Open a URL in a browser tab",
                    {"url": {"type": "string"}, "timeout": {"type": "integer", "default": 45000}}, "medium"),
            ToolDef("browser.title", "Current page title", {}, "low"),
            ToolDef("browser.screenshot", "Save a screenshot of the current page",
                    {"path": {"type": "string"}}, "low"),
            ToolDef("browser.snippet", "Visible text of the current page (or a selector)",
                    {"selector": {"type": "string", "default": None}}, "low"),
            ToolDef("browser.extract_links", "List of hrefs on the current page", {}, "low"),
            ToolDef("browser.click", "Click an element by selector",
                    {"selector": {"type": "string"}}, "medium"),
            ToolDef("browser.type", "Fill a form field and submit",
                    {"selector": {"type": "string"}, "text": {"type": "string"}}, "medium"),
            ToolDef("browser.download", "Download the current page as a file",
                    {"url": {"type": "string"}, "destination": {"type": "string"}}, "medium"),
            ToolDef("browser.close", "Close the browser", {}, "medium"),
            ToolDef("browser.health", "Check whether a real browser is usable", {}, "low"),
        ]

    async def run(self, action: str, params: dict[str, Any], ctx: SkillContext) -> Any:
        action = action.removeprefix("browser.")
        ctx.check_cancelled()
        ws = ctx.workspace_dir
        if action == "open":
            url = params["url"]
            if not (url.startswith("http://") or url.startswith("https://")):
                raise JqcError(f"browser.open: URL must be http(s), got '{url}'")
            res = await self.controller.open(url, timeout=params.get("timeout") or 45000)
            return res
        if action == "title":
            return {"title": await self.controller.title()}
        if action == "screenshot":
            p = _resolve_path(ws, params["path"])
            return await self.controller.screenshot(str(p), ctx)
        if action == "snippet":
            return {"text": await self.controller.snippet(params.get("selector"))}
        if action == "extract_links":
            return {"links": await self.controller.extract_links()}
        if action == "click":
            res = await self.controller.click(params["selector"])
            res["title"] = await self._safe_title()
            return res
        if action == "type":
            res = await self.controller.type(params["selector"], params["text"])
            res["title"] = await self._safe_title()
            return res
        if action == "download":
            dst = _resolve_path(ws, params["destination"] or f"downloads/{int(time.time())}")
            return await self.controller.download(params["url"], str(dst), ctx)
        if action == "close":
            await self.controller.close()
            return {"closed": True}
        if action == "health":
            ok, detail = await self.controller.health()
            return {"driver": await self._driver_name(), "ok": ok, "detail": detail}
        raise JqcError(f"browser: unknown action '{action}'")

    async def _safe_title(self) -> str:
        try:
            return await self.controller.title()
        except Exception:
            return ""

    async def _driver_name(self) -> str:
        return self.controller.__class__.__name__.replace("Driver", "").lower()


def _resolve_path(ws: Path, path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = ws / p
    return p.resolve()

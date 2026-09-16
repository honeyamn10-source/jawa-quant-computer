"""Capture loopback UI screenshots for the README (server on 127.0.0.1:8337)."""
import asyncio
import json
import urllib.request

from pathlib import Path

from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8337"
OUT = Path("docs/screenshots")
OUT.mkdir(parents=True, exist_ok=True)

VIEWS = ["chat", "tasks", "computer", "files", "models", "skills", "memory", "activity", "settings"]
PROMPTS = [
    "Open https://example.com, read the page title and save it to title-example-com.txt",
    "Create a folder called quant-notes with a notes.txt that lists three Python libraries I use weekly",
    "Remember that I prefer .txt files for scratch notes and that my timezone is Asia/Kolkata",
    "Schedule a summary job to run once tomorrow at 09:00 Asia/Kolkata",
]


def seed() -> None:
    for prompt in PROMPTS:
        req = urllib.request.Request(
            f"{BASE}/api/chat",
            data=json.dumps({"conversation_id": "conv-screenshot", "message": prompt}).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=120)
        except Exception as exc:
            print("seed skip:", str(exc)[:60])


async def main() -> None:
    seed()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1680, "height": 1020})
        await page.goto(f"{BASE}/", wait_until="networkidle")
        await page.wait_for_timeout(3000)
        for view in VIEWS:
            await page.eval_on_selector_all(
                ".nav-item",
                "(els, arg) => { for (const el of els) if (el.dataset.view === arg) el.click(); }",
                view,
            )
            await page.wait_for_timeout(2800)
            path = OUT / f"ui-{view}.png"
            await page.screenshot(path=str(path))
            print("captured", view, path)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

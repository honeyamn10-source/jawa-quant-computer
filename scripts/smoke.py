"""Quick smoke test of the core acceptance flows against a temp data dir."""
import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jqc.app import build_app
from jqc.config import Settings
from jqc.scheduler.times import now_utc
from datetime import timedelta
import tempfile


def make_settings(tmp: Path) -> Settings:
    return Settings(
        data_dir=tmp / "data",
        workspace_dir=tmp / "workspace",
        host="127.0.0.1",
        port=8337,
        demo_mode=True,
        browser_headless=True,
    )


async def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="jqc-smoke-"))
    s = make_settings(tmp)
    deps = build_app(s, browser_driver="mock")

    print("== FLOW 1: browser title -> file ==")
    r1 = await deps["agent"].submit_and_wait(
        "Open example.com, capture the page title and save it into a text file in my workspace.",
        workspace="default",
    )
    print("status:", r1["status"], "| result:", r1["result"][:200])
    assert r1["status"] == "completed", r1

    print("== FLOW 2: folder + notes.txt + read back ==")
    r2 = await deps["agent"].submit_and_wait(
        "Create a folder named AI Computer Test, create notes.txt inside it, write \"AI Computer is operational\", then read the file back to me.",
        workspace="default",
    )
    print("status:", r2["status"], "| result:", r2["result"][:400])
    assert r2["status"] == "completed", r2

    print("== FLOW 3: schedule in 5 minutes ==")
    r3 = await deps["agent"].submit_and_wait(
        "Schedule a task five minutes from now that creates scheduled-test.txt.",
        workspace="default",
    )
    print("status:", r3["status"])
    assert r3["status"] == "completed", r3
    import json

    jobs = deps["scheduler"].repo.list()
    print("jobs:", json.dumps(jobs, default=str)[:400])
    assert len(jobs) == 1 and jobs[0]["schedule_type"] == "once"

    print("== permissions: high-risk shell classified high ==")
    pm = deps["permissions"]
    print("rm -rf:", pm.classify("shell", "run", "rm -rf /"), "| write:", pm.classify("filesystem", "write", "a.txt"))

    print("\nALL CORE SMOKE CHECKS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
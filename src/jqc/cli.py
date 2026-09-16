"""Interactive terminal chat for Jawa Quant Computer.

Run locally:  .venv/bin/jawa-quant-computer
or:           python -m jqc.cli

Commands:
  /approve <approval_id>   approve a pending approval
  /deny <approval_id>      deny a pending approval
  /providers               list providers
  /jobs                    list scheduled jobs
  /skills                  list available tool schemas
  /tasks                   recent tasks
  /workspace               print workspace path
  /quit, /exit             leave
"""

from __future__ import annotations

import asyncio
import json
import time

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from jqc.app import build_app
from jqc.config import settings
from jqc.core.schemas import EventStatus, TaskStatus

console = Console()


def main() -> None:
    asyncio.run(_repl())


async def _repl() -> None:
    console.print(Panel("[bold cyan]Jawa Quant Computer[/bold cyan]\n"
                        "Local AI agent — type a request, or /help for commands.",
                        border_style="cyan"))
    deps = build_app(settings)
    agent = deps["agent"]
    await deps["scheduler"].start()

    while True:
        try:
            line = Prompt.ask("You")
        except (KeyboardInterrupt, EOFError):
            break
        line = line.strip()
        if not line:
            continue
        if line.startswith("/"):
            if line in {"/quit", "/exit", "/q"}:
                break
            _handle_command(line, deps)
            continue
        try:
            result = await agent.submit_and_wait(line)
        except Exception as exc:
            console.print(f"[red]{exc}[/red]")
            continue
        _render_task(result, deps)

    await deps["scheduler"].stop()
    deps["db"].close()


def _handle_command(line: str, deps: dict) -> None:
    parts = line.split()
    cmd = parts[0]
    if cmd == "/approve" and len(parts) > 1:
        row = deps["agent"].decide(parts[1], True)
        console.print(f"[green]approved[/green] {parts[1]}" if row else "[red]not found[/red]")
    elif cmd == "/deny" and len(parts) > 1:
        row = deps["agent"].decide(parts[1], False)
        console.print(f"[yellow]denied[/yellow] {parts[1]}" if row else "[red]not found[/red]")
    elif cmd == "/providers":
        table = Table(title="Providers")
        for col in ("id", "kind", "name", "model", "enabled"):
            table.add_column(col)
        for r in deps["router"].list_providers():
            table.add_row(str(r["id"]), r["kind"], r["name"], r["model"],
                          "yes" if r["enabled"] else "no")
        console.print(table)
    elif cmd == "/jobs":
        table = Table(title="Scheduled jobs")
        for col in ("id", "name", "type", "enabled", "status", "next_run"):
            table.add_column(col)
        for j in deps["scheduler"].repo.list():
            nxt = time.strftime("%Y-%m-%d %H:%M", time.localtime(j["next_run_at"])) if j["next_run_at"] else "-"
            table.add_row(j["id"], j["name"], j["schedule_type"],
                          "yes" if j["enabled"] else "no", j["status"], nxt)
        console.print(table)
    elif cmd == "/skills":
        for t in deps["registry"].tools():
            console.print(Panel(t.name, subtitle=t.description, subtitle_align="left"))
    elif cmd == "/tasks":
        table = Table(title="Tasks")
        for col in ("id", "status", "request"):
            table.add_column(col)
        for t in deps["agent"].tasks.list(limit=10):
            req = (t["request"] or "")[:60]
            table.add_row(t["id"], t["status"], req)
        console.print(table)
    elif cmd == "/workspace":
        console.print(str(settings.workspace_dir))
    elif cmd in {"/help", "/h"}:
        console.print("Commands: /approve <id>  /deny <id>  /providers  /jobs  /skills  /tasks "
                      "/workspace  /quit")
    else:
        console.print(f"[yellow]unknown command: {cmd}[/yellow]")


def _render_task(task: dict, deps: dict) -> None:
    status = task.get("status")
    if status == TaskStatus.failed.value:
        console.print(f"[red]Task failed:[/red] {task.get('error')}")
        return
    if status == TaskStatus.cancelled.value:
        console.print("[yellow]Task cancelled.[/yellow]")
        return
    result_raw = task.get("result")
    if not result_raw:
        console.print("[yellow]Task produced no result.[/yellow]")
        return
    try:
        result = json.loads(result_raw)
    except ValueError:
        result = {"summary": result_raw}
    console.print(Markdown(f"### {result.get('summary', 'Done.')}"))
    steps = deps["agent"].steps.for_task(task["id"])
    for st in steps:
        mark = "✅" if st["status"] == EventStatus.completed.value else "⬜"
        label = st["action"]
        console.print(f"  {mark} {st['tool']}.{label}")


if __name__ == "__main__":
    main()

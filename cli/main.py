#!/usr/bin/env python3
"""
CLI - terminal interface with rich UI.

Usage:
  python cli/main.py                       — interactive mode
  python cli/main.py --session <id>        — reattach to existing session
  python cli/main.py --list-sessions       — list recent sessions and exit
  python cli/main.py --stream              — enable token-by-token streaming
  python cli/main.py --focus               — focus mode (suppress events)
  python cli/main.py --model haiku         — force model for this session
  echo "explain this" | python cli/main.py — pipe stdin as single message
  cat file.py | python cli/main.py --one-shot "review this code"
"""
import argparse
import asyncio
import sys
import os
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich.text import Text
from rich import print as rprint

from core.orchestrator import AgentOrchestrator
from config.settings import load_config

console = Console()

BANNER = """[bold cyan]
╔═══════════════════════════════════════╗
║        🤖 AGENT SYSTEM v2.0          ║
║   Claude · Gemini · Ollama · Tools   ║
╚═══════════════════════════════════════╝
[/bold cyan]"""

HELP_TEXT = """
[bold yellow]Commands:[/bold yellow]
  [cyan]/help[/cyan]                  - Show this help
  [cyan]/clear[/cyan]                 - Clear conversation history
  [cyan]/stats[/cyan]                 - Session statistics
  [cyan]/model[/cyan]                 - Show last routing decision
  [cyan]/models[/cyan]                - List available models
  [cyan]/session[/cyan]               - Show current session ID
  [cyan]/routing on/off[/cyan]        - Toggle routing info display
  [cyan]/focus[/cyan]                 - Toggle focus mode (suppress events)
  [cyan]/stream[/cyan]                - Toggle streaming output
  [cyan]/macros[/cyan]                - List available prompt macros
  [cyan]/macro <name> <template>[/cyan]- Save a new macro
  [cyan]/brief[/cyan]                 - Generate a session briefing
  [cyan]/variants <message>[/cyan]    - Run 3 variants of a prompt
  [cyan]/copy[/cyan]                  - Copy last code block to clipboard
  [cyan]/title[/cyan]                 - Show/set session title
  [cyan]/exit[/cyan]                  - Quit

[bold yellow]Shortcuts:[/bold yellow]
  [cyan]haiku: <msg>[/cyan]           - Force claude-haiku model
  [cyan]gemini: <msg>[/cyan]          - Force gemini model
  [cyan]fast: <msg>[/cyan]            - Force cheapest model
  [cyan]/code <task>[/cyan]           - Code writing macro
  [cyan]/explain <topic>[/cyan]       - Explanation macro
  [cyan]/debug <error>[/cyan]         - Debug macro
  [cyan]/review <code>[/cyan]         - Code review macro
  [cyan]/summarize <text>[/cyan]      - Summarization macro
  [cyan]@/path/to/file[/cyan]         - Inject file content into message

[bold yellow]Pipe mode:[/bold yellow]
  [dim]echo "explain this" | python cli/main.py[/dim]
  [dim]cat error.log | python cli/main.py --one-shot "what's wrong?"[/dim]
"""


# ─── Streaming output ─────────────────────────────────────────────────────────
async def _stream_response(orchestrator: AgentOrchestrator, message: str, session_id: str, model_override: str = "") -> str:
    """Stream response token-by-token using a callback."""
    tokens: list[str] = []

    async def on_token(token: str) -> None:
        tokens.append(token)
        # Flush token to terminal immediately
        sys.stdout.write(token)
        sys.stdout.flush()

    # Use stream_callback path
    try:
        from llm.manager import LLMManager
        decision = await orchestrator.router.route(message, orchestrator.conversation_history)
        model = model_override or decision.model

        sys.stdout.write("\n[bold]Response:[/bold] ")
        sys.stdout.flush()

        result = await orchestrator.llm.call(
            model=model,
            messages=orchestrator.conversation_history + [{"role": "user", "content": message}],
            max_tokens=2048,
            stream=True,
            stream_callback=on_token,
        )
        sys.stdout.write("\n")
        await orchestrator._update_history(session_id, message, result)
        orchestrator.last_decision = decision
        return result
    except Exception:
        # Fall back to normal process
        return await orchestrator.process(message=message, session_id=session_id, preferred_model=model_override)


# ─── List sessions ────────────────────────────────────────────────────────────
async def _list_sessions_and_exit(config: dict) -> None:
    try:
        from db.history import init_db, list_sessions
        mongo_url = config.get("mongo_url", "mongodb://localhost:27017")
        await init_db(mongo_url)
        sessions = await list_sessions(limit=20)
        if not sessions:
            console.print("[dim]No sessions found.[/dim]")
            return
        table = Table(title="Recent Sessions")
        table.add_column("Session ID", style="cyan")
        table.add_column("Title", style="bold white")
        table.add_column("Preview", style="white")
        table.add_column("Tags", style="yellow")
        table.add_column("Updated", style="dim")
        for s in sessions:
            title = s.get("title", "")
            tags = ", ".join(s.get("auto_tags", [])[:3])
            table.add_row(
                s["session_id"],
                title[:30],
                s.get("preview", "")[:40],
                tags,
                s.get("updated_at", "")[:16],
            )
        console.print(table)
    except Exception as e:
        console.print(f"[red]Could not load sessions: {e}[/red]")


def _extract_last_code_block(text: str) -> str | None:
    """Extract the last code block from markdown text."""
    matches = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
    return matches[-1].strip() if matches else None


async def _show_macros(config: dict) -> None:
    try:
        from db.macros import list_macros
        macros = await list_macros()
        table = Table(title="Available Macros")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="dim")
        table.add_column("Template Preview", style="white")
        for m in macros:
            kind = "[green]builtin[/green]" if m.get("builtin") else "[yellow]custom[/yellow]"
            table.add_row(m["name"], kind, m["template"][:60] + "…")
        console.print(table)
    except Exception as e:
        console.print(f"[red]Could not list macros: {e}[/red]")


# ─── Main ─────────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="Agent System CLI")
    parser.add_argument("--session", "-s", metavar="SESSION_ID", help="Reattach to an existing session")
    parser.add_argument("--list-sessions", "-l", action="store_true", help="List recent sessions and exit")
    parser.add_argument("--stream", action="store_true", help="Enable token-by-token streaming output")
    parser.add_argument("--focus", action="store_true", help="Focus mode: suppress all event output")
    parser.add_argument("--model", "-m", metavar="MODEL", default="", help="Force a specific model (e.g. haiku, gemini)")
    parser.add_argument("--one-shot", metavar="PROMPT", help="Send a single prompt (combined with stdin if piped) and exit")
    args = parser.parse_args()

    config = load_config()

    if args.list_sessions:
        await _list_sessions_and_exit(config)
        return

    # ─── Stdin pipe detection ────────────────────────────────────────────────
    stdin_content = ""
    if not sys.stdin.isatty():
        stdin_content = sys.stdin.read().strip()

    session_id = args.session or "default"
    show_routing = not args.focus
    use_streaming = args.stream
    focus_mode = args.focus
    model_override = args.model
    last_response = ""

    try:
        orchestrator = AgentOrchestrator(config)
        if args.session:
            try:
                from db.history import init_db, load_context
                mongo_url = config.get("mongo_url", "mongodb://localhost:27017")
                await init_db(mongo_url)
                orchestrator.conversation_history = await load_context(session_id)
                console.print(f"[cyan]Reattached to session [bold]{session_id}[/bold] "
                               f"({len(orchestrator.conversation_history)} messages)[/cyan]")
            except Exception as e:
                console.print(f"[yellow]Could not load history: {e}[/yellow]")
    except Exception as e:
        console.print(f"[red]✗ Initialisation error: {e}[/red]")
        sys.exit(1)

    # ─── One-shot / pipe mode ────────────────────────────────────────────────
    if args.one_shot or stdin_content:
        if not sys.stdin.isatty():
            console.print(BANNER)
        prompt = args.one_shot or ""
        message = f"{prompt}\n\n{stdin_content}" if (prompt and stdin_content) else (prompt or stdin_content)

        from api.preprocessor import preprocess as preprocess_message
        processed, detected_model = await preprocess_message(message)
        model = model_override or detected_model

        if use_streaming:
            response = await _stream_response(orchestrator, processed, session_id, model)
        else:
            response = await orchestrator.process(message=processed, session_id=session_id, preferred_model=model, show_routing=show_routing)
            console.print(f"\n{response}")
        return

    # ─── Interactive mode ────────────────────────────────────────────────────
    console.print(BANNER)
    console.print("[green]✓ System ready![/green]")
    console.print("[dim]Type /help for commands. Use /code, /explain, /debug macros. Prefix 'haiku:' to force model.[/dim]\n")

    from api.preprocessor import preprocess as preprocess_message

    while True:
        try:
            msg_count = len(orchestrator.conversation_history) // 2 + 1
            user_input = Prompt.ask(f"\n[bold green]You[/bold green] [{msg_count}]")

            if not user_input.strip():
                continue

            # ─── Command handling ────────────────────────────────────────────
            if user_input.startswith("/"):
                cmd_lower = user_input.lower().strip()
                parts = user_input.strip().split(None, 2)
                cmd = parts[0].lower()

                if cmd in ("/exit", "/quit", "/q"):
                    console.print("[cyan]Goodbye![/cyan]")
                    break

                elif cmd == "/help":
                    console.print(Panel(HELP_TEXT, title="Help", border_style="cyan"))

                elif cmd == "/clear":
                    orchestrator.clear_history()

                elif cmd == "/stats":
                    stats = orchestrator.get_stats()
                    table = Table(title="Session Statistics")
                    table.add_column("Parameter", style="cyan")
                    table.add_column("Value", style="green")
                    for k, v in stats.items():
                        table.add_row(k, str(v))
                    console.print(table)

                elif cmd == "/model":
                    if orchestrator.last_decision:
                        d = orchestrator.last_decision
                        console.print(f"Model: {d.model} | Agent: {d.agent} | Tools: {d.tools}")
                    else:
                        console.print("[dim]No previous routing decision[/dim]")

                elif cmd == "/models":
                    models = orchestrator.llm.available_models()
                    health = orchestrator.llm.get_health_status()
                    for m in models:
                        status = "✓" if health.get(m) == "healthy" else "✗"
                        console.print(f"  [{status}] {m}")

                elif cmd == "/session":
                    console.print(f"[cyan]Session ID:[/cyan] [bold]{session_id}[/bold]")

                elif cmd.startswith("/routing"):
                    show_routing = "off" not in cmd_lower
                    console.print(f"[dim]Routing info {'enabled' if show_routing else 'disabled'}[/dim]")

                elif cmd == "/focus":
                    focus_mode = not focus_mode
                    show_routing = not focus_mode
                    console.print(f"[dim]Focus mode {'ON — events suppressed' if focus_mode else 'OFF'}[/dim]")

                elif cmd == "/stream":
                    use_streaming = not use_streaming
                    console.print(f"[dim]Streaming {'ON' if use_streaming else 'OFF'}[/dim]")

                elif cmd == "/macros":
                    await _show_macros(config)

                elif cmd == "/macro" and len(parts) >= 3:
                    macro_name = parts[1]
                    template = parts[2]
                    try:
                        from db.macros import save_macro
                        await save_macro(macro_name, template)
                        console.print(f"[green]Macro '{macro_name}' saved.[/green]")
                    except Exception as e:
                        console.print(f"[red]Could not save macro: {e}[/red]")

                elif cmd == "/brief":
                    brief_prompt = (
                        "Generate a concise daily briefing based on our conversation history. Include:\n"
                        "• Key topics discussed\n• Decisions or conclusions reached\n"
                        "• Any open questions or next steps\nKeep it under 10 bullets."
                    )
                    response = await orchestrator.process(message=brief_prompt, session_id=session_id)
                    console.print(Panel(response, title="[bold]Daily Briefing[/bold]", border_style="cyan"))
                    last_response = response

                elif cmd == "/variants" and len(parts) >= 2:
                    variant_msg = user_input[len("/variants"):].strip()
                    if not variant_msg:
                        console.print("[red]Usage: /variants <your message>[/red]")
                    else:
                        console.print("[dim]Running 3 variants...[/dim]")
                        tasks = [
                            orchestrator.llm.call(
                                model="claude",
                                messages=[{"role": "user", "content": variant_msg}],
                                max_tokens=512,
                                temperature=0.9,
                            )
                            for _ in range(3)
                        ]
                        results = await asyncio.gather(*tasks, return_exceptions=True)
                        for i, r in enumerate(results, 1):
                            if isinstance(r, Exception):
                                console.print(f"[red]Variant {i} failed: {r}[/red]")
                            else:
                                console.print(Panel(str(r), title=f"[bold]Variant {i}[/bold]", border_style="dim"))

                elif cmd == "/copy":
                    block = _extract_last_code_block(last_response)
                    if not block:
                        console.print("[yellow]No code block found in last response.[/yellow]")
                    else:
                        try:
                            import subprocess
                            proc = subprocess.run(["pbcopy"], input=block.encode(), timeout=3)
                            console.print(f"[green]Copied {len(block)} chars to clipboard.[/green]")
                        except Exception:
                            console.print(f"[yellow]pbcopy unavailable. Code block:\n{block}[/yellow]")

                elif cmd == "/title":
                    if len(parts) >= 2:
                        new_title = user_input[len("/title"):].strip()
                        try:
                            from db.history import init_db, set_session_title
                            mongo_url = config.get("mongo_url", "mongodb://localhost:27017")
                            await init_db(mongo_url)
                            await set_session_title(session_id, new_title)
                            console.print(f"[green]Title set: {new_title}[/green]")
                        except Exception as e:
                            console.print(f"[red]Could not set title: {e}[/red]")
                    else:
                        try:
                            from db.history import init_db, get_session_title
                            mongo_url = config.get("mongo_url", "mongodb://localhost:27017")
                            await init_db(mongo_url)
                            title = await get_session_title(session_id)
                            console.print(f"[cyan]Title:[/cyan] {title or '(none)'}")
                        except Exception as e:
                            console.print(f"[red]{e}[/red]")

                else:
                    console.print(f"[red]Unknown command: {parts[0]}[/red]. Type /help for commands.")

                continue

            # ─── Process message ─────────────────────────────────────────────
            processed, detected_model = await preprocess_message(user_input)
            effective_model = model_override or detected_model

            if use_streaming:
                last_response = await _stream_response(orchestrator, processed, session_id, effective_model)
            else:
                last_response = await orchestrator.process(
                    message=processed,
                    stream=False,
                    show_routing=show_routing,
                    session_id=session_id,
                    preferred_model=effective_model,
                )
                console.print(f"\n[bold]Response:[/bold]\n{last_response}")

        except KeyboardInterrupt:
            console.print("\n[cyan]Ctrl+C — type /exit to quit[/cyan]")
            continue
        except EOFError:
            break
        except Exception as e:
            console.print(f"\n[red]Error: {e}[/red]")
            import traceback
            console.print(f"[dim]{traceback.format_exc()}[/dim]")


if __name__ == "__main__":
    asyncio.run(main())

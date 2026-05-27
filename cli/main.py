#!/usr/bin/env python3
"""
CLI - terminal interface with rich UI.
Run: python cli/main.py
Run: python cli/main.py --session <session_id>
Run: python cli/main.py --list-sessions
"""
import argparse
import asyncio
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.prompt import Prompt
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

from core.orchestrator import AgentOrchestrator
from config.settings import load_config

console = Console()

BANNER = """
[bold cyan]
╔═══════════════════════════════════════╗
║        🤖 AGENT SYSTEM v1.0          ║
║   Claude · Gemini · Ollama · Tools   ║
╚═══════════════════════════════════════╝
[/bold cyan]"""

HELP_TEXT = """
[bold yellow]Commands:[/bold yellow]
  [cyan]/help[/cyan]       - Show this help
  [cyan]/clear[/cyan]      - Clear conversation history
  [cyan]/stats[/cyan]      - Session statistics
  [cyan]/model[/cyan]      - Show last routing decision
  [cyan]/models[/cyan]     - List available models
  [cyan]/session[/cyan]    - Show current session ID
  [cyan]/routing on/off[/cyan] - Toggle routing info display
  [cyan]/exit[/cyan]       - Quit

[bold yellow]Examples:[/bold yellow]
  Write a bubble sort function in Python
  Find information about the latest AI models
  Explain how transformers work in ML
  /exec print('Hello World')
"""


async def _list_sessions_and_exit(config: dict) -> None:
    """List recent sessions from MongoDB and exit."""
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
        table.add_column("Preview", style="white")
        table.add_column("Updated", style="dim")
        for s in sessions:
            table.add_row(
                s["session_id"],
                s.get("preview", "")[:60],
                s.get("updated_at", "")[:19],
            )
        console.print(table)
    except Exception as e:
        console.print(f"[red]Could not load sessions: {e}[/red]")


async def main():
    parser = argparse.ArgumentParser(description="Agent System CLI")
    parser.add_argument("--session", "-s", metavar="SESSION_ID", help="Reattach to an existing session")
    parser.add_argument("--list-sessions", "-l", action="store_true", help="List recent sessions and exit")
    args = parser.parse_args()

    # Load configuration
    config = load_config()

    if args.list_sessions:
        await _list_sessions_and_exit(config)
        return

    console.print(BANNER)
    console.print("[dim]Loading system...[/dim]")

    session_id = args.session or "default"

    try:
        orchestrator = AgentOrchestrator(config)
        # Reattach: load history from MongoDB if a session ID is given
        if args.session:
            try:
                from db.history import init_db, load_context
                mongo_url = config.get("mongo_url", "mongodb://localhost:27017")
                await init_db(mongo_url)
                orchestrator.conversation_history = await load_context(session_id)
                console.print(f"[cyan]Reattached to session [bold]{session_id}[/bold] "
                               f"({len(orchestrator.conversation_history)} messages)[/cyan]")
            except Exception as e:
                console.print(f"[yellow]Could not load history for session {session_id}: {e}[/yellow]")
        console.print("[green]✓ System ready![/green]")
        console.print("[dim]Type /help to see available commands[/dim]\n")
    except Exception as e:
        console.print(f"[red]✗ Initialisation error: {e}[/red]")
        console.print("[yellow]Check your .env file and API keys[/yellow]")
        sys.exit(1)

    show_routing = True

    while True:
        try:
            # Prompt with message number
            msg_count = len(orchestrator.conversation_history) // 2 + 1
            user_input = Prompt.ask(f"\n[bold green]You[/bold green] [{msg_count}]")

            if not user_input.strip():
                continue

            # Handle commands
            if user_input.startswith("/"):
                cmd = user_input.lower().strip()

                if cmd in ("/exit", "/quit", "/q"):
                    console.print("[cyan]Goodbye! 👋[/cyan]")
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
                    console.print("[cyan]Available models:[/cyan]")
                    for m in models:
                        console.print(f"  • {m}")

                elif cmd == "/session":
                    console.print(f"[cyan]Session ID:[/cyan] [bold]{session_id}[/bold]")

                elif cmd.startswith("/routing"):
                    if "off" in cmd:
                        show_routing = False
                        console.print("[dim]Routing info disabled[/dim]")
                    else:
                        show_routing = True
                        console.print("[dim]Routing info enabled[/dim]")

                else:
                    console.print(f"[red]Unknown command: {user_input}[/red]")

                continue

            # Process message
            response = await orchestrator.process(
                message=user_input,
                stream=True,
                show_routing=show_routing,
            )

            # stream=False is currently hardcoded in the agent ReAct loop;
            # always print the collected response.
            console.print(f"\n[bold]Response:[/bold]\n{response}")

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

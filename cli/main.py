#!/usr/bin/env python3
"""
CLI - terminal interface with rich UI.
Run: python cli/main.py
"""
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
  [cyan]/routing on/off[/cyan] - Toggle routing info display
  [cyan]/exit[/cyan]       - Quit

[bold yellow]Examples:[/bold yellow]
  Write a bubble sort function in Python
  Find information about the latest AI models
  Explain how transformers work in ML
  /exec print('Hello World')
"""


async def main():
    # Load configuration
    config = load_config()

    console.print(BANNER)
    console.print("[dim]Loading system...[/dim]")

    try:
        orchestrator = AgentOrchestrator(config)
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

            # If stream=True, response was already printed during streaming
            # If stream=False, print now
            if not config.get("stream", True):
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

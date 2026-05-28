"""
Seed script — populate dev database with sample data for onboarding (#15).

Usage:
    python3 scripts/seed.py [--mongo-url mongodb://localhost:27017]
"""
import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


async def seed(mongo_url: str) -> None:
    from db.history import init_db, append_message
    import db.personas as personas_db
    import db.macros as macros_db
    import db.prompts as prompts_db
    import db.memory as memory_db

    print(f"Connecting to {mongo_url}…")
    db = await init_db(mongo_url)
    for mod in (personas_db, macros_db, prompts_db, memory_db):
        mod.set_db(db)

    # ── Sample sessions ───────────────────────────────────────────────────────
    print("Seeding sample sessions…")
    await append_message("demo-session", "user", "What is machine learning?")
    await append_message("demo-session", "assistant", "Machine learning is a branch of AI that enables systems to learn from data without explicit programming.")
    await append_message("demo-session-2", "user", "Write a Python hello world.")
    await append_message("demo-session-2", "assistant", "```python\nprint('Hello, World!')\n```")

    # ── Sample personas ───────────────────────────────────────────────────────
    print("Seeding sample personas…")
    await personas_db.save_persona(
        "senior-engineer",
        "You are a senior software engineer with 15 years of experience. Be concise, prefer simple solutions, and always mention trade-offs.",
        "Technical expert persona",
    )
    await personas_db.save_persona(
        "teacher",
        "You are a patient teacher. Use clear language, provide examples, and check for understanding. Avoid jargon.",
        "Educational persona",
    )

    # ── Sample macros ─────────────────────────────────────────────────────────
    print("Seeding sample macros…")
    await macros_db.save_macro(
        "/review",
        "Please review the following code for bugs, performance issues, and best practices:\n\n{code}",
        "Code review template",
    )
    await macros_db.save_macro(
        "/explain",
        "Explain the following concept in simple terms suitable for a beginner:\n\n{concept}",
        "Beginner explanation template",
    )
    await macros_db.save_macro(
        "/test",
        "Write comprehensive unit tests for the following code using pytest:\n\n{code}",
        "Unit test generation template",
    )

    # ── Sample saved prompts ──────────────────────────────────────────────────
    print("Seeding sample prompts…")
    await prompts_db.save_prompt(
        "demo-session",
        "Debug assistant",
        "You are a debugging assistant. When given code and an error, identify the root cause and suggest the minimal fix.",
        tags=["debug", "code"],
    )
    await prompts_db.save_prompt(
        "demo-session",
        "SQL expert",
        "You are an expert SQL developer. Optimise queries, explain execution plans, and follow best practices for the target DB.",
        tags=["sql", "database"],
    )

    print("Seed complete.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed development database")
    parser.add_argument("--mongo-url", default="mongodb://localhost:27017", help="MongoDB connection URL")
    args = parser.parse_args()
    asyncio.run(seed(args.mongo_url))


if __name__ == "__main__":
    main()

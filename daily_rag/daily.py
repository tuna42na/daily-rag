import argparse
import sys
from datetime import date
from pathlib import Path

from . import config
from .calendar import export_calendar
from .coaching import plan_day, render_plan
from .generate import answer
from .ingest import ingest
from .personal import refresh


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate news, evidence-based coaching, and calendar tasks.")
    parser.add_argument("--no-ingest", action="store_true", help="Skip web refresh; local context still refreshes.")
    parser.add_argument("--no-check-in", action="store_true", help="Do not prompt for a daily check-in.")
    args = parser.parse_args()
    if not args.no_ingest:
        ingest()
    documents = refresh()
    journal_path = Path(config.JOURNAL_PATH)
    today = date.today()
    if not args.no_check_in and sys.stdin.isatty():
        yesterday = input("What did you do yesterday? Include results or artifacts: ").strip()
        planned = input("What are you doing today? Include blockers or constraints: ").strip()
        if yesterday or planned:
            journal_path.parent.mkdir(parents=True, exist_ok=True)
            with journal_path.open("a", encoding="utf-8") as journal:
                journal.write(f"\n## {today}\n\n- Yesterday: {yesterday}\n- Today: {planned}\n")
    recent = ""
    if journal_path.exists():
        recent = "\n\n## ".join(journal_path.read_text(encoding="utf-8").split("\n## ")[-3:])
    state, plan = plan_day(today, documents, recent)
    calendar_path = export_calendar(state)
    items = answer(
        f"top news topics and reporting across all sources, relevant to: {config.PROFILE}",
        "Write a concise topic-level news breakdown across the provided web sources. "
        "Group related reporting under a few themes, citing URLs. Highlight relevance "
        "to the user's active projects when supported. Do not use personal documents "
        "as evidence of news. If web evidence is absent, say so.",
        recent,
    )
    md = f"# News & Coaching for {today}\n\n{items}\n\n{render_plan(state, plan)}\n"
    md += f"\nCalendar export: `{calendar_path}` (all-day events; not synced).\n"
    output = Path(config.OUTPUT_DIR)
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{today}.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()

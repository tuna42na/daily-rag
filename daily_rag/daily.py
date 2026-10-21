import sys
from datetime import date
from pathlib import Path

from . import config
from .generate import answer
from .ingest import ingest

if "--no-ingest" not in sys.argv:
    ingest()

journal_path = Path(config.JOURNAL_PATH)
# Last few entries only, to keep the prompt small.
recent = ""
if journal_path.exists():
    recent = "\n\n## ".join(journal_path.read_text().split("\n## ")[-3:])

today = date.today().isoformat()
items = answer(
    f"top news topics and reporting across all sources, relevant to: {config.PROFILE}",
    "Write a concise topic-level news breakdown across the provided sources. Group related reporting under a few themes and explain what is being reported, noting which sources cover each topic and any overlap or differences when supported. Do not make article headlines or a story-by-story list the main structure; use individual articles only as supporting examples. Cite the source URL for each topic. If the sources do not support a meaningful topic, say so.",
    recent,
)
daily_task = answer(
    f"daily tasks and priorities for: {config.PROFILE}",
    "Produce a concise markdown summary of my top priorities and tasks for today, with any relevant context or notes. "
    "Factor in what I did yesterday and what I plan to do today from my check-ins.",
    recent,
)
md = f"# News & Topics for {today}\n\n{items}\n\n## Daily Tasks\n\n{daily_task}\n"
Path(config.OUTPUT_DIR).mkdir(exist_ok=True)
Path(config.OUTPUT_DIR, f"{today}.md").write_text(md)
print(md)

if sys.stdin.isatty():
    yesterday = input("What did you do yesterday? ").strip()
    planned = input("What are you doing today? ").strip()
    if yesterday or planned:
        journal_path.parent.mkdir(exist_ok=True)
        with journal_path.open("a") as f:
            f.write(f"\n## {today}\n\n- Yesterday: {yesterday}\n- Today: {planned}\n")

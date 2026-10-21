import sys
from datetime import date
from pathlib import Path

from . import config
from .generate import answer
from .ingest import ingest

if "--no-ingest" not in sys.argv:
    ingest()

today = date.today().isoformat()
items = answer(
    f"actionable items, deadlines, and news relevant to: {config.PROFILE}",
    "Produce a prioritized markdown checklist (- [ ] item) of things I should do or read today, with the source URL on each item.",
)
daily_task = answer(
    f"daily tasks and priorities for: {config.PROFILE}",
    "Produce a concise markdown summary of my top priorities and tasks for today, with any relevant context or notes.",
)
md = f"# To-do for {today}\n\n{items}\n\n## Daily Tasks\n\n{daily_task}\n"
Path(config.OUTPUT_DIR).mkdir(exist_ok=True)
Path(config.OUTPUT_DIR, f"{today}.md").write_text(md)
print(md)

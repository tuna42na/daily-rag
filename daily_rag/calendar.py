from datetime import timedelta
from pathlib import Path

from . import config
from .tasks import State


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\r\n", "\n").replace("\r", "\n").replace(
        "\n", "\\n"
    ).replace(";", "\\;").replace(",", "\\,")


def _fold(line: str) -> str:
    parts = []
    current = ""
    for char in line:
        if len((current + char).encode("utf-8")) > 75:
            parts.append(current)
            current = " "
        current += char
    parts.append(current)
    return "\r\n".join(parts)


def export_calendar(state: State) -> Path:
    """Write one replaceable calendar feed with stable IDs across reruns and reschedules."""
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//daily-rag//Personal Coach//EN", "CALSCALE:GREGORIAN"]
    for task in sorted(state.tasks.values(), key=lambda item: (item.scheduled_for, item.id)):
        description = (
            f"{task.reason}\n\nDone when: {task.success_criteria}"
            f"\n\nEvidence: {', '.join(task.evidence)}\nTask ID: {task.id}"
            f"\nSupporting quote: {state.evidence[task.evidence[0]]}"
        )
        for feedback in task.feedback:
            description += f"\n{feedback.at.isoformat()} [{feedback.status}]: {feedback.note}"
        title = task.title if task.status == "planned" else f"[{task.status}] {task.title}"
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:{task.id}@daily-rag.local",
            f"DTSTAMP:{task.updated_at.strftime('%Y%m%dT%H%M%SZ')}",
            f"CREATED:{task.created_at.strftime('%Y%m%dT%H%M%SZ')}",
            f"LAST-MODIFIED:{task.updated_at.strftime('%Y%m%dT%H%M%SZ')}",
            f"SEQUENCE:{task.revision}",
            f"DTSTART;VALUE=DATE:{task.scheduled_for.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(task.scheduled_for + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_escape(title)}",
            f"DESCRIPTION:{_escape(description)}",
            "STATUS:CANCELLED" if task.status == "skipped" else "STATUS:CONFIRMED",
            "TRANSP:TRANSPARENT",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    path = Path(config.OUTPUT_DIR, "tasks.ics")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\r\n".join(_fold(line) for line in lines) + "\r\n").encode("utf-8"))
    return path

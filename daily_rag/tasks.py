import argparse
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from . import config

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Status = Literal["planned", "done", "skipped", "blocked"]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Suggestion(Model):
    title: Text
    category: Literal["build", "learning", "resume", "review", "unblock"]
    reason: Text
    evidence: list[Text] = Field(min_length=1, max_length=1)
    success_criteria: Text


class Observation(Model):
    kind: Literal["observed", "evidence_gap"]
    finding: Text
    evidence: list[Text] = Field(min_length=1, max_length=1)
    next_step: Text


class Proposal(Model):
    observations: list[Observation] = Field(max_length=3)
    tasks: list[Suggestion] = Field(max_length=3)


class Feedback(Model):
    at: datetime
    status: Status
    note: Text


class Task(Suggestion):
    id: Text
    created_at: datetime
    updated_at: datetime
    scheduled_for: date
    status: Status = "planned"
    revision: int = Field(default=0, ge=0)
    feedback: list[Feedback] = Field(default_factory=list)


class Plan(Model):
    task_ids: list[str] = Field(max_length=3)
    observations: list[Observation] = Field(max_length=3)


class State(Model):
    version: Literal[1] = 1
    tasks: dict[str, Task] = Field(default_factory=dict)
    plans: dict[date, Plan] = Field(default_factory=dict)
    evidence: dict[str, str] = Field(default_factory=dict)


def load_state() -> State:
    path = Path(config.TASKS_PATH)
    state = State.model_validate_json(path.read_text()) if path.exists() else State()
    if any(key != task.id for key, task in state.tasks.items()):
        raise ValueError("Task log contains mismatched task IDs.")
    if any(task_id not in state.tasks for plan in state.plans.values() for task_id in plan.task_ids):
        raise ValueError("Task log contains a plan referring to a missing task.")
    evidence_lists = [task.evidence for task in state.tasks.values()]
    evidence_lists += [item.evidence for plan in state.plans.values() for item in plan.observations]
    if any(key not in state.evidence for keys in evidence_lists for key in keys):
        raise ValueError("Task log is missing a cited evidence snapshot.")
    return state


def save_state(state: State) -> None:
    path = Path(config.TASKS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.write_text(state.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def record_feedback(task_id: str, status: Status, note: str) -> Task:
    state = load_state()
    if task_id not in state.tasks:
        raise ValueError(f"Unknown task ID: {task_id}")
    task = state.tasks[task_id]
    now = datetime.now(timezone.utc)
    feedback = Feedback(at=now, status=status, note=note)
    task.feedback.append(feedback)
    task.status = status
    task.updated_at = now
    task.revision += 1
    save_state(state)
    return task


def feedback_context(state: State) -> dict[str, str]:
    """Keep open work and the latest 30 closed tasks as explicitly self-reported evidence."""
    ordered = sorted(state.tasks.values(), key=lambda task: task.updated_at, reverse=True)
    closed = [task for task in ordered if task.status in {"done", "skipped"}][:30]
    active = [task for task in ordered if task.status in {"planned", "blocked"}]
    return {
        f"task:{task.id}@{task.revision}": task.model_dump_json()
        for task in active + closed
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Track self-reported task outcomes and blockers.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    update = commands.add_parser("update")
    update.add_argument("id")
    update.add_argument("status", choices=["planned", "done", "skipped", "blocked"])
    update.add_argument("--note", required=True, help="Result/artifact, reason for skipping, or blocker.")
    args = parser.parse_args()
    if args.command == "update":
        record_feedback(args.id, args.status, args.note)
        from .calendar import export_calendar

        export_calendar(load_state())
        print(f"Updated {args.id}: {args.status}")
    else:
        for task in sorted(load_state().tasks.values(), key=lambda item: (item.scheduled_for, item.id)):
            print(f"{task.id}  {task.scheduled_for}  {task.status}: {task.title}")


if __name__ == "__main__":
    main()

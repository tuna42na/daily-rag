import hashlib
import re
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import ollama

from . import config
from .generate import COACH_RULES
from .personal import Document
from .tasks import Observation, Plan, Proposal, State, Suggestion, Task, feedback_context, load_state, save_state

INITIAL_EVIDENCE = "task-history:no-outcomes"
INITIAL_FINDING = "No task outcome feedback was available when this plan was created."


def initial_review() -> Observation:
    return Observation(
        kind="evidence_gap",
        finding="There is not enough recorded outcome evidence to assess progress or skill gaps yet.",
        evidence=[INITIAL_EVIDENCE],
        next_step="After each task, record its concrete artifact or blocker with tasks update. "
        "Use those outcomes, not resume omissions, to identify weak spots and justified resume updates.",
    )


def outcome_reviews(state: State) -> list[Observation]:
    reviews = []
    available = feedback_context(state)
    ordered = sorted(state.tasks.values(), key=lambda task: task.updated_at, reverse=True)
    ordered.sort(key=lambda task: {"blocked": 0, "skipped": 1, "done": 2, "planned": 3}[task.status])
    for task in ordered:
        if not task.feedback or task.status == "planned":
            continue
        source = f"task:{task.id}@{task.revision}"
        if source not in available:
            continue
        note = task.feedback[-1].note
        if task.status == "blocked":
            count = sum(entry.status == "blocked" for entry in task.feedback)
            finding = f"'{task.title}' has been reported blocked {count} time(s). Latest blocker: {note}"
            action = (
                "Use the next session to isolate and resolve that blocker with a smaller test, "
                "note, or diagram. Record the resulting artifact before calling the original task done."
            )
        elif task.status == "skipped":
            finding = f"You skipped '{task.title}': {note}"
            action = "Check whether this goal still belongs in the roadmap. Reduce or remove its scope rather than repeatedly rescheduling unchanged work."
        else:
            finding = f"You reported completing '{task.title}': {note}"
            action = (
                "Verify the artifact against the completion criterion. Compare the demonstrated "
                "skill/result with your resume; update a bullet only if there is a defensible "
                "new achievement. A planning note is not a shipped product."
            )
        reviews.append(Observation(
            kind="observed", finding=finding, evidence=[source], next_step=action
        ))
        if len(reviews) == 3:
            break
    return reviews


def roadmap_queue(documents: list[Document], state: State) -> list[Suggestion]:
    """Keep explicit unchecked roadmap work in source order instead of guessing priorities."""
    known = {task.title.casefold() for task in state.tasks.values()}
    queue = []
    for doc in documents:
        if "roadmap" not in Path(doc.source).stem.lower():
            continue
        learning_section = False
        for number, line in enumerate(doc.text.splitlines(), 1):
            if re.match(r"^#{1,6}\s+Parking lot\b", line, re.IGNORECASE):
                break
            if line.startswith("### "):
                learning_section = "software engineering" in line.lower()
            for match in re.finditer(r"\[ \]\s*([^|\n]+)", line):
                title = match.group(1).replace("**", "").replace("`", "").strip()
                if not title or title.casefold() in known:
                    continue
                reason = "Next unchecked roadmap item, kept in prerequisite order."
                success_criteria = f"Record the resulting file, test, note, diagram, or demo that completes: {title}"
                if "; Why: " in title:
                    title, details = title.split("; Why: ", 1)
                    if "; Done when: " in details:
                        reason, success_criteria = details.split("; Done when: ", 1)
                    else:
                        reason = details
                    title = title.strip()
                known.add(title.casefold())
                category = "learning" if title.startswith("ENG ") or learning_section else "build"
                if title.startswith("REVIEW "):
                    category = "review"
                queue.append(Suggestion(
                    title=title,
                    category=category,
                    reason=reason.strip(),
                    evidence=[f"{doc.source}@{doc.fingerprint[:12]}:L{number}"],
                    success_criteria=success_criteria.strip(),
                ))
    return queue


def plan_day(today: date, documents: list[Document], journal: str) -> tuple[State, Plan]:
    limit = config.DAILY_TASK_LIMIT
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 3:
        raise ValueError("DAILY_TASK_LIMIT must be an integer between 1 and 3.")
    state = load_state()
    has_outcomes = any(task.feedback for task in state.tasks.values()) or bool(journal.strip())
    if today in state.plans and (state.plans[today].task_ids or not documents):
        if documents and not has_outcomes:
            state.plans[today].observations = [initial_review()]
            state.evidence[INITIAL_EVIDENCE] = INITIAL_FINDING
            save_state(state)
        return state, state.plans[today]
    open_tasks = sorted(
        (task for task in state.tasks.values() if task.status in {"planned", "blocked"}),
        key=lambda task: (task.scheduled_for, task.created_at),
    )
    carried = open_tasks[:limit]
    sources = {}
    for doc in documents:
        for line_number, line in enumerate(doc.text.splitlines(), 1):
            if line.strip():
                sources[f"{doc.source}@{doc.fingerprint[:12]}:L{line_number}"] = line.strip()
    sources.update(feedback_context(state))
    if documents and not has_outcomes:
        sources[INITIAL_EVIDENCE] = INITIAL_FINDING
    if journal.strip():
        revision = hashlib.sha256(journal.encode("utf-8")).hexdigest()[:12]
        sources[f"journal:{today}@{revision}"] = journal
    remaining = limit - len(carried)
    queued = roadmap_queue(documents, state)[:remaining]
    remaining -= len(queued)
    reviews = outcome_reviews(state)
    if documents and not has_outcomes:
        reviews = [initial_review()]
    evidence_text = "\n\n---\n\n".join(f"[source: {key}]\n{text}" for key, text in sources.items())
    schema = Proposal.model_json_schema()
    schema["properties"]["tasks"]["maxItems"] = remaining
    minimum = 1 if documents and not carried and not queued else 0
    schema["properties"]["tasks"]["minItems"] = minimum
    schema["properties"]["observations"]["minItems"] = 1 if documents else 0
    if not has_outcomes or reviews:
        schema["properties"]["observations"]["minItems"] = 0
        schema["properties"]["observations"]["maxItems"] = 0
    outcome_keys = []
    if sources:
        for name in ("Suggestion", "Observation"):
            schema["$defs"][name]["properties"]["evidence"]["items"]["enum"] = list(sources)
        outcome_keys = [
            key for key in sources
            if key.startswith("journal:") or any(
                key == f"task:{task.id}@{task.revision}" and task.feedback
                for task in state.tasks.values()
            )
        ]
        if outcome_keys:
            schema["$defs"]["Observation"]["properties"]["evidence"]["items"]["enum"] = outcome_keys
    else:
        schema["properties"]["tasks"]["maxItems"] = 0
        schema["properties"]["observations"]["maxItems"] = 0
    messages = [
            {"role": "system", "content": COACH_RULES},
            {
                "role": "user",
                "content": (
                    f"Today: {today}. Profile: {config.PROFILE}\n"
                    f"Evidence sources:\n{evidence_text}\n\n"
                    f"Already scheduled carryover task IDs: {[task.id for task in carried]}.\n"
                    f"Already selected roadmap tasks: {[item.title for item in queued]}.\n"
                    f"Suggest between zero and {remaining} NEW tasks, never more. "
                    f"At least {minimum} new task is required. When personal documents exist "
                    "and no work is carried over, choose a concrete next roadmap step. If "
                    "progress is unclear or all listed work appears done, make the task a "
                    "status/artifact review instead of inventing progress or returning nothing. "
                    f"Return observations only if recorded outcomes or check-ins exist: {has_outcomes}. "
                    "Uncertainty must be an evidence_gap with a verification step. "
                    "Carryover counts against the daily budget. Respect any LOWER task budget "
                    "in the roadmap, its prerequisite order, checked items, alternating tracks, "
                    "and non-goals. Day numbers are sequence positions, not deadlines. "
                    "Do not repeat open, completed, or skipped tasks from history. "
                    "Prioritize the EARLIEST unchecked roadmap work. Unchecked roadmap items "
                    "are NOT existing experience to put on a resume. Do not schedule parked "
                    "or deferred work. Do not suggest a resume achievement without a documented "
                    "completed result. An artifact is mandatory: 'gain understanding' is not "
                    "a completion criterion. "
                    "If a completed roadmap item supports a new resume bullet or reveals an "
                    "outdated claim, suggest a specific resume update with an artifact to verify. "
                    "Pair learning with the earliest unfinished project work; do not let news "
                    "distract from prerequisites. Define a concrete, verifiable artifact for "
                    "every success_criteria. Suggest unblock/review work when appropriate. "
                    "Assess progress from self-reported feedback, repeated blockers, and "
                    "artifact evidence; do not equate missing evidence with lack of ability. "
                    "Focus observations on the recorded outcomes and blockers, not a generic "
                    "resume skill audit. Cite an outcome/check-in source for each observation. "
                    "Use kind=evidence_gap for uncertainty and kind=observed only for supported "
                    "observations. Each finding needs an actionable next_step. Cite at least "
                    "one EXACT evidence-source key in every evidence list. Each personal-document "
                    "key identifies a line of source text. Choose the specific line that supports "
                    "the recommendation or observation, not an unrelated heading or resume skill. "
                    "The application will attach the original text as the supporting quote. "
                    "No source keys means no tasks or observations. Return JSON matching the schema."
                ),
            },
        ]
    if remaining == 0 and (not has_outcomes or reviews):
        proposal = Proposal(tasks=[], observations=[])
    else:
        response = ollama.chat(
            model=config.CHAT_MODEL,
            options={"num_ctx": config.MODEL_CONTEXT_TOKENS, "temperature": 0},
            format=schema,
            messages=messages,
        )
        proposal = Proposal.model_validate_json(response["message"]["content"])
    if len(proposal.tasks) < minimum:
        raise ValueError("Planner returned no task despite available personal context and capacity.")
    if len(proposal.tasks) > remaining:
        raise ValueError(f"Planner returned {len(proposal.tasks)} tasks for {remaining} available slots.")
    for item in [*proposal.tasks, *proposal.observations]:
        unknown = set(item.evidence) - sources.keys()
        if unknown:
            raise ValueError(f"Planner cited unknown evidence: {sorted(unknown)}")
    if outcome_keys and any(
        item.evidence[0] not in outcome_keys for item in proposal.observations
    ):
        raise ValueError("Coaching observations must cite recorded outcomes or check-ins.")
    if reviews:
        proposal.observations = reviews
    existing_titles = {task.title.casefold() for task in state.tasks.values()}
    existing_titles.update(item.title.casefold() for item in queued)
    for suggestion in proposal.tasks:
        title = suggestion.title.casefold()
        if title in existing_titles:
            raise ValueError(f"Planner repeated an existing task: {suggestion.title}")
        existing_titles.add(title)
    now = datetime.now(timezone.utc)
    ids = []
    for task in carried:
        task.scheduled_for = today
        task.updated_at = now
        task.revision += 1
        ids.append(task.id)
    for suggestion in [*queued, *proposal.tasks]:
        task = Task(
            **suggestion.model_dump(),
            id=uuid4().hex,
            created_at=now,
            updated_at=now,
            scheduled_for=today,
        )
        state.tasks[task.id] = task
        ids.append(task.id)
    for item in [*queued, *proposal.tasks, *proposal.observations]:
        for key in item.evidence:
            state.evidence[key] = sources[key]
    plan = Plan(task_ids=ids, observations=proposal.observations)
    state.plans[today] = plan
    save_state(state)
    return state, plan


def render_plan(state: State, plan: Plan) -> str:
    lines = ["## Coaching Review", ""]
    for observation in plan.observations:
        label = "Evidence gap" if observation.kind == "evidence_gap" else "Observed"
        lines.extend([
            f"- **{label}:** {observation.finding}",
            f"  - Next step: {observation.next_step}",
            f"  - Evidence: {', '.join(observation.evidence)}",
            f"  - Supporting quote: {state.evidence[observation.evidence[0]]}",
        ])
    if not plan.observations:
        lines.append("Not enough evidence for a constructive assessment today.")
    lines.extend(["", "## Daily Tasks", ""])
    for task_id in plan.task_ids:
        task = state.tasks[task_id]
        checked = "x" if task.status == "done" else " "
        lines.extend([
            f"- [{checked}] **{task.title}** ({task.category}; {task.status})",
            f"  - Why: {task.reason}",
            f"  - Done when: {task.success_criteria}",
            f"  - Evidence: {', '.join(task.evidence)}",
            f"  - Task ID: `{task.id}`",
        ])
        if task.feedback:
            lines.append(f"  - Latest feedback: {task.feedback[-1].note}")
    if not plan.task_ids:
        lines.append("No evidence-backed tasks scheduled today.")
    return "\n".join(lines)

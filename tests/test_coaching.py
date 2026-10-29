import io
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from pydantic import ValidationError
from pypdf import PdfWriter

from daily_rag import calendar, coaching, config, daily, generate, personal, store, tasks


class CoachingTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.personal_dir = self.root / "personal-context"
        self.personal_dir.mkdir()
        self.patch = patch.multiple(
            config,
            PERSONAL_CONTEXT_DIR=str(self.personal_dir),
            PERSONAL_CONTEXT_CACHE=str(self.root / "data/context.json"),
            TASKS_PATH=str(self.root / "data/tasks.json"),
            INDEX_PATH=str(self.root / "data/index.json"),
            JOURNAL_PATH=str(self.root / "data/journal.md"),
            OUTPUT_DIR=str(self.root / "output"),
            PERSONAL_CONTEXT_MAX_CHARS=40000,
            DAILY_TASK_LIMIT=2,
        )
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.today = date(2026, 10, 22)
        self.document = personal.Document(
            source="personal-context/roadmap.md", fingerprint="123456789abc", text="Two tasks per day."
        )
        self.source = "personal-context/roadmap.md@123456789abc:L1"
        self.suggestion = {
            "title": "Write MVP scope",
            "category": "build",
            "reason": "Define scope before implementing the service.",
            "evidence": [self.source],
            "success_criteria": "A one-page scope note with explicit non-goals.",
        }
        self.proposal = {
            "observations": [{
                "kind": "evidence_gap",
                "finding": "No implementation artifact has been reported.",
                "evidence": [self.source],
                "next_step": "Report the first scope note.",
            }],
            "tasks": [self.suggestion],
        }

    def response(self, proposal=None):
        return {"message": {"content": json.dumps(self.proposal if proposal is None else proposal)}}

    def create_plan(self):
        with patch.object(
            coaching.ollama, "chat", return_value=self.response()
        ):
            return coaching.plan_day(self.today, [self.document], "")

    def test_refresh_changed_removed_and_nested_text_files(self):
        roadmap = self.personal_dir / "roadmap.md"
        roadmap.write_text("Initial roadmap")
        nested = self.personal_dir / "notes"
        nested.mkdir()
        (nested / "goals.txt").write_text("Learn Go")
        (self.personal_dir / "ignored.docx").write_text("Not supported")
        (self.personal_dir / ".hidden.md").write_text("Hidden")
        docs = personal.refresh()
        self.assertEqual(len(docs), 2)
        original = next(doc for doc in docs if doc.source.endswith("roadmap.md"))
        roadmap.write_text("Revised roadmap")
        docs = personal.refresh()
        revised = next(doc for doc in docs if doc.source.endswith("roadmap.md"))
        self.assertNotEqual(original.fingerprint, revised.fingerprint)
        self.assertEqual(revised.text, "Revised roadmap")
        roadmap.unlink()
        docs = personal.refresh()
        self.assertEqual(len(docs), 1)
        self.assertNotIn("Revised roadmap", Path(config.PERSONAL_CONTEXT_CACHE).read_text())
        (nested / "goals.txt").unlink()
        nested.rmdir()
        self.assertEqual(personal.refresh(), [])

    def test_pdf_extraction_is_cached_by_content_not_mtime(self):
        pdf = self.personal_dir / "resume.pdf"
        pdf.write_bytes(b"first revision")
        reader = Mock()
        reader.pages = [Mock(), Mock()]
        reader.pages[0].extract_text.return_value = "Resume page one"
        reader.pages[1].extract_text.return_value = "Resume page two"
        with patch.object(personal, "PdfReader", return_value=reader) as parse:
            first = personal.refresh()
            self.assertIn("Resume page two", first[0].text)
            self.assertEqual(personal.refresh(), first)
            self.assertEqual(parse.call_count, 1)
            pdf.write_bytes(b"second revision")
            personal.refresh()
            self.assertEqual(parse.call_count, 2)

    def test_blank_pdf_fails_without_overwriting_good_cache(self):
        (self.personal_dir / "roadmap.md").write_text("Good context")
        personal.refresh()
        cached = Path(config.PERSONAL_CONTEXT_CACHE).read_bytes()
        with PdfWriter() as writer:
            writer.add_blank_page(width=300, height=300)
            writer.write(self.personal_dir / "blank.pdf")
        with self.assertRaisesRegex(ValueError, "No readable text"):
            personal.refresh()
        self.assertEqual(Path(config.PERSONAL_CONTEXT_CACHE).read_bytes(), cached)

    def test_excess_context_and_symlink_fail_explicitly(self):
        note = self.personal_dir / "notes.md"
        note.write_text("abcdef")
        with patch.object(config, "PERSONAL_CONTEXT_MAX_CHARS", 5):
            with self.assertRaisesRegex(ValueError, "6 characters"):
                personal.refresh()
        (self.personal_dir / "linked.txt").symlink_to(note)
        with self.assertRaisesRegex(ValueError, "symlinks"):
            personal.refresh()

    def test_plan_persists_evidence_and_is_idempotent_same_day(self):
        state, plan = self.create_plan()
        self.assertEqual(len(plan.task_ids), 1)
        self.assertEqual(state.evidence[self.source], self.document.text)
        with patch.object(coaching.ollama, "chat") as model:
            restored, same = coaching.plan_day(self.today, [], "Changed check-in")
            model.assert_not_called()
        self.assertEqual(plan, same)
        self.assertEqual(state, restored)
        rendered = coaching.render_plan(state, plan)
        self.assertIn("Done when:", rendered)
        self.assertNotIn("Supporting quote:", rendered)

    def test_unknown_evidence_and_invalid_json_do_not_save_plan(self):
        invalid = dict(self.suggestion, evidence=["invented-source"])
        cases = [
            (self.response({"tasks": [invalid], "observations": []}), ValueError),
            ({"message": {"content": "not JSON"}}, ValidationError),
            (self.response({"tasks": [dict(self.suggestion, title=" ")], "observations": []}), ValidationError),
        ]
        for response, error in cases:
            with self.subTest(response=response), patch.object(coaching.ollama, "chat", return_value=response):
                with self.assertRaises(error):
                    coaching.plan_day(self.today, [self.document], "")
                self.assertFalse(Path(config.TASKS_PATH).exists())

    def test_configured_cap_and_hard_three_task_cap(self):
        for limit in [0, 4, True, "2"]:
            with self.subTest(limit=limit), patch.object(config, "DAILY_TASK_LIMIT", limit):
                with self.assertRaisesRegex(ValueError, "between 1 and 3"):
                    coaching.plan_day(self.today, [], "")
        with patch.object(
            coaching.ollama, "chat",
            return_value=self.response({"tasks": [self.suggestion] * 3, "observations": []}),
        ):
            with self.assertRaisesRegex(ValueError, "available slots"):
                coaching.plan_day(self.today, [self.document], "")
        with self.assertRaises(ValidationError):
            tasks.Proposal(tasks=[self.suggestion] * 4, observations=[])

    def test_duplicate_titles_in_proposal_rejected(self):
        with patch.object(
            coaching.ollama, "chat",
            return_value=self.response({"tasks": [self.suggestion] * 2, "observations": []}),
        ):
            with self.assertRaisesRegex(ValueError, "repeated"):
                coaching.plan_day(self.today, [self.document], "")
        self.assertFalse(Path(config.TASKS_PATH).exists())

    def test_empty_saved_plan_is_reconsidered_when_documents_become_available(self):
        tasks.save_state(tasks.State(plans={self.today: tasks.Plan(task_ids=[], observations=[])}))
        state, plan = self.create_plan()
        self.assertEqual(len(plan.task_ids), 1)
        self.assertEqual(len(state.tasks), 1)

    def test_no_task_with_personal_context_is_rejected(self):
        with patch.object(
            coaching.ollama, "chat", return_value=self.response({"tasks": [], "observations": []})
        ):
            with self.assertRaisesRegex(ValueError, "no task"):
                coaching.plan_day(self.today, [self.document], "")
        self.assertFalse(Path(config.TASKS_PATH).exists())

    def test_supporting_quote_is_attached_from_source_not_generated(self):
        state, plan = self.create_plan()
        self.assertNotIn("Supporting quote:", coaching.render_plan(state, plan))
        unfolded = calendar.export_calendar(state).read_text().replace("\n ", "")
        self.assertIn("Supporting quote: Two tasks per day.", unfolded)
        state.evidence.clear()
        tasks.save_state(state)
        with self.assertRaisesRegex(ValueError, "missing a cited evidence snapshot"):
            tasks.load_state()

    def test_roadmap_inline_details_set_task_reason_and_completion_criteria(self):
        document = personal.Document(
            source="personal-context/roadmap.md",
            fingerprint="abcdef123456",
            text=(
                "| 01 | [ ] **ABI** Draft the MVP brief; Why: Set scope first. "
                "; Done when: The brief names the user and non-goals. |"
            ),
        )

        [suggestion] = coaching.roadmap_queue([document], tasks.State())

        self.assertEqual(suggestion.title, "ABI Draft the MVP brief")
        self.assertEqual(suggestion.reason, "Set scope first.")
        self.assertEqual(suggestion.success_criteria, "The brief names the user and non-goals.")

    def test_feedback_carryover_and_closed_tasks(self):
        _, plan = self.create_plan()
        task_id = plan.task_ids[0]
        tasks.record_feedback(task_id, "blocked", "Need scope review")
        empty = {"tasks": [], "observations": []}
        with patch.object(
            coaching.ollama, "chat", return_value=self.response(empty)
        ) as model:
            following, next_plan = coaching.plan_day(self.today + timedelta(days=1), [self.document], "")
        self.assertEqual(next_plan.task_ids, [task_id])
        self.assertEqual(following.tasks[task_id].scheduled_for, self.today + timedelta(days=1))
        self.assertEqual(following.tasks[task_id].status, "blocked")
        self.assertIn("between zero and 1 NEW tasks", model.call_args.kwargs["messages"][1]["content"])
        self.assertIn("Need scope review", model.call_args.kwargs["messages"][1]["content"])
        self.assertIn("Need scope review", next_plan.observations[0].finding)
        tasks.record_feedback(task_id, "done", "Scope note committed: abc123")
        with patch.object(
            coaching.ollama, "chat", return_value=self.response(empty)
        ):
            final, final_plan = coaching.plan_day(self.today + timedelta(days=2), [], "")
        self.assertEqual(final_plan.task_ids, [])
        self.assertEqual(len(final.tasks[task_id].feedback), 2)
        self.assertEqual(final.evidence[self.source], self.document.text)
        self.assertIn("resume", final_plan.observations[0].next_step)

    def test_feedback_validation_and_corrupt_state_are_not_silenced(self):
        state, plan = self.create_plan()
        with self.assertRaisesRegex(ValueError, "Unknown task"):
            tasks.record_feedback("missing", "done", "artifact")
        with self.assertRaises(ValidationError):
            tasks.record_feedback(plan.task_ids[0], "done", " ")
        self.assertEqual(tasks.load_state(), state)
        Path(config.TASKS_PATH).write_text("{corrupt")
        with self.assertRaises(ValidationError):
            tasks.load_state()

    def test_repeated_blockers_get_specific_recovery_review(self):
        _, plan = self.create_plan()
        task_id = plan.task_ids[0]
        tasks.record_feedback(task_id, "blocked", "Cannot explain TLS")
        tasks.record_feedback(task_id, "planned", "Trying a smaller diagram")
        tasks.record_feedback(task_id, "blocked", "TLS section still incomplete")
        review = coaching.outcome_reviews(tasks.load_state())[0]
        self.assertIn("blocked 2 time(s)", review.finding)
        self.assertIn("TLS section still incomplete", review.finding)
        self.assertIn("smaller test", review.next_step)

    def test_skipped_task_prompts_scope_review_not_automatic_reschedule(self):
        _, plan = self.create_plan()
        tasks.record_feedback(plan.task_ids[0], "skipped", "Scope changed")
        review = coaching.outcome_reviews(tasks.load_state())[0]
        self.assertIn("Scope changed", review.finding)
        self.assertIn("Reduce or remove", review.next_step)

    def test_calendar_dates_ids_folding_escaping_and_revisions(self):
        state, plan = self.create_plan()
        task_id = plan.task_ids[0]
        task = state.tasks[task_id]
        task.title = "Resume, review; " + "\N{LATIN SMALL LETTER E WITH ACUTE}" * 80
        task.reason = "Line one\r\nBEGIN:VEVENT\nBackslash: \\"
        tasks.save_state(state)
        path = calendar.export_calendar(state)
        raw = path.read_bytes()
        self.assertTrue(raw.endswith(b"\r\n"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        for line in raw.split(b"\r\n"):
            self.assertLessEqual(len(line), 75)
            line.decode("utf-8")
        unfolded = raw.decode().replace("\r\n ", "")
        self.assertEqual(unfolded.count("\r\nBEGIN:VEVENT\r\n"), 1)
        self.assertIn("DTSTART;VALUE=DATE:20261022", unfolded)
        self.assertIn("DTEND;VALUE=DATE:20261023", unfolded)
        self.assertIn("SUMMARY:Resume\\, review\\;", unfolded)
        self.assertIn("Line one\\nBEGIN:VEVENT\\nBackslash: \\\\", unfolded)
        self.assertEqual(calendar.export_calendar(state).read_bytes(), raw)
        tasks.record_feedback(task_id, "skipped", "Scope changed")
        updated = calendar.export_calendar(tasks.load_state()).read_text()
        self.assertIn(f"UID:{task_id}@daily-rag.local", updated)
        self.assertIn("SEQUENCE:1", updated)
        self.assertIn("STATUS:CANCELLED", updated)
        self.assertIn("[skipped]", updated)

    def test_calendar_stable_uid_on_carryover_and_year_boundary(self):
        self.today = date(2026, 12, 31)
        state, plan = self.create_plan()
        task_id = plan.task_ids[0]
        output = calendar.export_calendar(state).read_text()
        self.assertIn("DTEND;VALUE=DATE:20270101", output)
        with patch.object(
            coaching.ollama, "chat", return_value=self.response({"tasks": [], "observations": []})
        ):
            state, _ = coaching.plan_day(date(2027, 1, 1), [], "")
        output = calendar.export_calendar(state).read_text()
        self.assertIn(f"UID:{task_id}@daily-rag.local", output)
        self.assertIn("DTSTART;VALUE=DATE:20270101", output)
        self.assertIn("SEQUENCE:1", output)

    def test_empty_index_needs_no_embedding_service(self):
        with patch.object(store, "embed") as embed:
            self.assertEqual(store.search("question"), [])
            embed.assert_not_called()

    def test_roadmap_queue_preserves_order_skips_checked_and_parking_lot(self):
        roadmap = self.document.model_copy(update={"text": (
            "# Roadmap\n"
            "| 01 | [x] **ABI** Completed setup | [ ] **ENG** Diagram request lifecycle |\n"
            "| 02 | [ ] **CEO** Define workflow | [ ] **ENG** Write networking notes |\n"
            "## Parking lot (not MVP commitments)\n"
            "- [ ] Add ranked-choice voting\n"
        )})
        queue = coaching.roadmap_queue([roadmap], tasks.State())
        self.assertEqual([item.title for item in queue], [
            "ENG Diagram request lifecycle", "CEO Define workflow", "ENG Write networking notes"
        ])
        self.assertEqual(queue[0].category, "learning")
        self.assertEqual(queue[1].category, "build")

    def test_roadmap_tasks_do_not_depend_on_model_guessing_priorities(self):
        roadmap = self.document.model_copy(update={"text": (
            "| 01 | [ ] **ABI** Write MVP scope | [ ] **ENG** Diagram request lifecycle |\n"
            "| 02 | [ ] **CEO** Define workflow | [ ] **ENG** Write networking notes |"
        )})
        with patch.object(
            coaching.ollama, "chat",
            return_value=self.response({"tasks": [], "observations": []}),
        ) as model:
            state, plan = coaching.plan_day(self.today, [roadmap], "")
        self.assertEqual([state.tasks[key].title for key in plan.task_ids], [
            "ABI Write MVP scope", "ENG Diagram request lifecycle"
        ])
        model.assert_not_called()
        self.assertIn("not enough recorded outcome evidence", plan.observations[0].finding)
        first_id = plan.task_ids[0]
        tasks.record_feedback(first_id, "done", "scope.md")
        with patch.object(
            coaching.ollama, "chat",
            return_value=self.response({"tasks": [], "observations": []}),
        ) as next_model:
            following, next_plan = coaching.plan_day(self.today + timedelta(days=1), [roadmap], "")
        next_model.assert_not_called()
        self.assertIn("scope.md", next_plan.observations[0].finding)
        titles = [task.title for task in following.tasks.values()]
        self.assertEqual(titles.count("ABI Write MVP scope"), 1)
        self.assertIn("CEO Define workflow", titles)

    def test_answer_includes_full_personal_context_and_feedback(self):
        (self.personal_dir / "roadmap.md").write_text("One build and one learning task.")
        _, plan = self.create_plan()
        tasks.record_feedback(plan.task_ids[0], "done", "Published scope.md")
        with patch.object(generate, "search", return_value=[]), patch.object(
            generate.ollama, "chat", return_value={"message": {"content": "Review"}}
        ) as model:
            self.assertEqual(generate.answer("weak spots", "Review progress"), "Review")
        user = model.call_args.kwargs["messages"][1]["content"]
        self.assertIn("One build and one learning task.", user)
        self.assertIn("Published scope.md", user)
        self.assertIn("not proof of a skill deficit", model.call_args.kwargs["messages"][0]["content"])

    def test_daily_integration_refreshes_local_without_web_and_uses_current_checkin(self):
        (self.personal_dir / "roadmap.md").write_text("Two tasks a day.")
        source = personal.refresh()[0]
        key = f"{source.source}@{source.fingerprint[:12]}:L1"
        suggestion = dict(self.suggestion, evidence=[key])
        proposal = {"observations": [], "tasks": [suggestion]}
        with patch("sys.argv", ["daily", "--no-ingest"]), patch(
            "sys.stdin.isatty", return_value=True
        ), patch("builtins.input", side_effect=["Shipped scope", "Blocked on review"]), patch(
            "sys.stdout", new_callable=io.StringIO
        ), patch.object(daily, "ingest") as ingest, patch.object(
            coaching.ollama, "chat", return_value=self.response(proposal)
        ) as model, patch.object(daily, "answer", return_value="No web news."):
            daily.main()
        ingest.assert_not_called()
        self.assertIn("Blocked on review", model.call_args.kwargs["messages"][1]["content"])
        state = tasks.load_state()
        self.assertEqual(len(state.tasks), 1)
        self.assertTrue(Path(config.OUTPUT_DIR, "tasks.ics").exists())
        digest = Path(config.OUTPUT_DIR, f"{date.today()}.md").read_text()
        self.assertIn("No web news.", digest)
        self.assertIn("Write MVP scope", digest)
        self.assertIn("Done when:", digest)


if __name__ == "__main__":
    unittest.main()

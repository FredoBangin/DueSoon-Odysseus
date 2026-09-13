"""Deterministic, evidence-linked dashboard answers."""

from __future__ import annotations

from datetime import UTC, datetime
import re


class DeterministicAssistant:
    def answer(self, question: str, snapshot: dict[str, object]) -> dict[str, object]:
        text = re.sub(r"\s+", " ", question.strip().lower()).rstrip("?.!")
        counts = snapshot.get("counts", {})
        incomplete = int(counts.get("active", len(snapshot["upcoming"])))
        undated = int(counts.get("undated_active", len(snapshot.get("needs_information", []))))
        matches = lambda pattern: re.fullmatch(pattern, text) is not None
        if matches(r"(what (am i|work is|is) missing|what is overdue|(show|list)( me)? (my )?(missing|overdue) work|(do i have|any) (missing|overdue) work)"):
            intent = "missing_work"
            items = list({item["id"]: item for item in [*snapshot["missing"], *snapshot["overdue"]]}.values())
            answer = "You have no missing work." if not items else f"You have {len(items)} missing or overdue item(s)."
        elif matches(r"((did|have) i (submit|finish|complete|finished|submitted|completed) (everything|all( my)? work)|is (everything|all( my)? work) (done|submitted|complete))"):
            intent, items = "completion_check", snapshot["upcoming"] or snapshot.get("needs_information", [])
            answer = (
                "Canvas currently shows no active assignments awaiting completion."
                if not incomplete else
                f"Not everything is confirmed complete. Canvas has {incomplete} active assignment(s) not confirmed submitted or graded."
            )
            if undated:
                answer += f" {undated} lack resolved deadlines, so absence from Urgent is not proof they are done."
        elif matches(r"(what (should|do) i (work on|start|focus on)( next| today| first)?|what should i do next)"):
            intent = "work_next"
            items = [item for item in snapshot["upcoming"] if item.get("work_priority", {}).get("state") in {"NOW", "NEXT", "LATER"}]
            if items:
                answer = f"Work next: {items[0]['title']} for {items[0]['course_name']}."
                reason = items[0]["work_priority"].get("state_reason")
                if reason:
                    answer += f" {reason}"
            elif incomplete:
                items = snapshot.get("next_due", [])[:1]
                answer = "I cannot rank work confidently yet: deadline or effort information is missing."
                if items:
                    answer += f" The next known deadline is for {items[0]['title']}; that does not prove it should be started first."
            else:
                answer = "No active work was found."
        elif matches(r"(what (is )?due( next)?|what('s| is) due next|what is the next deadline|what assignment is due next)"):
            intent, items = "due_next", snapshot.get("next_due", snapshot["upcoming"])
            answer = "No upcoming dated work was found." if not items else f"Next: {items[0]['title']} for {items[0]['course_name']}."
            if undated:
                answer += f" {undated} active assignment(s) still need resolved deadlines."
        elif matches(r"(any updates( on school stuff)?|what('s| is) going on( with school)?|what do i need to know today|status( update)?|give me (an )?update)"):
            intent, items = "status_update", snapshot["urgent"] or snapshot["upcoming"]
            urgent = int(counts.get("urgent", len(snapshot["urgent"])))
            answer = f"Canvas shows {incomplete} active and {int(counts.get('completed', 0))} completed assignment(s); {urgent} meet urgent criteria."
            if undated:
                answer += f" {undated} active assignment(s) lack resolved deadlines and need evidence review."
        else:
            return {"mode": "deterministic", "intent": "unsupported",
                    "answer": "Model-backed interpretation is unavailable for this answer. Exact Canvas deadline, completion, and workload checks still work; I will not guess about unprocessed course evidence.",
                    "confidence": "unknown", "evidence": [], "generated_at": datetime.now(UTC).isoformat(),
                    "data_freshness": snapshot["freshness"]["canvas_status"]}
        evidence = [{"label": item["title"], "href": item["external_url"] or f"/app/calendar?assignment={item['id']}"}
                    for item in list(items)[:10]]
        return {"mode": "deterministic", "intent": intent, "answer": answer,
                "confidence": "high" if snapshot["freshness"]["canvas_status"] == "fresh" else "likely", "evidence": evidence, "generated_at": datetime.now(UTC).isoformat(),
                "data_freshness": snapshot["freshness"]["canvas_status"]}

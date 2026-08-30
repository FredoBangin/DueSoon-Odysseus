"""Deterministic, evidence-linked dashboard answers."""

from __future__ import annotations

from datetime import UTC, datetime
import re


class DeterministicAssistant:
    def answer(self, question: str, snapshot: dict[str, object]) -> dict[str, object]:
        text = re.sub(r"\s+", " ", question.strip().lower())
        if any(word in text for word in ("missing", "overdue")):
            intent, items = "missing_work", snapshot["missing"] or snapshot["overdue"]
            answer = "You have no missing work." if not items else f"You have {len(items)} missing or overdue item(s)."
        elif any(word in text for word in ("submit", "complete", "everything")):
            intent, items = "completion_check", snapshot["missing"] or snapshot["overdue"]
            answer = "Canvas shows no incomplete overdue work." if not items else f"Not yet—{len(items)} item(s) still need attention."
        elif any(phrase in text for phrase in ("work on", "start next", "focus on")):
            intent, items = "work_next", snapshot["upcoming"]
            answer = "No active work was found." if not items else f"Work next: {items[0]['title']} for {items[0]['course_name']}."
        elif any(word in text for word in ("next", "due")):
            intent, items = "due_next", snapshot.get("next_due", snapshot["upcoming"])
            answer = "No upcoming dated work was found." if not items else f"Next: {items[0]['title']} for {items[0]['course_name']}."
        elif any(word in text for word in ("update", "going on", "status")):
            intent, items = "status_update", snapshot["urgent"] or snapshot["upcoming"]
            answer = f"You have {len(snapshot['urgent'])} urgent and {len(snapshot['upcoming'])} upcoming item(s)."
        else:
            return {"mode": "deterministic", "intent": "unsupported",
                    "answer": "I can answer: Any updates? What is due next? What am I missing? Did I submit everything?",
                    "confidence": "unknown", "evidence": [], "generated_at": datetime.now(UTC).isoformat(),
                    "data_freshness": snapshot["freshness"]["canvas_status"]}
        evidence = [{"label": item["title"], "href": item["external_url"] or f"/app/calendar?assignment={item['id']}"}
                    for item in list(items)[:10]]
        return {"mode": "deterministic", "intent": intent, "answer": answer,
                "confidence": "high", "evidence": evidence, "generated_at": datetime.now(UTC).isoformat(),
                "data_freshness": snapshot["freshness"]["canvas_status"]}

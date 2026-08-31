import {post} from "../api.js";

function node(tag, text, className = "") {
  const element = document.createElement(tag);
  element.className = className;
  element.textContent = text;
  return element;
}

function learningCard(items) {
  if (!items?.length) return null;
  const card = node("article", "", "admin-card duesoon-card-wide");
  card.append(
    node("h2", "Help DueSoon learn"),
    node("p", "Tell DueSoon what completed work was actually like—time, size, difficulty, or what slowed you down. This improves planning only; it never changes deadlines or reminders.", "admin-toggle-sub"),
  );
  for (const item of items) {
    const form = node("form", "", "duesoon-learning-row");
    const copy = node("div", "", "duesoon-learning-copy");
    copy.append(node("div", `How did ${item.title} go?`, "admin-toggle-label"), node("div", item.course_name, "admin-toggle-sub"));
    const input = document.createElement("input");
    input.className = "settings-input duesoon-learning-input";
    input.type = "text";
    input.maxLength = 5000;
    input.required = true;
    input.placeholder = "Example: About 2 hours, 18 questions; the last module was hard";
    input.setAttribute("aria-label", `Completion feedback for ${item.title}`);
    const save = node("button", "Save feedback", "confirm-btn confirm-btn-primary duesoon-learning-save");
    save.type = "submit";
    const result = node("span", "", "admin-toggle-sub");
    form.append(copy, input, save, result);
    form.onsubmit = async event => {
      event.preventDefault();
      save.disabled = true;
      try {
        await post(`/api/v1/dashboard/assignments/${item.assignment_id}/planning`, {
          completion_feedback: input.value.trim(),
        });
        input.disabled = true;
        result.textContent = "Saved";
      } catch (error) {
        result.textContent = error.message;
        save.disabled = false;
      }
    };
    card.append(form);
  }
  return card;
}

function dueLabel(item) {
  if (!item.due_at) return "No resolved deadline";
  const due = new Date(item.due_at);
  if (Number.isNaN(due.getTime())) return "Deadline unavailable";
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(due);
}

function assignmentList(title, items, mode = "urgency") {
  const card = node("article", "", "admin-card");
  card.append(node("h2", title));

  if (!items.length) {
    card.append(node("p", "Nothing here right now.", "admin-toggle-sub"));
    return card;
  }

  const list = node("div", "", "duesoon-assignment-list");
  for (const item of items) {
    const row = node("div", "", "cal-event-item");
    const dot = node("span", "", "cal-event-dot");
    dot.style.background = item.course_color;

    const information = node("div", "", "cal-event-info");
    information.append(
      node("div", item.title, "cal-event-name"),
      node(
        "div",
        `${dueLabel(item)} · ${item.course_name} · ${item.submission_status.replaceAll("_", " ")}`,
        "cal-event-time",
      ),
    );

    const label = mode === "priority" ? item.work_priority.band : item.urgency.level;
    const reasons = mode === "priority" ? item.work_priority.reasons : item.urgency.reasons;
    const badge = node("span", label, "cal-event-tag");
    badge.title = (reasons || []).join(" · ");
    row.append(dot, information, badge);
    list.append(row);
  }

  card.append(list);
  return card;
}

function assistantCard(onAsk) {
  const card = node("article", "", "admin-card duesoon-card-wide");
  card.append(
    node("h2", "Ask DueSoon"),
    node(
      "p",
      "Ask anything. DueSoon answers normally, then uses connected school evidence when your question needs it.",
      "admin-toggle-sub",
    ),
  );

  const form = node("form", "", "cal-quickadd-row duesoon-ask-row");
  const icon = node("span", "", "cal-quickadd-icon");
  icon.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';

  const input = document.createElement("input");
  input.className = "cal-quickadd-input duesoon-ask-input";
  input.type = "text";
  input.placeholder = "What do I need to know today?";
  input.maxLength = 500;
  input.setAttribute("aria-label", "Ask DueSoon about school");

  const ask = node("button", "Ask", "confirm-btn confirm-btn-primary duesoon-ask-submit");
  ask.type = "submit";
  form.append(icon, input, ask);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (question) onAsk(question);
  });
  card.append(form);
  return card;
}

export function renderHome(root, data, onAsk) {
  root.replaceChildren();
  const grid = node("div", "", "duesoon-dashboard-grid");
  grid.append(
    assistantCard(onAsk),
    assignmentList("Urgent", data.urgent),
    assignmentList("Work priority", data.upcoming, "priority"),
    assignmentList("Missing or overdue", [...data.missing, ...data.overdue]),
    assignmentList("Recently completed", data.completed_recently),
  );
  const learning = learningCard(data.questions);
  if (learning) grid.append(learning);
  root.append(grid);
}

export {node};

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
    node("p", "Optional completion feedback improves future effort estimates. It never changes deadlines or reminders.", "admin-toggle-sub"),
  );
  for (const item of items) {
    const form = node("form", "", "admin-toggle-row");
    const copy = node("div", "");
    copy.append(node("div", item.prompt, "admin-toggle-label"), node("div", item.course_name, "admin-toggle-sub"));
    const input = document.createElement("input");
    input.className = "settings-input";
    input.type = "number";
    input.min = "5";
    input.max = "10080";
    input.required = true;
    input.placeholder = "Minutes";
    input.setAttribute("aria-label", `Minutes spent on ${item.title}`);
    const save = node("button", "Save", "confirm-btn confirm-btn-primary");
    save.type = "submit";
    const result = node("span", "", "admin-toggle-sub");
    form.append(copy, input, save, result);
    form.onsubmit = async event => {
      event.preventDefault();
      save.disabled = true;
      try {
        await post(`/api/v1/dashboard/assignments/${item.assignment_id}/planning`, {
          estimated_minutes: Number(input.value),
          note: "Owner completion effort estimate",
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
      "Ask about deadlines, missing work, workload, reminders, or what changed.",
      "admin-toggle-sub",
    ),
  );

  const form = node("form", "", "cal-quickadd-row duesoon-ask-row");
  const icon = node("span", "", "cal-quickadd-icon");
  icon.innerHTML = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';

  const input = document.createElement("input");
  input.className = "cal-quickadd-input";
  input.type = "text";
  input.placeholder = " ";
  input.maxLength = 500;
  input.setAttribute("aria-label", "Ask DueSoon about school");

  const hint = node("span", "", "cal-quickadd-hint");
  hint.setAttribute("aria-hidden", "true");
  hint.innerHTML = '<span class="qa-hint-accent">Ask DueSoon</span> — any updates on school stuff? <svg class="qa-hint-enter" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="9 10 4 15 9 20"/><path d="M20 4v7a4 4 0 0 1-4 4H4"/></svg>';

  form.append(icon, input, hint);
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

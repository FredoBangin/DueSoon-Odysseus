import assert from "node:assert/strict";

// Minimal DOM ownership model: exercise real view modules without a browser,
// network, user credentials, or a new frontend dependency.
class Element {
  constructor(tag) {
    this.tagName = tag;
    this.children = [];
    this.style = {};
    this.attributes = {};
    this.listeners = {};
    this.className = "";
    this.textContent = "";
    this.classList = {
      add: value => { this.className += ` ${value}`; },
    };
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = items; }
  setAttribute(key, value) { this.attributes[key] = value; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  querySelectorAll(selector) {
    const matches = element => selector.startsWith(".")
      ? element.className.split(" ").includes(selector.slice(1))
      : element.tagName === selector;
    return this.children.flatMap(child => [
      ...(matches(child) ? [child] : []), ...child.querySelectorAll(selector),
    ]);
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  set innerHTML(value) {
    this.children = [];
    if (value.includes('class="body"')) {
      const role = new Element("div"); role.className = "role";
      const body = new Element("div"); body.className = "body";
      this.append(role, body);
    }
  }
}

globalThis.document = {createElement: tag => new Element(tag)};
const requests = [];
globalThis.fetch = async (path, options) => {
  requests.push({path, payload: JSON.parse(options.body)});
  return {
    ok: true, status: 200,
    json: async () => ({answer: "Recorded facts only.", mode: "deterministic", confidence: "high", evidence: []}),
  };
};

const {renderHome} = await import("../../../src/duesoon/web/static/js/views/home.js");
const {renderAssistant} = await import("../../../src/duesoon/web/static/js/views/assistant.js");
const root = new Element("section");
const assignment = {
  id: 1, title: "Lab", course_name: "Course", course_color: "blue",
  due_at: "2026-09-14T12:00:00Z", submission_status: "not_submitted",
  urgency: {level: "LOW", reasons: []},
  work_priority: {band: "MONITOR", display_label: "Needs effort estimate", state_reason: "Effort is unknown", reasons: []},
};
renderHome(root, {
  urgent: [], upcoming: [assignment], next_due: [assignment], missing: [], overdue: [],
  completed_recently: [{...assignment, id: 2, submission_status: "submitted"}],
  needs_information: [{...assignment, id: 3, due_at: null}],
  counts: {undated_active: 12}, questions: [], assistant_status: {availability: "disabled"},
}, () => {});
assert.equal(root.querySelectorAll(".duesoon-calendar-complete").length, 1);
assert(root.querySelectorAll(".cal-event-tag").some(item => item.textContent === "Needs effort estimate"));
assert(root.querySelectorAll("p").some(item => item.textContent.includes("No work currently meets urgent criteria")));
assert(root.querySelectorAll("h2").some(item => item.textContent === "Needs deadline evidence (12)"));
assert(root.querySelectorAll("p").some(item => item.textContent.includes("AI interpretation is offline")));

renderAssistant(root, "", {availability: "disabled"});
const form = root.querySelector("form");
assert(form, "Assistant route must have a working composer");
const input = form.querySelector("input");
const button = form.querySelector("button");
input.value = "18 questions, 3 modules, pointers were hard; what should I tackle next?";
const submit = form.listeners.submit({preventDefault() {}});
assert.equal(button.disabled, true);
await form.listeners.submit({preventDefault() {}});
await submit;
assert.equal(requests.length, 1, "Pending submissions must not produce duplicate model requests");
assert.equal(requests[0].path, "/api/v1/dashboard/assistant");
assert.equal(requests[0].payload.question, "18 questions, 3 modules, pointers were hard; what should I tackle next?");
assert.equal(input.value, "");
assert.equal(button.disabled, false);
input.value = "Explain recursion, then help me connect it to this lab.";
await form.listeners.submit({preventDefault() {}});
assert.equal(requests.length, 2, "Composer must support follow-up messages");
console.log("DueSoon frontend runtime: passed");

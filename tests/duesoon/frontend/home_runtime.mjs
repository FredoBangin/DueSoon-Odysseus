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
const {providerHealthText} = await import("../../../src/duesoon/web/static/js/views/foundations.js");
assert(providerHealthText({provider_health:{state:"unconfigured"}}).includes("credentials"));
assert(providerHealthText({provider_health:{state:"healthy"}}).includes("does not prove remaining quota"));
assert(providerHealthText({provider_health:{state:"cooldown",reason:"quota_exhausted",retry_after_seconds:120}}).includes("2 minute(s)"));
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

await renderAssistant(root, "", {availability: "disabled"});
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
const {renderNotificationHistory} = await import("../../../src/duesoon/web/static/js/views/notifications.js");
const notification = {
  kind: "daily_digest", title: "DueSoon daily briefing", status: "sent", provider: "ntfy",
  attempted_at: "2026-09-23T12:04:00Z", completed_at: "2026-09-23T12:05:00Z",
  body: "Due This Week\nSample Course — Sample lab — Sun, Sep 27 at 11:59 PM EDT\n\nDue Later\nAnother Course — <img src=x onerror=alert(1)> — Mon, Sep 28 at 11:59 PM EDT",
};
renderNotificationHistory(root, {timezone:"America/New_York", items:[notification]});
assert.equal(root.querySelectorAll(".duesoon-notification-entry").length, 2);
assert.deepEqual(root.querySelectorAll("h3").map(item => item.textContent), ["Due This Week", "Due Later"]);
assert(root.querySelectorAll("p").some(item => item.textContent.includes("Sep 23, 2026") && item.textContent.includes("8:05 AM EDT")));
assert(root.querySelectorAll(".duesoon-notification-entry").some(item => item.textContent.includes("<img src=x onerror=alert(1)>")));
assert.equal(root.querySelectorAll("img").length, 0, "Source titles must remain escaped text");
renderNotificationHistory(root, {timezone:"America/New_York", items:[{...notification, provider:"discord",
  body:"Here's your school update.\n\nDue Today\nSample lab — Mon, Sep 28 at 1:00 PM EDT\n\nRecently completed\nPractice — completed in Canvas\n\nCourse updates\n1 new Canvas announcement recorded.\n\nUpdate window: Monday, September 28 at 8:00 AM EDT.",
}]});
assert(root.querySelectorAll("p").some(item => item.textContent === "Here's your school update."), "Discord summary introduction must remain visible");
assert.deepEqual(root.querySelectorAll("h3").map(item => item.textContent), ["Due Today", "Recently completed", "Course updates"]);
assert(root.querySelectorAll("p").some(item => item.textContent.startsWith("Update window:")));
const oldBody = "TEST101-2026-99 | Sample Course: Old lab · due Mon 11:59 PM\nAnother Course: Second lab · due Sun 11:59 PM";
renderNotificationHistory(root, {timezone:"America/New_York", items:[{...notification, body:oldBody}]});
assert.equal(root.querySelectorAll(".duesoon-notification-entry").length, 2);
assert.equal(root.querySelectorAll(".duesoon-notification-entry")[0].children[0].textContent, "Sample Course — Old lab — Date unknown — check Canvas");
assert.equal(root.querySelectorAll(".duesoon-notification-entry")[1].children[0].textContent, "Another Course — Second lab — Date unknown — check Canvas");
assert.equal(root.querySelectorAll(".duesoon-notification-entry").some(item => item.textContent.includes("due Mon")), false);
renderNotificationHistory(root, {timezone:"America/New_York", items:[{...notification, body:"1. Sample lab\nSample Course\nDue Sun, Sep 27, 2026 at 11:59 PM EDT"}]});
assert.equal(root.querySelectorAll(".duesoon-notification-entry").length, 1, "A single new-format assignment must stay grouped");
renderNotificationHistory(root, {timezone:"America/New_York", items:[{...notification, kind:"deadline_checkpoint", body:"Sample lab\nDue in 1h"}]});
assert(root.querySelectorAll("p").some(item => item.textContent === "Sample lab\nDue in 1h"));
console.log("DueSoon frontend runtime: passed");

// A Discord link opens pinned context but never submits/answers automatically.
requests.length=0;
globalThis.fetch=async(path,options={})=>{
  requests.push({path,payload:options.body?JSON.parse(options.body):null});
  return {ok:true,status:200,json:async()=>options.body
    ?{answer:"Saved owner context only.",mode:"deterministic",evidence:[]}
    :{id:7,title:"School changes",body:"Course updates\nActual announcement excerpt",question:null}};
};
await renderAssistant(root,"",{availability:"disabled"},7);
assert.equal(requests.length,1);
assert.equal(requests[0].path,"/api/v1/dashboard/academic-updates/7");
const linkedForm=root.querySelector("form");
linkedForm.querySelector("input").value="Professor said this is practice. It had 18 questions.";
await linkedForm.listeners.submit({preventDefault(){}});
assert.equal(requests[1].payload.update_id,7);
assert(requests[1].payload.question.includes("18 questions"));

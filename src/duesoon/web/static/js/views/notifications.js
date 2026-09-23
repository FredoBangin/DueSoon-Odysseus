import {get} from "../api.js";
import {node} from "./home.js";

function deliveryLabel(item, timezone) {
  const status = {sent: "Sent", failed: "Failed", dry_run: "Preview", pending: "Pending", retry_scheduled: "Retry scheduled", outcome_unknown: "Delivery unconfirmed"}[item.status] || String(item.status).replaceAll("_", " ");
  const date = new Date(item.completed_at || item.attempted_at || "");
  if (Number.isNaN(date.getTime())) return `${status} · Date unavailable · ${item.provider}`;
  const formatted = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone, month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", timeZoneName: "short",
  }).format(date);
  return `${status} · ${formatted} · ${item.provider}`;
}

function notificationBody(item) {
  const body = node("div", "", "duesoon-notification-body");
  const text = String(item.body || "").replaceAll("\r\n", "\n");
  if (item.kind !== "daily_digest") {
    body.append(node("p", text));
    return body;
  }
  // Old deliveries have one assignment per line. Do not guess their missing dates
  // or rewrite the immutable delivery body while making their display readable.
  const blocks = text.includes("\n\n") ? text.split(/\n\s*\n/) : /^1\. /u.test(text) ? [text] : text.split("\n");
  let legacyDates = false;
  for (const block of blocks.filter(value => value.trim())) {
    const row = node("div", "", "duesoon-notification-entry");
    const lines = block.split("\n");
    if (/^\d+\. /u.test(lines[0]) && lines.length === 3) {
      row.append(node("strong", lines[0].replace(/^\d+\. /u, "")), node("div", lines[1], "admin-toggle-sub"), node("div", lines[2]));
    } else {
      const old = block.match(/^(.+?): (.+) · due (.+)$/u);
      if (old) {
        legacyDates = true;
        const course = old[1].split("|").slice(1).join("|").trim() || old[1];
        row.append(node("strong", old[2]), node("div", course, "admin-toggle-sub"), node("div", `Due ${old[3]}`));
      } else row.append(node("p", block));
    }
    body.append(row);
  }
  if (legacyDates) body.append(node("p", "This older briefing did not record full due dates.", "admin-toggle-sub"));
  return body;
}

export function renderNotificationHistory(root, data) {
  root.replaceChildren();
  root.append(node("h2", "Notifications", "section-title"));
  if (!data.items.length) {
    root.append(node("p", "No notification activity yet.", "admin-toggle-sub"));
    return;
  }
  for (const item of data.items) {
    const panel = node("article", "", "admin-card duesoon-notification");
    panel.append(node("h2", item.title), node("p", deliveryLabel(item, data.timezone), "admin-toggle-sub"), notificationBody(item));
    root.append(panel);
  }
}

export async function renderNotifications(root) {
  renderNotificationHistory(root, await get("/api/v1/dashboard/notifications?limit=50"));
}

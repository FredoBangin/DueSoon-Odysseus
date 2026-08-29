function node(tag,text,className=""){const el=document.createElement(tag);el.className=className;el.textContent=text;return el}
function list(title,items){
  const panel=node("article","","admin-card");
  panel.append(node("h2",title));
  if(!items.length) panel.append(node("p","Nothing here right now.","admin-toggle-sub"));
  for(const item of items){
    const row=node("div","","list-item");
    const dot=node("span","","session-star");
    if(item.course_color) dot.style.background=item.course_color;
    const main=node("span","","grow");
    main.append(node("strong",item.title),node("small",`${item.course_name} · ${item.submission_status}`,"admin-toggle-sub"));
    const urgency=node("span",item.urgency.level,"cal-event-tag");
    row.append(dot,main,urgency);
    panel.append(row);
  }
  return panel;
}
export function renderHome(root,data){
  root.replaceChildren();
  root.append(
    node("p","Academic briefing","section-title"),
    list("Urgent",data.urgent),
    list("Upcoming",data.upcoming),
    list("Missing or overdue",[...data.missing,...data.overdue]),
    list("Recently completed",data.completed_recently),
  );
}
export {node};

import {get,post} from "../api.js";
import {node} from "./home.js";

const VIEWS=["month","week","agenda"];
const COMPLETE_STATES=new Set(["submitted","graded"]);
const iso=date=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
const addDays=(value,count)=>new Date(value.getFullYear(),value.getMonth(),value.getDate()+count);
const isComplete=event=>event.source==="canvas"&&COMPLETE_STATES.has(event.status);
function markCompletion(element,event){
  if(isComplete(event)) element.classList.add("duesoon-calendar-complete");
  element.setAttribute("aria-label",`${event.title}, ${event.status}`);
}
function range(view,anchor){
  if(view==="month") return {start:new Date(anchor.getFullYear(),anchor.getMonth(),1),end:new Date(anchor.getFullYear(),anchor.getMonth()+1,0)};
  if(view==="week"){const start=addDays(anchor,-anchor.getDay());return {start,end:addDays(start,6)};}
  return {start:anchor,end:addDays(anchor,30)};
}

async function planningEditor(body,event){
  if(event.source!=="canvas"||!event.assignment_id)return;
  const endpoint=`/api/v1/dashboard/assignments/${event.assignment_id}/planning`;
  try{
    const planning=await get(endpoint);
    body.append(node("h5","Work planning","settings-section-heading"));
    const summary=node("p",`${planning.priority.band} · ${planning.priority.score}/100 priority · ${planning.effort.confidence} confidence`,"admin-toggle-sub");
    body.append(summary);
    const form=node("form","","admin-card");
    const effortLabel=node("label","Estimated minutes","settings-label");
    const effort=document.createElement("input"); effort.className="settings-input"; effort.type="number"; effort.min="5"; effort.max="10080"; effort.value=planning.effort.estimated_minutes??"";
    const progressLabel=node("label","Percent complete","settings-label");
    const progress=document.createElement("input"); progress.className="settings-input"; progress.type="number"; progress.min="0"; progress.max="100"; progress.value=planning.progress_percent??0;
    const save=node("button","Save work estimate","confirm-btn confirm-btn-primary"); save.type="submit";
    const status=node("p","Corrections affect work priority only—not deadlines or reminders.","admin-toggle-sub");
    form.append(effortLabel,effort,progressLabel,progress,save,status);
    form.onsubmit=async submitEvent=>{
      submitEvent.preventDefault(); save.disabled=true;
      const payload={percent_complete:Number(progress.value)};
      if(effort.value)payload.estimated_minutes=Number(effort.value);
      try{
        const updated=await post(endpoint,payload);
        summary.textContent=`${updated.priority.band} · ${updated.priority.score}/100 priority · ${updated.effort.confidence} confidence`;
        status.textContent="Saved. History remains reviewable.";
      }catch(error){status.textContent=error.message;}finally{save.disabled=false;}
    };
    body.append(form);
  }catch(error){body.append(node("p",`Work planning unavailable: ${error.message}`,"admin-toggle-sub"));}
}

async function openDetail(event){
  document.querySelector("#duesoon-calendar-detail")?.remove();
  const modal=node("div","","modal");
  modal.id="duesoon-calendar-detail";
  const content=node("section","","modal-content cal-modal-content");
  markCompletion(content,event);
  content.setAttribute("role","dialog");
  content.setAttribute("aria-label","Assignment details");
  const header=node("div","","modal-header");
  header.append(node("h4",event.title));
  const close=node("button","×","close-btn");
  close.type="button";
  close.setAttribute("aria-label","Close assignment details");
  close.onclick=()=>modal.remove();
  header.append(close);
  const body=node("div","","modal-body");
  body.append(node("p",event.course_name,"cal-event-tag"),node("p",`${event.local_date} at ${event.local_time}`,"cal-event-time"),node("p",`${event.status} · ${event.urgency_level} urgency`,"admin-toggle-sub"));
  if(event.external_url){
    const link=node("a","Open in Canvas","theme-io-btn");
    link.href=event.external_url; link.target="_blank"; link.rel="noopener noreferrer"; body.append(link);
  }
  content.append(header,body); modal.append(content); document.body.append(modal);
  await planningEditor(body,event);
}

function eventRow(event){
  const row=node("button","","cal-event-row");
  row.type="button";
  markCompletion(row,event);
  const dot=node("span","","cal-event-row-dot");
  dot.style.background=event.color||"var(--accent, var(--red))";
  row.append(dot,node("span",event.local_time||"","cal-event-row-time"),node("span",event.title,"cal-event-row-name"));
  row.title=`${event.course_name} · ${event.status}`;
  row.onclick=()=>openDetail(event);
  return row;
}

function drawMonth(grid,anchor,events){
  const headers=node("div","","cal-week-headers");
  ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"].forEach(label=>headers.append(node("div",label,"cal-weekday")));
  grid.append(headers);
  const first=new Date(anchor.getFullYear(),anchor.getMonth(),1);
  const daysInMonth=new Date(anchor.getFullYear(),anchor.getMonth()+1,0).getDate();
  const rows=Math.ceil((first.getDay()+daysInMonth)/7);
  for(let rowIndex=0;rowIndex<rows;rowIndex++){
    const week=node("div","","cal-week-row");
    for(let col=0;col<7;col++){
      const dayIndex=rowIndex*7+col-first.getDay()+1;
      const cell=node("div","","cal-day");
      const current=new Date(anchor.getFullYear(),anchor.getMonth(),dayIndex);
      if(dayIndex<1||dayIndex>daysInMonth) cell.classList.add("cal-other");
      if(iso(current)===iso(new Date())) cell.classList.add("cal-today");
      cell.append(node("span",String(current.getDate()),"cal-day-num"));
      events.filter(event=>event.local_date===iso(current)).forEach(event=>cell.append(eventRow(event)));
      week.append(cell);
    }
    grid.append(week);
  }
}

function drawWeek(grid,dates,events){
  const headers=node("div","","cal-week-headers");
  for(let i=0;i<7;i++){const current=addDays(dates.start,i);headers.append(node("div",current.toLocaleDateString(undefined,{weekday:"short",month:"short",day:"numeric"}),"cal-weekday"));}
  grid.append(headers);
  const week=node("div","","cal-week-row");
  for(let i=0;i<7;i++){
    const current=addDays(dates.start,i);const cell=node("div","","cal-day");
    if(iso(current)===iso(new Date())) cell.classList.add("cal-today");
    cell.append(node("span",String(current.getDate()),"cal-day-num"));
    events.filter(event=>event.local_date===iso(current)).forEach(event=>cell.append(eventRow(event)));
    week.append(cell);
  }
  grid.append(week);
}

function drawAgenda(root,dates,events){
  const agenda=node("div","","cal-agenda");
  for(let current=new Date(dates.start);current<=dates.end;current=addDays(current,1)){
    const dayEvents=events.filter(event=>event.local_date===iso(current));
    if(!dayEvents.length) continue;
    const day=node("section","","cal-agenda-day");
    day.append(node("h3",current.toLocaleDateString(undefined,{weekday:"long",month:"long",day:"numeric"}),"cal-agenda-date"));
    dayEvents.forEach(event=>{
      const row=node("button","","cal-agenda-event"); row.type="button"; row.onclick=()=>openDetail(event);
      markCompletion(row,event);
      const dot=node("span","","cal-event-dot"); dot.style.background=event.color||"var(--accent, var(--red))";
      const info=node("span","","cal-event-info"); info.append(node("strong",event.title,"cal-event-name"),node("span",`${event.local_time} · ${event.course_name}`,"cal-event-time"));
      row.append(dot,info); day.append(row);
    });
    agenda.append(day);
  }
  if(!agenda.children.length) agenda.append(node("p","No deadlines in this range.","cal-agenda-empty"));
  root.append(agenda);
}

export async function renderCalendar(root,initial="month"){
  let view=VIEWS.includes(initial)?initial:"month"; let anchor=new Date();
  async function draw(){
    root.replaceChildren();
    const toolbar=node("div","","cal-toolbar");
    const nav=node("div","","cal-toolbar-nav");
    for(const label of ["Previous","Today","Next"]){
      const button=node("button",label,"cal-nav");
      if(label==="Today") button.classList.add("cal-today-btn");
      button.onclick=()=>{if(label==="Today")anchor=new Date();else if(view==="month")anchor=new Date(anchor.getFullYear(),anchor.getMonth()+(label==="Next"?1:-1),1);else anchor=addDays(anchor,(label==="Next"?1:-1)*(view==="week"?7:31));draw();};
      nav.append(button);
    }
    toolbar.append(nav);
    const toggle=node("div","","cal-view-toggle");
    for(const mode of VIEWS){const button=node("button",mode[0].toUpperCase()+mode.slice(1),"cal-view-btn");if(mode===view)button.classList.add("active");button.onclick=()=>{view=mode;draw();};toggle.append(button);}
    toolbar.append(toggle);
    const dates=range(view,anchor);
    toolbar.append(node("span",view==="month"?anchor.toLocaleDateString(undefined,{month:"long",year:"numeric"}):`${iso(dates.start)} – ${iso(dates.end)}`,"cal-title"));
    root.append(toolbar);
    const data=await get(`/api/v1/dashboard/calendar?start=${iso(dates.start)}&end=${iso(dates.end)}`);
    if(view==="agenda"){drawAgenda(root,dates,data.events);return;}
    const grid=node("div","","cal-grid");
    if(view==="month") drawMonth(grid,anchor,data.events); else drawWeek(grid,dates,data.events);
    root.append(grid);
  }
  await draw();
}

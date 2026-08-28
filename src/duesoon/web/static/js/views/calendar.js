import {get} from "../api.js";
import {node} from "./home.js";

const VIEWS=["month","week","agenda"];
const iso=date=>{
  const year=date.getFullYear();
  const month=String(date.getMonth()+1).padStart(2,"0");
  const day=String(date.getDate()).padStart(2,"0");
  return `${year}-${month}-${day}`;
};
const addDays=(value,count)=>new Date(value.getFullYear(),value.getMonth(),value.getDate()+count);

function range(view,anchor){
  if(view==="month") return {
    start:new Date(anchor.getFullYear(),anchor.getMonth(),1),
    end:new Date(anchor.getFullYear(),anchor.getMonth()+1,0),
  };
  if(view==="week"){
    const start=addDays(anchor,-anchor.getDay());
    return {start,end:addDays(start,6)};
  }
  return {start:anchor,end:addDays(anchor,30)};
}

function openDetail(event){
  document.querySelector(".detail-drawer")?.remove();
  const drawer=node("aside","","detail-drawer");
  drawer.setAttribute("aria-label","Assignment details");
  const close=node("button","Close","secondary drawer-close");
  close.onclick=()=>drawer.remove();
  drawer.append(close,node("p",event.course_name,"eyebrow"),node("h2",event.title));
  drawer.append(node("p",`${event.local_date} at ${event.local_time}`));
  drawer.append(node("p",`${event.status} · ${event.urgency_level} urgency`,"muted"));
  if(event.external_url){
    const link=node("a","Open in Canvas");
    link.href=event.external_url;
    link.target="_blank";
    link.rel="noopener noreferrer";
    drawer.append(link);
  }
  document.body.append(drawer);
}

export async function renderCalendar(root,initial="month"){
  let view=VIEWS.includes(initial)?initial:"month";
  let anchor=new Date();

  async function draw(){
    root.replaceChildren();
    const bar=node("div","","toolbar");
    for(const label of ["Previous","Today","Next"]){
      const button=node("button",label,"secondary");
      button.onclick=()=>{
        if(label==="Today") anchor=new Date();
        else if(view==="month") anchor=new Date(anchor.getFullYear(),anchor.getMonth()+(label==="Next"?1:-1),1);
        else anchor=addDays(anchor,(label==="Next"?1:-1)*(view==="week"?7:31));
        draw();
      };
      bar.append(button);
    }
    for(const mode of VIEWS){
      const button=node("button",mode[0].toUpperCase()+mode.slice(1),mode===view?"":"secondary");
      button.onclick=()=>{view=mode;draw();};
      bar.append(button);
    }
    const dates=range(view,anchor);
    const heading=node("span",view==="month"?anchor.toLocaleDateString(undefined,{month:"long",year:"numeric"}):`${iso(dates.start)} – ${iso(dates.end)}`,"calendar-heading");
    bar.append(heading);
    root.append(bar);

    const data=await get(`/api/v1/dashboard/calendar?start=${iso(dates.start)}&end=${iso(dates.end)}`);
    if(view==="agenda"){
      if(!data.events.length) root.append(node("p","No deadlines in this range.","empty"));
      for(const event of data.events){
        const row=node("article","","panel agenda-row");
        row.append(node("strong",event.title),node("p",`${event.local_date} ${event.local_time} · ${event.course_name}`,"muted"));
        row.onclick=()=>openDetail(event);
        root.append(row);
      }
      return;
    }

    const grid=node("div","","calendar-grid");
    const count=view==="week"?7:dates.end.getDate();
    if(view==="month"){
      for(let blank=0;blank<dates.start.getDay();blank++) grid.append(node("div","","day muted"));
    }
    for(let index=0;index<count;index++){
      const current=view==="week"?addDays(dates.start,index):new Date(anchor.getFullYear(),anchor.getMonth(),index+1);
      const cell=node("div","","day");
      cell.append(node("strong",current.toLocaleDateString(undefined,{weekday:"short",day:"numeric"})));
      for(const event of data.events.filter(item=>item.local_date===iso(current))){
        const item=node("button",event.title,"event");
        item.style.setProperty("--event",event.color);
        item.title=`${event.course_name} · ${event.status} · ${event.local_time}`;
        item.onclick=()=>openDetail(event);
        cell.append(item);
      }
      grid.append(cell);
    }
    root.append(grid);
  }
  await draw();
}

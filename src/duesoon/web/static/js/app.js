import {bootstrapSession,get,post} from "./api.js";
import {renderHome} from "./views/home.js";
import {renderAssistant} from "./views/assistant.js";
import {renderCalendar} from "./views/calendar.js";
import {renderNotifications} from "./views/notifications.js";
import {renderDocuments,renderEmail,renderMemory,renderNotes,renderReview,renderSettings} from "./views/foundations.js";

const root=document.querySelector("#content");
const title=document.querySelector("#page-title");

function closeSidebar(){
  window.closeDueSoonSidebar?.();
}

async function show(view,question=""){
  document.querySelectorAll("[data-view]").forEach(button=>
    button.classList.toggle("active",button.dataset.view===view));
  title.textContent=view[0].toUpperCase()+view.slice(1);
  history.replaceState({},"",`/app/${view}`);
  closeSidebar();
  try{
    if(view==="home"){
      const briefing=await get("/api/v1/dashboard/briefing");
      renderHome(root,briefing,value=>show("assistant",value));
    }else if(view==="assistant") renderAssistant(root,question);
    else if(view==="calendar") await renderCalendar(root);
    else if(view==="email") await renderEmail(root);
    else if(view==="notifications") await renderNotifications(root);
    else if(view==="review") await renderReview(root);
    else if(view==="notes") await renderNotes(root);
    else if(view==="memory") await renderMemory(root);
    else if(view==="documents") await renderDocuments(root);
    else if(view==="settings") await renderSettings(root);
    else show("home");
  }catch(error){ root.textContent=`Unable to load this view: ${error.message}`; }
}

await bootstrapSession();
document.querySelectorAll("[data-view]").forEach(button=>
  button.addEventListener("click",()=>show(button.dataset.view)));
document.querySelectorAll('[data-view][role="button"]').forEach(button=>
  button.addEventListener("keydown",event=>{
    if(event.key==="Enter"||event.key===" "){event.preventDefault();button.click();}
  }));
document.querySelector("#logout").addEventListener("click",async()=>{
  await post("/api/v1/auth/logout",{});
  location.replace("/login");
});
window.addEventListener("popstate",()=>show(location.pathname.split("/")[2]||"home"));
show(location.pathname.split("/")[2]||"home");

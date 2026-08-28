import {bootstrapSession,get,post} from "./api.js";
import {renderHome} from "./views/home.js";
import {renderAssistant} from "./views/assistant.js";
import {renderCalendar} from "./views/calendar.js";
import {renderNotifications} from "./views/notifications.js";
import {renderDeferred,renderReview,renderSettings} from "./views/foundations.js";

const root=document.querySelector("#content");
const title=document.querySelector("#page-title");
const fresh=document.querySelector("#freshness");
const sidebarFresh=document.querySelector("#sidebar-freshness");
const sidebarToggle=document.querySelector("#sidebar-toggle");
const backdrop=document.querySelector("#mobile-backdrop");

function closeSidebar(){
  document.body.classList.remove("sidebar-open");
  sidebarToggle.setAttribute("aria-expanded","false");
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
      fresh.textContent=briefing.freshness.canvas_status;
      fresh.className=`status-pill ${briefing.freshness.canvas_status}`;
      sidebarFresh.textContent=`Canvas ${briefing.freshness.canvas_status}`;
      renderHome(root,briefing,value=>show("assistant",value));
    }else if(view==="assistant") renderAssistant(root,question);
    else if(view==="calendar") await renderCalendar(root);
    else if(view==="notifications") await renderNotifications(root);
    else if(view==="review") await renderReview(root);
    else if(view==="settings") await renderSettings(root);
    else renderDeferred(root,view);
  }catch(error){ root.textContent=`Unable to load this view: ${error.message}`; }
}

await bootstrapSession();
document.querySelectorAll("[data-view]").forEach(button=>
  button.addEventListener("click",()=>show(button.dataset.view)));
document.querySelector("#logout").addEventListener("click",async()=>{
  await post("/api/v1/auth/logout",{});
  location.replace("/login");
});
sidebarToggle.addEventListener("click",()=>{
  const open=document.body.classList.toggle("sidebar-open");
  sidebarToggle.setAttribute("aria-expanded",String(open));
});
backdrop.addEventListener("click",closeSidebar);
window.addEventListener("popstate",()=>show(location.pathname.split("/")[2]||"home"));
show(location.pathname.split("/")[2]||"home");

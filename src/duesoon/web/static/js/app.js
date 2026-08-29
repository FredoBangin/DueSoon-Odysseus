import {bootstrapSession,get,post} from "./api.js";
import {renderHome} from "./views/home.js";
import {renderAssistant} from "./views/assistant.js";
import {renderCalendar} from "./views/calendar.js";
import {renderNotifications} from "./views/notifications.js";
import {renderDocuments,renderEmail,renderMemory,renderNotes,renderReview,renderSettings} from "./views/foundations.js";

const root=document.querySelector("#content");
const title=document.querySelector("#page-title");
const settingsModal=document.querySelector("#settings-modal");
const settingsRoot=document.querySelector("#settings-content");
const titles={home:"Academic briefing",assistant:"Assistant",calendar:"Calendar",email:"School email",notifications:"Notifications",review:"Learning review",notes:"Notes",memory:"Memory",documents:"Documents",settings:"Settings"};
let currentView="home";

function markActive(view){
  document.querySelectorAll("[data-view]").forEach(button=>
    button.classList.toggle("active",button.dataset.view===view));
}

function setSettingsOpen(open){
  settingsModal.classList.toggle("hidden",!open);
  settingsModal.setAttribute("aria-hidden",String(!open));
  if(!open) markActive(currentView);
}

function closeSidebar(){
  window.closeDueSoonSidebar?.();
}

async function show(view,question=""){
  if(view==="settings"){
    markActive("settings");
    closeSidebar();
    try{
      await renderSettings(settingsRoot);
      setSettingsOpen(true);
    }catch(error){
      settingsRoot.textContent=`Unable to load settings: ${error.message}`;
      setSettingsOpen(true);
    }
    return;
  }
  currentView=view;
  setSettingsOpen(false);
  markActive(view);
  title.textContent=titles[view]||view[0].toUpperCase()+view.slice(1);
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
    else show("home");
  }catch(error){ root.textContent=`Unable to load this view: ${error.message}`; }
}

const session=await bootstrapSession();
const userName=document.querySelector("#user-bar-name");
const userAvatar=document.querySelector("#user-bar-avatar");
if(userName && session.username) userName.textContent=session.username;
if(userAvatar && session.username) userAvatar.textContent=session.username.slice(0,1).toUpperCase();
document.querySelectorAll("[data-view]").forEach(button=>
  button.addEventListener("click",()=>show(button.dataset.view)));
document.querySelectorAll('[data-view][role="button"]').forEach(button=>
  button.addEventListener("keydown",event=>{
    if(event.key==="Enter"||event.key===" "){event.preventDefault();button.click();}
  }));
const appearanceButton=document.querySelector("#tool-theme-btn");
appearanceButton?.addEventListener("click",async()=>{
  await show("settings");
  document.querySelector('[data-duesoon-settings-tab="appearance"]')?.click();
});
appearanceButton?.addEventListener("keydown",event=>{
  if(event.key==="Enter"||event.key===" "){event.preventDefault();appearanceButton.click();}
});
document.querySelector("#logout").addEventListener("click",async()=>{
  await post("/api/v1/auth/logout",{});
  location.replace("/login");
});
document.querySelectorAll("[data-close-settings]").forEach(button=>button.addEventListener("click",()=>setSettingsOpen(false)));
settingsModal.addEventListener("click",event=>{if(event.target===settingsModal)setSettingsOpen(false);});
document.addEventListener("keydown",event=>{if(event.key==="Escape"&&!settingsModal.classList.contains("hidden"))setSettingsOpen(false);});
window.addEventListener("popstate",()=>show(location.pathname.split("/")[2]||"home"));
const initialView=location.pathname.split("/")[2]||"home";
if(initialView==="settings"){
  await show("home");
  await show("settings");
}else{
  await show(initialView);
}

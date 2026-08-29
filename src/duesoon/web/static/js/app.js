import {bootstrapSession,get,post} from "./api.js";
import {renderHome} from "./views/home.js";
import {renderAssistant} from "./views/assistant.js";
import {renderCalendar} from "./views/calendar.js";
import {renderNotifications} from "./views/notifications.js";
import {renderDocuments,renderEmail,renderMemory,renderNotes,renderReview,renderSettings} from "./views/foundations.js";

const root=document.querySelector("#content");
const title=document.querySelector("#page-title, #current-meta");

// The full Odysseus document is the shell.  Its navigation IDs are stable,
// while DueSoon routes are intentionally smaller; map retained launchers to
// those routes instead of adding a second visual navigation system.
const navigation={
  "sidebar-brand-btn":"home",
  "rail-chats":"assistant",
  "rail-calendar":"calendar",
  "rail-email":"email",
  "rail-memory":"memory",
  "rail-notes":"notes",
  "rail-archive":"documents",
  "rail-tasks":"notifications",
  "rail-settings":"settings",
  "tool-memory-btn":"memory",
  "tool-calendar-btn":"calendar",
  "tool-email-btn":"email",
  "tool-notes-btn":"notes",
  "tool-library-btn":"documents",
  "tool-tasks-btn":"notifications",
  "email-section-title":"email",
};
for(const [id,view] of Object.entries(navigation)){
  const element=document.getElementById(id);
  if(element){
    element.dataset.view=view;
    if(!element.hasAttribute("role")) element.setAttribute("role","button");
    if(!element.hasAttribute("tabindex")) element.setAttribute("tabindex","0");
  }
}

// Odysseus has no sign-out row in its stock shell.  Add the existing shell
// button treatment so DueSoon keeps session control without inventing a card.
let logout=document.querySelector("#logout");
if(!logout){
  const settingsButton=document.querySelector("#user-bar-settings");
  const actions=settingsButton?.parentElement;
  if(actions){
    logout=document.createElement("button");
    logout.type="button";
    logout.id="logout";
    logout.className="user-bar-btn";
    logout.title="Sign out";
    logout.setAttribute("aria-label","Sign out");
    logout.innerHTML='<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 17l5-5-5-5"/><path d="M15 12H3"/><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/></svg>';
    actions.append(logout);
  }
}

function closeSidebar(){
  window.closeDueSoonSidebar?.();
}

async function show(view,question=""){
  document.querySelectorAll("[data-view]").forEach(button=>
    button.classList.toggle("active",button.dataset.view===view));
  if(title) title.textContent=view[0].toUpperCase()+view.slice(1);
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
logout?.addEventListener("click",async()=>{
  await post("/api/v1/auth/logout",{});
  location.replace("/login");
});

// Reuse the stock Odysseus composer for the dashboard assistant.  This keeps
// the interaction shell identical across Home and the other retained tools.
const composer=document.querySelector("#chat-form");
const message=document.querySelector("#message");
const sendButton=document.querySelector(".send-btn");
const askAssistant=async(question)=>{
  if(!question) return;
  const user=document.createElement("div");
  user.className="msg msg-user";
  user.innerHTML='<div class="role">You</div><div class="body"></div>';
  user.querySelector(".body").textContent=question;
  root.append(user);
  if(sendButton) sendButton.disabled=true;
  try{
    const value=await post("/api/v1/dashboard/assistant",{question});
    const reply=document.createElement("div");
    reply.className="msg msg-ai";
    reply.innerHTML='<div class="role">DueSoon</div><div class="body"></div>';
    const body=reply.querySelector(".body");
    const answer=document.createElement("p");
    answer.textContent=value.answer;
    body.append(answer);
    const detail=document.createElement("small");
    detail.className="admin-toggle-sub";
    detail.textContent=[value.mode,value.model,value.confidence,`data ${value.data_freshness}`].filter(Boolean).join(" · ");
    body.append(detail);
    root.append(reply);
  }catch(error){
    const reply=document.createElement("div");
    reply.className="msg msg-ai";
    reply.innerHTML='<div class="role">DueSoon</div><div class="body"></div>';
    reply.querySelector(".body").textContent=error.message;
    root.append(reply);
  }finally{
    if(sendButton) sendButton.disabled=false;
    root.scrollTop=root.scrollHeight;
  }
};
composer?.addEventListener("submit",event=>{
  event.preventDefault();
  const question=message?.value.trim();
  if(message) message.value="";
  askAssistant(question);
});
sendButton?.addEventListener("click",event=>{
  event.preventDefault();
  const question=message?.value.trim();
  if(message) message.value="";
  askAssistant(question);
});
document.querySelector("#app-loader")?.remove();
window.addEventListener("popstate",()=>show(location.pathname.split("/")[2]||"home"));
show(location.pathname.split("/")[2]||"home");

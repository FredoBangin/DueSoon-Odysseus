import {get,patch,post} from "../api.js";
import {node} from "./home.js";

const COPY={
  email:["Email","Read-only Gmail evidence is next. Canvas Inbox and announcements are already part of the ingestion foundation."],
  notes:["Notes","This retained Odysseus space will become assignment annotations and evidence notes."],
  memory:["Memory","Approved academic aliases, explanation preferences, and matching feedback will live here."],
  documents:["Documents","Canvas module, page, and course-file evidence ingestion is being connected here."],
};

export function renderDeferred(root,key){
  root.replaceChildren();
  const [title,copy]=COPY[key];
  const panel=node("article","","panel wide");
  panel.append(node("h2",title),node("p",copy),node("span","Retained from Odysseus · safe foundation","pill"));
  root.append(panel);
}

export async function renderEmail(root){
  const value=await get("/api/v1/dashboard/gmail?limit=25");
  root.replaceChildren();
  const intro=node("article","","panel wide");
  intro.append(node("h2","School email"),node("p","Read-only Gmail. DueSoon cannot send, delete, archive, or modify messages.","muted"));
  root.append(intro);
  if(!value.enabled){
    root.append(node("p","Gmail is not configured on the Azure server yet.","empty"));
    return;
  }
  if(!value.items.length) root.append(node("p","No matching inbox messages.","empty"));
  for(const item of value.items){
    const card=node("article","","panel");
    card.append(node("h2",item.subject),node("p",item.from,"muted"),node("p",item.snippet));
    if(item.attachments.length) card.append(node("small",`${item.attachments.length} attachment(s) · evidence metadata only`,"muted"));
    root.append(card);
  }
}

export async function renderReview(root){
  const value=await get("/api/v1/dashboard/review");
  root.replaceChildren();
  const intro=node("article","","panel wide");
  intro.append(node("h2","Learning review"),node("p",value.message,"muted"));
  root.append(intro);
  if(!value.items.length){ root.append(node("p","No learning proposals yet.","empty")); return; }
  for(const item of value.items){
    const card=node("article","","panel");
    card.append(node("h2",`${item.scope_type} · ${item.status}`));
    card.append(node("p",item.after));
    card.append(node("p",item.affected_future_behavior,"muted"));
    const controls=node("div","","toolbar");
    const actions=item.status==="proposed"?["approve","reject","edit"]:["undo"];
    for(const action of actions){
      const button=node("button",action,action==="approve"?"":"secondary");
      button.onclick=async()=>{
        let edited_text;
        if(action==="edit"){
          const field=document.createElement("textarea");
          field.value=item.after;
          field.rows=4;
          const save=node("button","Save proposal");
          const form=node("form","","panel");
          form.append(field,save);
          form.onsubmit=async event=>{
            event.preventDefault();
            await post(`/api/v1/dashboard/review/${item.id}`,{action:"edit",edited_text:field.value});
            renderReview(root);
          };
          card.append(form);
          return;
        }
        await post(`/api/v1/dashboard/review/${item.id}`,{action,edited_text});
        renderReview(root);
      };
      controls.append(button);
    }
    card.append(controls);
    root.append(card);
  }
}

export async function renderSettings(root){
  const [value,model]=await Promise.all([
    get("/api/v1/dashboard/settings"),
    get("/api/v1/dashboard/model-settings"),
  ]);
  root.replaceChildren();
  const connections=node("article","","panel wide");
  connections.append(node("h2","Connections and capabilities"));
  for(const [name,status] of Object.entries({...value.features,canvas:value.canvas.status,notifications:value.notifications.status})){
    const row=node("div","","capability");
    row.append(node("strong",name.replaceAll("_"," ")),node("span",String(status),"pill"));
    connections.append(row);
  }
  root.append(connections);

  const provider=node("form","","panel wide");
  provider.append(node("h2","Assistant model routing"));
  provider.append(node("p",model.api_key_configured?"API key loaded securely from the server environment.":"Add DUESOON_MODEL_API_KEY to the Azure secrets file before enabling.","muted"));
  provider.append(node("p",`Provider: ${model.base_url}`,"muted"));
  const enabled=document.createElement("input");
  enabled.type="checkbox";
  enabled.checked=model.enabled;
  enabled.style.width="auto";
  const enabledLabel=node("label","Enable model-backed answers");
  enabledLabel.prepend(enabled);
  const primary=document.createElement("input"); primary.value=model.primary_model||""; primary.placeholder="Primary model";
  const fallbacks=document.createElement("input"); fallbacks.value=(model.fallback_models||[]).join(", "); fallbacks.placeholder="Fallback models, comma separated";
  const save=node("button","Save model settings");
  const result=node("p","","muted");
  provider.append(enabledLabel,primary,fallbacks,save,result);
  provider.onsubmit=async event=>{
    event.preventDefault(); save.disabled=true;
    try{
      await patch("/api/v1/dashboard/model-settings",{
        enabled:enabled.checked,
        primary_model:primary.value.trim(),
        fallback_models:fallbacks.value.split(",").map(item=>item.trim()).filter(Boolean),
      });
      result.textContent="Saved. Server-held API key was not exposed.";
    }catch(error){ result.textContent=error.message; }
    finally{ save.disabled=false; }
  };
  root.append(provider);
}

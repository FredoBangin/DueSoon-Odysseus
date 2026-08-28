import {get,patch,post} from "../api.js";
import {node} from "./home.js";

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

export async function renderNotes(root){
  const value=await get("/api/v1/dashboard/notes");
  root.replaceChildren();
  const form=node("form","","panel wide form-stack");
  form.append(node("h2","Academic notes"),node("p","Keep assignment context and your own observations here. Notes never change a deadline or submission state.","muted"));
  const title=document.createElement("input"); title.required=true; title.maxLength=500; title.placeholder="Note title";
  const body=document.createElement("textarea"); body.required=true; body.maxLength=10000; body.rows=4; body.placeholder="What should you remember?";
  const save=node("button","Save note");
  const result=node("p","","muted");
  form.append(title,body,save,result);
  form.onsubmit=async event=>{
    event.preventDefault(); save.disabled=true;
    try{ await post("/api/v1/dashboard/notes",{title:title.value,body:body.value}); await renderNotes(root); }
    catch(error){ result.textContent=error.message; save.disabled=false; }
  };
  root.append(form);
  if(!value.items.length){ root.append(node("p","No academic notes yet.","empty")); return; }
  for(const item of value.items){
    const card=node("article","","panel");
    card.append(node("h2",item.title),node("p",item.body));
    const context=[item.course_name,item.assignment_title].filter(Boolean).join(" · ");
    if(context) card.append(node("small",context,"muted"));
    const controls=node("div","","toolbar");
    const archive=node("button","Archive","secondary");
    archive.onclick=async()=>{ archive.disabled=true; await patch(`/api/v1/dashboard/notes/${item.id}`,{archived:true}); await renderNotes(root); };
    controls.append(archive); card.append(controls); root.append(card);
  }
}

export async function renderMemory(root){
  const value=await get("/api/v1/dashboard/memories");
  root.replaceChildren();
  const form=node("form","","panel wide form-stack");
  form.append(node("h2","Approved academic memory"),node("p","Store aliases, preferences, matching feedback, or source-reliability guidance. You control every entry.","muted"));
  const type=document.createElement("select");
  for(const option of ["alias","preference","matching_feedback","source_reliability"]){ const el=document.createElement("option"); el.value=option; el.textContent=option.replaceAll("_"," "); type.append(el); }
  const scope=document.createElement("select");
  for(const option of ["global","course","assignment","sender"]){ const el=document.createElement("option"); el.value=option; el.textContent=option; scope.append(el); }
  const scopeRef=document.createElement("input"); scopeRef.maxLength=255; scopeRef.placeholder="Scope reference (optional)";
  const label=document.createElement("input"); label.required=true; label.maxLength=500; label.placeholder="Short label";
  const content=document.createElement("textarea"); content.required=true; content.maxLength=5000; content.rows=3; content.placeholder="What should DueSoon learn?";
  const save=node("button","Save approved memory"); const result=node("p","","muted");
  form.append(type,scope,scopeRef,label,content,save,result);
  form.onsubmit=async event=>{
    event.preventDefault(); save.disabled=true;
    try{ await post("/api/v1/dashboard/memories",{memory_type:type.value,scope_type:scope.value,scope_ref:scopeRef.value||null,label:label.value,value:content.value}); await renderMemory(root); }
    catch(error){ result.textContent=error.message; save.disabled=false; }
  };
  root.append(form);
  if(!value.items.length){ root.append(node("p","No approved memory yet.","empty")); return; }
  for(const item of value.items){
    const card=node("article","","panel");
    card.append(node("h2",item.label),node("p",item.value),node("small",`${item.memory_type.replaceAll("_"," ")} · ${item.scope_type}${item.scope_ref?` · ${item.scope_ref}`:""}`,"muted"));
    const controls=node("div","","toolbar"); const disable=node("button","Deactivate","secondary");
    disable.onclick=async()=>{ disable.disabled=true; await patch(`/api/v1/dashboard/memories/${item.id}`,{active:false}); await renderMemory(root); };
    controls.append(disable); card.append(controls); root.append(card);
  }
}

export async function renderDocuments(root){
  const value=await get("/api/v1/dashboard/documents?limit=150");
  root.replaceChildren();
  const intro=node("article","","panel wide");
  intro.append(node("h2","Canvas documents"),node("p","Read-only evidence catalog from Canvas files, pages, and modules. Raw document bodies and signed download URLs are not exposed here.","muted"));
  root.append(intro);
  if(!value.items.length){ root.append(node("p","No Canvas document evidence synced yet.","empty")); return; }
  for(const item of value.items){
    const card=node("article","","panel");
    card.append(node("h2",item.title),node("p",item.course_name||"Canvas","muted"),node("span",item.source_type.replaceAll("_"," "),"pill"));
    const details=[item.content_type,item.size?`${item.size} bytes`:null].filter(Boolean).join(" · ");
    if(details) card.append(node("small",details,"muted"));
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

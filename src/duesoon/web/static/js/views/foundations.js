import {get,patch,post} from "../api.js";
import {node} from "./home.js";

const muted="admin-toggle-sub";
const card="admin-card";
const action="theme-io-btn";

export async function renderEmail(root){
  const value=await get("/api/v1/dashboard/gmail?limit=25"); root.replaceChildren();
  const intro=node("article","",card); intro.append(node("h2","School email"),node("p","Read-only Gmail. DueSoon cannot send, delete, archive, or modify messages.",muted)); root.append(intro);
  if(!value.enabled){root.append(node("p","Gmail is not configured on the Azure server yet.",muted));return;}
  const sync=node("button","Save inbox as evidence",action),result=node("span","",muted);
  sync.type="button";sync.onclick=async()=>{sync.disabled=true;try{const saved=await post("/api/v1/dashboard/gmail/sync",{});result.textContent=`${saved.stored} new · ${saved.unchanged} unchanged`; }catch(error){result.textContent=error.message;}finally{sync.disabled=false;}};
  const controls=node("div","","theme-io-row");controls.append(sync,result);intro.append(controls);
  if(!value.items.length) root.append(node("p","No matching inbox messages.",muted));
  for(const item of value.items){const email=node("article","",card);email.append(node("h2",item.subject),node("p",item.from,muted),node("p",item.snippet));if(item.attachments.length)email.append(node("small",`${item.attachments.length} attachment(s) · evidence metadata only`,muted));root.append(email);}
}

export async function renderNotes(root){
  const value=await get("/api/v1/dashboard/notes"); root.replaceChildren();
  const form=node("form","",card); form.append(node("h2","Academic notes"),node("p","Keep assignment context and your own observations here. Notes never change a deadline or submission state.",muted));
  const title=document.createElement("input"); title.required=true; title.maxLength=500; title.placeholder="Note title";
  const body=document.createElement("textarea"); body.required=true; body.maxLength=10000; body.rows=4; body.placeholder="What should you remember?";
  const save=node("button","Save note",action); const result=node("p","",muted); form.append(title,body,save,result);
  form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{await post("/api/v1/dashboard/notes",{title:title.value,body:body.value});await renderNotes(root);}catch(error){result.textContent=error.message;save.disabled=false;}};
  root.append(form);
  if(!value.items.length){root.append(node("p","No academic notes yet.",muted));return;}
  for(const item of value.items){const note=node("article","",card);note.append(node("h2",item.title),node("p",item.body));const context=[item.course_name,item.assignment_title].filter(Boolean).join(" · ");if(context)note.append(node("small",context,muted));const controls=node("div","","cal-toolbar");const archive=node("button","Archive",action);archive.onclick=async()=>{archive.disabled=true;await patch(`/api/v1/dashboard/notes/${item.id}`,{archived:true});await renderNotes(root);};controls.append(archive);note.append(controls);root.append(note);}
}

export async function renderMemory(root){
  const value=await get("/api/v1/dashboard/memories"); root.replaceChildren();
  const form=node("form","",card); form.append(node("h2","Approved academic memory"),node("p","Store aliases, preferences, matching feedback, or source-reliability guidance. You control every entry.",muted));
  const type=document.createElement("select"); for(const option of ["alias","preference","matching_feedback","source_reliability"]){const el=document.createElement("option");el.value=option;el.textContent=option.replaceAll("_"," ");type.append(el);}
  const scope=document.createElement("select"); for(const option of ["global","course","assignment","sender"]){const el=document.createElement("option");el.value=option;el.textContent=option;scope.append(el);}
  const scopeRef=document.createElement("input");scopeRef.maxLength=255;scopeRef.placeholder="Scope reference (optional)";
  const label=document.createElement("input");label.required=true;label.maxLength=500;label.placeholder="Short label";
  const content=document.createElement("textarea");content.required=true;content.maxLength=5000;content.rows=3;content.placeholder="What should DueSoon learn?";
  const save=node("button","Save approved memory",action),result=node("p","",muted); form.append(type,scope,scopeRef,label,content,save,result);
  form.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{await post("/api/v1/dashboard/memories",{memory_type:type.value,scope_type:scope.value,scope_ref:scopeRef.value||null,label:label.value,value:content.value});await renderMemory(root);}catch(error){result.textContent=error.message;save.disabled=false;}};
  root.append(form);
  if(!value.items.length){root.append(node("p","No approved memory yet.",muted));return;}
  for(const item of value.items){const memory=node("article","",card);memory.append(node("h2",item.label),node("p",item.value),node("small",`${item.memory_type.replaceAll("_"," ")} · ${item.scope_type}${item.scope_ref?` · ${item.scope_ref}`:""}`,muted));const controls=node("div","","cal-toolbar");const disable=node("button","Deactivate",action);disable.onclick=async()=>{disable.disabled=true;await patch(`/api/v1/dashboard/memories/${item.id}`,{active:false});await renderMemory(root);};controls.append(disable);memory.append(controls);root.append(memory);}
}

export async function renderDocuments(root){
  const value=await get("/api/v1/dashboard/documents?limit=150");root.replaceChildren();
  const intro=node("article","",card);intro.append(node("h2","Academic documents"),node("p","Read-only evidence catalog from Canvas files, pages, modules, and saved Gmail. Raw bodies and signed download URLs are not exposed here.",muted));root.append(intro);
  if(!value.items.length){root.append(node("p","No document or email evidence synced yet.",muted));return;}
  for(const item of value.items){const doc=node("article","",card);doc.append(node("h2",item.title),node("p",item.course_name||item.sender||item.source,muted),node("span",item.source_type.replaceAll("_"," "),"cal-event-tag"));const details=[item.content_type,item.size?`${item.size} bytes`:null].filter(Boolean).join(" · ");if(details)doc.append(node("small",details,muted));root.append(doc);}
}

export async function renderReview(root){
  const value=await get("/api/v1/dashboard/review");root.replaceChildren();
  const intro=node("article","",card);intro.append(node("h2","Learning review"),node("p",value.message,muted));root.append(intro);
  const evidenceItems=value.evidence_items||[];
  if(evidenceItems.length){
    root.append(node("h2","Academic evidence to review"));
    for(const item of evidenceItems){
      const review=node("article","",card);
      const title=item.assignment_title||item.assignment_hint||"Unmatched academic claim";
      const context=[item.course_name,item.source_type?.replaceAll("_"," "),item.status].filter(Boolean).join(" · ");
      review.append(node("h2",title),node("p",context,muted));
      if(item.candidate_due_at)review.append(node("p",`Candidate deadline: ${new Date(item.candidate_due_at).toLocaleString()}`));
      review.append(node("p",`${item.claim_type.replaceAll("_"," ")} · ${item.confidence} confidence · ${item.precision} precision`,muted),node("p",item.reason),node("small","Raw source content stays private. Review does not approve or change a deadline.",muted));
      if(item.assignment_id){
        const controls=node("div","","cal-toolbar");
        const inspect=node("button","Review assignment",action),details=node("div","",muted);
        inspect.type="button";
        inspect.onclick=async()=>{inspect.disabled=true;try{const value=await get(`/api/v1/dashboard/assignments/${item.assignment_id}/evidence`);details.replaceChildren(node("p",value.resolution_explanation));for(const evidence of value.items)details.append(node("p",`${evidence.source_type.replaceAll("_"," ")} · ${evidence.disposition} · ${evidence.summary}`));}catch(error){details.textContent=error.message;}finally{inspect.disabled=false;}};
        controls.append(inspect);review.append(controls,details);
      }
      root.append(review);
    }
  }
  if(!value.items.length){if(!evidenceItems.length)root.append(node("p","Nothing needs review.",muted));return;}
  root.append(node("h2","Learning proposals"));
  for(const item of value.items){
    const review=node("article","",card);
    review.append(node("h2",`${item.scope_type} · ${item.status}`),node("p",item.after),node("p",item.affected_future_behavior,muted));
    review.append(node("small",`Created by ${item.created_by||"owner"} · revision ${item.revision}`,muted));
    if(item.audit?.length)review.append(node("p",`Audit: ${item.audit.map(event=>event.action).join(" → ")}`,muted));
    const controls=node("div","","cal-toolbar");
    const actions=item.status==="proposed"?["approve","reject","edit"]:["approved","rejected"].includes(item.status)?["undo"]:[];
    for(const actionName of actions){
      const button=node("button",actionName,actionName==="approve"?"confirm-btn confirm-btn-primary":action);
      button.onclick=async()=>{
        if(actionName==="edit"){
          const field=document.createElement("textarea");field.value=item.after;field.rows=4;
          const save=node("button","Save proposal","confirm-btn confirm-btn-primary");
          const form=node("form","",card);form.append(field,save);
          form.onsubmit=async event=>{event.preventDefault();await post(`/api/v1/dashboard/review/${item.id}`,{action:"edit",edited_text:field.value});renderReview(root);};
          review.append(form);return;
        }
        await post(`/api/v1/dashboard/review/${item.id}`,{action:actionName});renderReview(root);
      };
      controls.append(button);
    }
    review.append(controls);root.append(review);
  }
}

export async function renderSettings(root){
  const [value,model]=await Promise.all([get("/api/v1/dashboard/settings"),get("/api/v1/dashboard/model-settings")]);
  root.replaceChildren();
  document.querySelectorAll("[data-duesoon-settings-tab]").forEach(button=>button.classList.toggle("active",button.dataset.duesoonSettingsTab==="connections"));

  const connectionsPanel=node("section","");
  connectionsPanel.dataset.settingsPanel="connections";
  const connections=node("article","",card);
  connections.append(node("h2","Connections and capabilities"));
  for(const [name,status] of Object.entries({...value.features,canvas:value.canvas.status,notifications:value.notifications.status})){
    const row=node("div","","admin-toggle-row");
    const copy=node("div","");
    copy.append(node("div",name.replaceAll("_"," "),"admin-toggle-label"));
    row.append(copy,node("span",String(status),"cal-event-tag"));
    connections.append(row);
  }
  connectionsPanel.append(connections);

  const assistantPanel=node("section","","hidden");
  assistantPanel.dataset.settingsPanel="assistant";
  const provider=node("form","",card);
  provider.append(
    node("h2","Assistant model routing"),
    node("p",model.api_key_configured?"API key loaded securely from the server environment.":"Add DUESOON_MODEL_API_KEY to the Azure secrets file before enabling.",muted),
    node("p",`Provider: ${model.base_url}`,muted),
  );

  const enabled=document.createElement("input");
  enabled.type="checkbox";
  enabled.checked=model.enabled;
  const switchControl=node("label","","admin-switch");
  switchControl.append(enabled,node("span","","admin-slider"));
  const enabledRow=node("div","","admin-toggle-row");
  const enabledCopy=node("div","");
  enabledCopy.append(node("div","Model-backed answers","admin-toggle-label"),node("div","Deterministic answers remain available when disabled.","admin-toggle-sub"));
  enabledRow.append(enabledCopy,switchControl);

  const primaryLabel=node("label","Primary model","settings-label");
  const primary=document.createElement("input");
  primary.className="settings-input";
  primary.type="text";
  primary.value=model.primary_model||"";
  primary.placeholder="Primary model";

  const fallbacksLabel=node("label","Fallback models","settings-label");
  const fallbacks=document.createElement("input");
  fallbacks.className="settings-input";
  fallbacks.type="text";
  fallbacks.value=(model.fallback_models||[]).join(", ");
  fallbacks.placeholder="Comma separated";

  const save=node("button","Save model settings","confirm-btn confirm-btn-primary");
  const result=node("p","",muted);
  provider.append(enabledRow,primaryLabel,primary,fallbacksLabel,fallbacks,save,result);
  provider.onsubmit=async event=>{event.preventDefault();save.disabled=true;try{await patch("/api/v1/dashboard/model-settings",{enabled:enabled.checked,primary_model:primary.value.trim(),fallback_models:fallbacks.value.split(",").map(item=>item.trim()).filter(Boolean)});result.textContent="Saved. Server-held API key was not exposed.";}catch(error){result.textContent=error.message;}finally{save.disabled=false;}};
  assistantPanel.append(provider);

  const appearancePanel=node("section","","hidden");
  appearancePanel.dataset.settingsPanel="appearance";
  const themes=node("article","",card);
  themes.append(node("h2","Theme"),node("p","Choose an inherited Odysseus palette.",muted));
  const themeChoices=node("div","","theme-io-row");
  for(const option of [["dark","Dark"],["midnight","Midnight"],["ocean","Ocean"],["forest","Forest"],["ume","Ume"]]){
    const button=node("button",option[1],"theme-io-btn");
    button.type="button";
    button.dataset.theme=option[0];
    themeChoices.append(button);
  }
  themes.append(themeChoices);
  const backgrounds=node("article","",card);
  backgrounds.append(node("h2","Animated background"),node("p","Use the original Odysseus effects or turn animation off.",muted));
  const backgroundChoices=node("div","","theme-io-row");
  for(const option of [["constellations","Constellations"],["rain","Rain"],["perlin-flow","Flow"],["none","None"]]){
    const button=node("button",option[1],"theme-io-btn");
    button.type="button";
    button.dataset.bgPattern=option[0];
    backgroundChoices.append(button);
  }
  backgrounds.append(backgroundChoices);
  appearancePanel.append(themes,backgrounds);

  root.append(connectionsPanel,assistantPanel,appearancePanel);
  document.querySelectorAll("[data-duesoon-settings-tab]").forEach(button=>{
    button.onclick=()=>{
      document.querySelectorAll("[data-duesoon-settings-tab]").forEach(item=>item.classList.toggle("active",item===button));
      root.querySelectorAll("[data-settings-panel]").forEach(panel=>panel.classList.toggle("hidden",panel.dataset.settingsPanel!==button.dataset.duesoonSettingsTab));
    };
  });
}

import {post} from "../api.js";
import {node} from "./home.js";

function attachFeedback(reply,value){
  if(!value.answer_id) return;
  const controls=node("div","","toolbar");
  controls.append(node("span","Was this right?","muted"));
  for(const verdict of ["correct","incorrect","uncertain"]){
    const button=node("button",verdict,"secondary");
    button.onclick=async()=>{
      controls.querySelectorAll("button").forEach(item=>item.disabled=true);
      if(verdict==="correct"){
        await post(`/api/v1/dashboard/assistant/${value.answer_id}/feedback`,{verdict});
        controls.replaceChildren(node("span","Saved. Thanks.","muted"));
        return;
      }
      const form=node("form","","panel");
      form.append(node("strong","What was wrong, and what should DueSoon understand next time?"));
      const correction=document.createElement("textarea");
      correction.required=true;
      correction.maxLength=2000;
      correction.rows=4;
      const save=node("button","Create review proposal");
      form.append(correction,save);
      form.onsubmit=async event=>{
        event.preventDefault();
        save.disabled=true;
        try{
          await post(`/api/v1/dashboard/assistant/${value.answer_id}/feedback`,{
            verdict,
            what_was_wrong:correction.value.trim(),
            scope_type:"global",
          });
          form.replaceChildren(node("span","Proposal saved for your Review tab.","muted"));
        }catch(error){
          save.disabled=false;
          form.append(node("p",error.message,"error"));
        }
      };
      reply.append(form);
    };
    controls.append(button);
  }
  reply.append(controls);
}

export function renderAssistant(root,initial=""){
  root.replaceChildren();
  const intro=node("article","","panel wide");
  intro.append(node("p","Ask about deadlines, missing work, workload, reminders, or what changed. Answers use your DueSoon evidence and never change canonical deadlines.","muted"));
  const log=node("div");
  const form=node("form","","assistant-box");
  const input=document.createElement("input");
  const button=node("button","Ask");
  input.maxLength=500;
  input.placeholder="Hey, any updates on school stuff?";
  form.append(input,button);
  root.append(intro,log,form);

  async function ask(question){
    log.append(node("div",question,"message user"));
    button.disabled=true;
    try{
      const value=await post("/api/v1/dashboard/assistant",{question});
      const reply=node("div","","message");
      reply.append(node("strong",value.answer));
      const detail=[value.mode,value.model,value.confidence,`data ${value.data_freshness}`].filter(Boolean).join(" · ");
      reply.append(node("p",detail,"muted"));
      const evidence=node("div","","evidence");
      for(const item of value.evidence||[]){
        const link=node("a",item.label);
        link.href=item.href;
        link.rel="noopener noreferrer";
        evidence.append(link);
      }
      reply.append(evidence);
      attachFeedback(reply,value);
      log.append(reply);
    }catch(error){ log.append(node("div",error.message,"message error")); }
    finally{ button.disabled=false; }
  }
  form.addEventListener("submit",event=>{
    event.preventDefault();
    const value=input.value.trim();
    input.value="";
    if(value) ask(value);
  });
  if(initial) ask(initial);
}

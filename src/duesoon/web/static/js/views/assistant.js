import {post} from "../api.js";
import {node} from "./home.js";

function attachFeedback(reply,value){
  if(!value.answer_id) return;
  const controls=node("div","","cal-toolbar");
  controls.append(node("span","Was this right?","admin-toggle-sub"));
  for(const verdict of ["correct","incorrect","uncertain"]){
    const button=node("button",verdict,"theme-io-btn");
    button.onclick=async()=>{
      controls.querySelectorAll("button").forEach(item=>item.disabled=true);
      if(verdict==="correct"){
        await post(`/api/v1/dashboard/assistant/${value.answer_id}/feedback`,{verdict});
        controls.replaceChildren(node("span","Saved. Thanks.","admin-toggle-sub"));
        return;
      }
      const form=node("form","","admin-card");
      form.append(node("strong","What was wrong, and what should DueSoon understand next time?"));
      const correction=document.createElement("textarea");
      correction.required=true;
      correction.maxLength=2000;
      correction.rows=4;
      const save=node("button","Create review proposal","confirm-btn confirm-btn-primary");
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
          form.replaceChildren(node("span","Proposal saved for your Review tab.","admin-toggle-sub"));
        }catch(error){
          save.disabled=false;
          form.append(node("p",error.message,"admin-toggle-sub"));
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
  const intro=node("article","","admin-card");
  intro.append(node("h2","DueSoon assistant"),node("p","Ask from the Odysseus composer below about deadlines, missing work, workload, reminders, or what changed. Answers never change canonical deadlines.","admin-toggle-sub"));
  const log=node("div");
  root.append(intro,log);

  async function ask(question){
    const user=node("div","","msg msg-user");
    user.innerHTML='<div class="role">You</div><div class="body"></div>';
    user.querySelector(".body").textContent=question;
    log.append(user);
    try{
      const value=await post("/api/v1/dashboard/assistant",{question});
      const reply=node("div","","msg msg-ai");
      reply.innerHTML='<div class="role">DueSoon</div><div class="body"></div>';
      const body=reply.querySelector(".body");
      body.append(node("p",value.answer));
      const detail=[value.mode,value.model,value.confidence,`data ${value.data_freshness}`].filter(Boolean).join(" · ");
      body.append(node("p",detail,"admin-toggle-sub"));
      const evidence=node("div","","cal-toolbar");
      for(const item of value.evidence||[]){
        const link=node("a",item.label,"theme-io-btn");
        link.href=item.href;
        link.rel="noopener noreferrer";
        evidence.append(link);
      }
      body.append(evidence);
      attachFeedback(reply,value);
      log.append(reply);
    }catch(error){
      const reply=node("div","","msg msg-ai");
      reply.innerHTML='<div class="role">DueSoon</div><div class="body"></div>';
      reply.querySelector(".body").textContent=error.message;
      log.append(reply);
    }
  }
  if(initial) ask(initial);
}

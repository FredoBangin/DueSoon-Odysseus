import{get}from"../api.js";import{node}from"./home.js";
export async function renderNotifications(root){
  const data=await get("/api/v1/dashboard/notifications?limit=50");root.replaceChildren();
  root.append(node("h2","Notifications","section-title"));
  if(!data.items.length){root.append(node("p","No notification activity yet.","admin-toggle-sub"));return;}
  for(const item of data.items){const panel=node("article","","admin-card");panel.append(node("h2",item.title),node("p",item.body),node("small",`${item.status} · ${item.provider}`,"admin-toggle-sub"));root.append(panel);}
}

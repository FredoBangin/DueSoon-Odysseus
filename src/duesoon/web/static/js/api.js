let csrfToken="";
async function parse(response){if(response.status===401){location.replace("/login");throw new Error("Session expired")}if(!response.ok)throw new Error(`Request failed (${response.status})`);return response.json()}
export async function bootstrapSession(){const value=await parse(await fetch("/api/v1/auth/session",{credentials:"same-origin",cache:"no-store"}));csrfToken=value.csrf_token;return value}
export async function get(path){return parse(await fetch(path,{credentials:"same-origin",cache:"no-store"}))}
export async function post(path,body){return parse(await fetch(path,{method:"POST",credentials:"same-origin",cache:"no-store",headers:{"Content-Type":"application/json","X-CSRF-Token":csrfToken},body:JSON.stringify(body)}))}

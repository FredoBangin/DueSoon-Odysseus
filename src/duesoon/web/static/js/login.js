import {startConstellations} from "./background.js";

startConstellations();

const form=document.querySelector("#login-form"),error=document.querySelector("#login-error"),password=document.querySelector("#password");
const update=new URLSearchParams(location.search).get("update");
const destination=/^[1-9][0-9]{0,9}$/.test(update||"")?`/app/assistant?update=${update}`:"/app";
form.addEventListener("submit",async event=>{event.preventDefault();error.textContent="";const body={username:document.querySelector("#username").value,password:password.value};password.value="";try{const response=await fetch("/api/v1/auth/login",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});if(!response.ok)throw new Error();location.replace(destination)}catch{error.textContent="Unable to sign in. Check your credentials and try again."}});

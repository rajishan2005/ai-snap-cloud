const BASE_URL='https://ai-snap-cloud-production.up.railway.app';
const seen=new Set();
let polling=false;

async function getConfig(){return chrome.storage.local.get({baseUrl:BASE_URL,pairCode:'',enabled:true,privateKey:null,publicKey:null});}
function b64urlToBytes(value){const s=value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4);const raw=atob(s);return Uint8Array.from(raw,c=>c.charCodeAt(0));}
function samePublicKey(a,b){return !!a&&!!b&&a.kty==='RSA'&&b.kty==='RSA'&&a.n===b.n&&a.e===b.e;}
async function decryptImage(data,headers,config){
  const iv=headers['X-AI-Snap-IV']||'',wrapped=headers['X-AI-Snap-Key']||'',mime=headers['X-AI-Snap-Mime']||'image/jpeg',name=headers['X-AI-Snap-Name']||'ai-snap.jpg';
  if(!iv||!wrapped)return {data,mime,name,encrypted:false};
  if(!config.privateKey)throw new Error('Secure pairing private key is missing. Create a new pairing.');
  if(config.publicKey){
    const s=await fetch(`${config.baseUrl.replace(/\/$/,'')}/api/pair/status?code=${encodeURIComponent(config.pairCode)}`,{cache:'no-store'});
    if(!s.ok)throw new Error(`Pairing status unavailable (${s.status}).`);
    const d=await s.json();
    if(!d.ok||!d.publicKey||!samePublicKey(config.publicKey,d.publicKey))throw new Error('Pairing key mismatch. Create a new secure pairing and reconnect the phone.');
  }
  let privateKey;
  try{privateKey=await crypto.subtle.importKey('jwk',config.privateKey,{name:'RSA-OAEP',hash:'SHA-256'},false,['decrypt']);}
  catch(e){throw new Error(`Invalid local RSA key: ${e?.name||'DOMException'}. Create a new pairing.`);}
  let raw;
  try{raw=await crypto.subtle.decrypt({name:'RSA-OAEP'},privateKey,b64urlToBytes(wrapped));}
  catch(e){throw new Error(`RSA key unwrap failed: ${e?.name||'DOMException'}. Create a new pairing.`);}
  const aes=await crypto.subtle.importKey('raw',raw,{name:'AES-GCM'},false,['decrypt']);
  try{return {data:await crypto.subtle.decrypt({name:'AES-GCM',iv:b64urlToBytes(iv)},aes,data),mime,name,encrypted:true};}
  catch(e){throw new Error(`AES-GCM decrypt failed: ${e?.name||'DOMException'}. The encrypted image or metadata does not match.`);}
}
async function fetchFile(base,code,name){
  const r=await fetch(`${base}/api/file/${encodeURIComponent(name)}?code=${encodeURIComponent(code)}`,{cache:'no-store'});
  if(!r.ok)return {ok:false,status:r.status,error:`Could not download encrypted image (${r.status}).`};
  const data=await r.arrayBuffer(),headers={};
  for(const n of ['X-AI-Snap-IV','X-AI-Snap-Key','X-AI-Snap-Mime','X-AI-Snap-Name'])headers[n]=r.headers.get(n)||'';
  if(!headers['X-AI-Snap-IV']||!headers['X-AI-Snap-Key']){const mr=await fetch(`${base}/api/file-meta?code=${encodeURIComponent(code)}&name=${encodeURIComponent(name)}`,{cache:'no-store'});if(mr.ok){const m=await mr.json();if(m.ok){headers['X-AI-Snap-IV']=m.iv||'';headers['X-AI-Snap-Key']=m.wrappedKey||'';headers['X-AI-Snap-Mime']=m.mime||'';headers['X-AI-Snap-Name']=m.originalName||'';}}}
  return {ok:true,data,headers};
}
async function ack(base,code,name){try{await fetch(`${base}/api/ack?code=${encodeURIComponent(code)}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name}),cache:'no-store'});}catch(_){} }
async function handlePending(sendResponse){
  if(polling){sendResponse({ok:true,busy:true});return;}polling=true;
  try{
    const c=await getConfig(),base=(c.baseUrl||BASE_URL).replace(/\/$/,'');
    if(!c.enabled||!base||!c.pairCode||!c.privateKey){sendResponse({ok:true,delivered:0});return;}
    const pr=await fetch(`${base}/api/pending?code=${encodeURIComponent(c.pairCode)}`,{cache:'no-store'});
    if(!pr.ok){sendResponse({ok:false,status:pr.status,error:`Pending check failed (${pr.status}).`});return;}
    const d=await pr.json(),files=Array.isArray(d.files)?d.files:[];let delivered=0;
    for(const f of files){if(!f?.name||seen.has(f.name))continue;seen.add(f.name);try{
      const r=await fetchFile(base,c.pairCode,f.name);if(!r.ok)throw new Error(r.error||'Download failed');
      const dec=await decryptImage(r.data,r.headers,{...c,baseUrl:base});
      const tabs=await chrome.tabs.query({active:true,lastFocusedWindow:true}),tab=tabs[0];
      if(!tab?.id||!/^https:\/\/(chatgpt\.com|chat\.openai\.com)\//i.test(tab.url||''))throw new Error('Open ChatGPT in the active tab first.');
      const result=await chrome.tabs.sendMessage(tab.id,{type:'AI_SNAP_FILE_DATA',data:dec.data,mime:dec.mime,name:dec.name});
      if(!result?.ok)throw new Error(result?.error||'ChatGPT rejected the image');
      await ack(base,c.pairCode,f.name);delivered++;
    }catch(e){seen.delete(f.name);console.error('AI Snap:',e);}}
    sendResponse({ok:true,delivered});
  }catch(e){sendResponse({ok:false,error:e?.message||'AI Snap background error'});}finally{polling=false;}
}
chrome.runtime.onInstalled.addListener(async()=>{await chrome.storage.local.set({enabled:true});});
chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{if(message?.type==='AI_SNAP_CHECK_NOW'){handlePending(sendResponse);return true;}});

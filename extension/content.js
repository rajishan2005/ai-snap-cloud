let eventSource=null,reconnectTimer=null,pollTimer=null,activeTab=false,pendingCheckInFlight=false;
const processing=new Set();
function fromB64url(value){const s=value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4);const raw=atob(s);return Uint8Array.from(raw,c=>c.charCodeAt(0));}
function fromBase64(value){const raw=atob(value);const out=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)out[i]=raw.charCodeAt(i);return out.buffer;}
function sleep(ms){return new Promise(r=>setTimeout(r,ms));}
function runtimeMessage(message){return new Promise((resolve,reject)=>{chrome.runtime.sendMessage(message,response=>{if(chrome.runtime.lastError)reject(new Error(chrome.runtime.lastError.message));else resolve(response);});});}
async function getConfig(){return chrome.storage.local.get({baseUrl:'',pairCode:'',privateKey:null,enabled:true});}
function isCurrentChat(){return activeTab&&document.visibilityState==='visible'&&(location.hostname.endsWith('chatgpt.com')||location.hostname.endsWith('openai.com'));}
function visible(el){return !!el&&el.getClientRects().length>0&&getComputedStyle(el).visibility!=='hidden'&&getComputedStyle(el).display!=='none';}
async function findUploadInput(){
  let inputs=[...document.querySelectorAll('input[type=file]')];
  let input=inputs.find(e=>{const a=(e.getAttribute('accept')||'').toLowerCase();return !a||a.includes('image')||a.includes('*');});
  if(input)return input;
  const buttons=[...document.querySelectorAll('button,[role=button]')].filter(visible);
  const btn=buttons.find(b=>{const t=((b.getAttribute('aria-label')||'')+' '+(b.getAttribute('data-testid')||'')+' '+(b.textContent||'')).toLowerCase();return /attach|upload|add file/.test(t);});
  if(btn)btn.click();
  const deadline=Date.now()+1500;
  while(Date.now()<deadline){
    inputs=[...document.querySelectorAll('input[type=file]')];
    input=inputs.find(e=>{const a=(e.getAttribute('accept')||'').toLowerCase();return !a||a.includes('image')||a.includes('*');});
    if(input)return input;
    await sleep(25);
  }
  return null;
}
async function attachBlob(buffer,mime,name){
  const blob=new Blob([buffer],{type:mime||'image/jpeg'});const file=new File([blob],name||'ai-snap.jpg',{type:blob.type});
  const input=await findUploadInput();if(!input)throw new Error('ChatGPT upload input not found');
  const transfer=new DataTransfer();transfer.items.add(file);const proto=Object.getPrototypeOf(input);const setter=Object.getOwnPropertyDescriptor(proto,'files')?.set;
  if(setter)setter.call(input,transfer.files);else input.files=transfer.files;
  input.dispatchEvent(new Event('input',{bubbles:true,composed:true}));input.dispatchEvent(new Event('change',{bubbles:true,composed:true}));return true;
}
async function fetchFileThroughExtension(url){
  for(let attempt=0;attempt<5;attempt++){
    try{const r=await runtimeMessage({type:'AI_SNAP_FETCH_FILE',url});if(r?.ok)return r;if(r?.status===404){await sleep(150);continue}return r||{ok:false,error:'No response'};}catch(e){if(attempt===4)throw e;await sleep(150);}
  }
  return {ok:false,status:404,error:'File not available yet'};
}
async function deliver(name){
  if(!isCurrentChat()||processing.has(name))return false;processing.add(name);
  try{
    const c=await getConfig(),base=(c.baseUrl||'').replace(/\/$/,'');
    if(!c.enabled||!base||!c.pairCode||!c.privateKey)throw new Error('Secure pairing is not configured.');
    const url=`${base}/api/file/${encodeURIComponent(name)}?code=${encodeURIComponent(c.pairCode)}`;
    const r=await fetchFileThroughExtension(url);if(!r.ok)throw new Error(r.status?`Could not download encrypted image (${r.status}).`:(r.error||'Could not download encrypted image.'));
    const iv=r.headers?.['X-AI-Snap-IV'],wrapped=r.headers?.['X-AI-Snap-Key'],mime=r.headers?.['X-AI-Snap-Mime']||'image/jpeg',original=r.headers?.['X-AI-Snap-Name']||'ai-snap.jpg';
    if(!iv||!wrapped)throw new Error('Encrypted metadata is missing.');
    const encrypted=fromBase64(r.data),privateKey=await crypto.subtle.importKey('jwk',c.privateKey,{name:'RSA-OAEP',hash:'SHA-256'},false,['decrypt']);
    const rawAes=await crypto.subtle.decrypt({name:'RSA-OAEP'},privateKey,fromB64url(wrapped));const aesKey=await crypto.subtle.importKey('raw',rawAes,{name:'AES-GCM'},false,['decrypt']);
    const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:fromB64url(iv)},aesKey,encrypted);await attachBlob(plain,mime,original);
    runtimeMessage({type:'AI_SNAP_ACK',url:`${base}/api/ack?code=${encodeURIComponent(c.pairCode)}`,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})}).catch(()=>{});return true;
  }catch(e){console.error('AI Snap:',e);return false}finally{processing.delete(name)}
}
async function checkPending(){
  if(!isCurrentChat()||pendingCheckInFlight)return;pendingCheckInFlight=true;
  try{const c=await getConfig(),base=(c.baseUrl||'').replace(/\/$/,'');if(!c.enabled||!base||!c.pairCode||!c.privateKey)return;
    const r=await runtimeMessage({type:'AI_SNAP_FETCH_PENDING',url:`${base}/api/pending?code=${encodeURIComponent(c.pairCode)}`});if(!r?.ok)return;const d=JSON.parse(r.text||'{}');
    for(const f of(Array.isArray(d.files)?d.files:[]))await deliver(f.name);
  }catch(_){}finally{pendingCheckInFlight=false}
}
function startPolling(){if(pollTimer)clearInterval(pollTimer);pollTimer=setInterval(()=>{if(isCurrentChat())checkPending()},600);checkPending();}
function connectEvents(){
  if(eventSource){eventSource.close();eventSource=null}if(reconnectTimer)clearTimeout(reconnectTimer);
  getConfig().then(c=>{const base=(c.baseUrl||'').replace(/\/$/,'');if(!c.enabled||!base||!c.pairCode||!c.privateKey)return;
    try{eventSource=new EventSource(`${base}/api/events?code=${encodeURIComponent(c.pairCode)}`);eventSource.onmessage=e=>{try{const d=JSON.parse(e.data);if(d.name&&isCurrentChat())deliver(d.name)}catch(_){}};eventSource.onerror=()=>{if(eventSource){eventSource.close();eventSource=null}reconnectTimer=setTimeout(connectEvents,1000)}}catch(_){reconnectTimer=setTimeout(connectEvents,1000)}
  });
}
chrome.runtime.onMessage.addListener(message=>{if(message?.type==='AI_SNAP_ACTIVE_STATE'){activeTab=!!message.active;if(activeTab)checkPending();}});
async function init(){try{const r=await chrome.runtime.sendMessage({type:'AI_SNAP_GET_ACTIVE_STATE'});activeTab=!!r?.active}catch(_){activeTab=document.visibilityState==='visible'}startPolling();connectEvents();}
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible'){checkPending();connectEvents()}});
new MutationObserver(()=>{if(activeTab&&document.visibilityState==='visible')checkPending()}).observe(document.documentElement,{childList:true,subtree:true});
init();

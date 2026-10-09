async function notifyActiveTab(){try{const [active]=await chrome.tabs.query({active:true,lastFocusedWindow:true});const tabs=await chrome.tabs.query({});await Promise.all(tabs.filter(t=>Number.isInteger(t.id)).map(t=>chrome.tabs.sendMessage(t.id,{type:'AI_SNAP_ACTIVE_STATE',active:t.id===active?.id}).catch(()=>{})));}catch(_) {}}
async function fetchJson(url){const r=await fetch(url,{cache:'no-store'});const text=await r.text();let json=null;try{json=JSON.parse(text)}catch(_){}return{ok:r.ok,status:r.status,json,text}}
function arrayBufferToBase64(buffer){const bytes=new Uint8Array(buffer);let binary='';const chunk=0x8000;for(let i=0;i<bytes.length;i+=chunk){binary+=String.fromCharCode(...bytes.subarray(i,Math.min(i+chunk,bytes.length)));}return btoa(binary);}
chrome.runtime.onInstalled.addListener(async()=>{await chrome.storage.local.set({enabled:true});notifyActiveTab();});
chrome.tabs.onActivated.addListener(()=>notifyActiveTab());
chrome.windows.onFocusChanged.addListener(()=>notifyActiveTab());
function historyDb(){return new Promise((resolve,reject)=>{const req=indexedDB.open('orami-history',1);req.onupgradeneeded=()=>{const db=req.result;if(!db.objectStoreNames.contains('files'))db.createObjectStore('files',{keyPath:'id'});};req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error||new Error('History database unavailable'));});}
async function saveHistoryItem(item){if(typeof item?.dataB64==='string'){const raw=atob(item.dataB64),bytes=new Uint8Array(raw.length);for(let i=0;i<raw.length;i++)bytes[i]=raw.charCodeAt(i);item={...item,data:bytes.buffer};delete item.dataB64;}const db=await historyDb();let duplicate=false;try{await new Promise((resolve,reject)=>{const tx=db.transaction('files','readwrite'),store=tx.objectStore('files'),req=store.get(item.id);req.onsuccess=()=>{if(req.result){duplicate=true;return;}store.put(item);};req.onerror=()=>reject(req.error||new Error('History lookup failed'));tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error||new Error('History save failed'));tx.onabort=()=>reject(tx.error||new Error('History save aborted'));});if(!duplicate)await new Promise((resolve,reject)=>{const tx=db.transaction('files','readwrite'),store=tx.objectStore('files'),req=store.getAll();req.onsuccess=()=>{const rows=(req.result||[]).sort((a,b)=>(b.createdAt||0)-(a.createdAt||0));let bytes=0;const keep=new Set();for(const row of rows){if(Date.now()-(row.createdAt||0)>7*24*60*60*1000)continue;const size=row.data?.byteLength||0;if(keep.size<100&&bytes+size<=150*1024*1024){keep.add(row.id);bytes+=size;}}const del=db.transaction('files','readwrite'),s=del.objectStore('files');for(const row of rows)if(!keep.has(row.id))s.delete(row.id);del.oncomplete=resolve;del.onerror=()=>reject(del.error);};req.onerror=()=>reject(req.error);});return {ok:true,duplicate};}finally{db.close();}}
chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{
  if(message?.type==='ORAMI_SAVE_HISTORY'){saveHistoryItem(message.item).then(result=>sendResponse(result)).catch(e=>sendResponse({ok:false,error:e?.message||'History save failed'}));return true;}
  if(message?.type==='AI_SNAP_GET_ACTIVE_STATE'){chrome.tabs.query({active:true,lastFocusedWindow:true}).then(([tab])=>sendResponse({active:!!sender.tab?.id&&sender.tab.id===tab?.id})).catch(()=>sendResponse({active:false}));return true;}
  if(message?.type==='AI_SNAP_FETCH_FILE'||message?.type==='AI_SNAP_FETCH_PENDING'||message?.type==='AI_SNAP_ACK'){
    (async()=>{try{
      if(message.type==='AI_SNAP_FETCH_FILE'){
        // Fetch metadata independently first. This avoids relying on custom response
        // headers being preserved through every browser/network layer.
        let meta=null;
        if(message.metaUrl){try{meta=await fetchJson(message.metaUrl);}catch(_){} }
        const r=await fetch(message.url,{method:'GET',cache:'no-store'});
        const data=await r.arrayBuffer();
        const headers={};
        for(const name of ['X-AI-Snap-IV','X-AI-Snap-Key','X-AI-Snap-Mime','X-AI-Snap-Name'])headers[name]=r.headers.get(name)||'';
        const eventMeta=message.eventMeta||{};
        if(meta?.ok&&meta.json?.ok){headers['X-AI-Snap-IV']=meta.json.iv||headers['X-AI-Snap-IV'];headers['X-AI-Snap-Key']=meta.json.wrappedKey||headers['X-AI-Snap-Key'];headers['X-AI-Snap-Mime']=meta.json.mime||headers['X-AI-Snap-Mime'];headers['X-AI-Snap-Name']=meta.json.originalName||headers['X-AI-Snap-Name'];}
        if(!headers['X-AI-Snap-IV']&&eventMeta.iv)headers['X-AI-Snap-IV']=eventMeta.iv;
        if(!headers['X-AI-Snap-Key']&&eventMeta.wrappedKey)headers['X-AI-Snap-Key']=eventMeta.wrappedKey;
        if(!headers['X-AI-Snap-Mime']&&eventMeta.mime)headers['X-AI-Snap-Mime']=eventMeta.mime;
        if(!headers['X-AI-Snap-Name']&&eventMeta.originalName)headers['X-AI-Snap-Name']=eventMeta.originalName;
        sendResponse({ok:r.ok,status:r.status,headers,dataB64:arrayBufferToBase64(data)});
      }else{
        const r=await fetch(message.url,{method:message.method||'GET',headers:message.headers||{},body:message.body,cache:'no-store'});const text=await r.text();sendResponse({ok:r.ok,status:r.status,text});
      }
    }catch(error){sendResponse({ok:false,error:error?.message||'Network request failed'});}})();return true;
  }
});

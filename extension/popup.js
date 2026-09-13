const $ = id => document.getElementById(id);
const baseInput=$('baseUrl'), saveButton=$('save'), pairButton=$('pair'), newPairButton=$('newPair'), copyButton=$('copy'), clearPair=$('clearPair');
const status=$('status'), pairBox=$('pairBox'), codeInput=$('code'), mobileUrl=$('mobileUrl'), qr=$('qr');
function setStatus(message,ok=false){status.textContent=message;status.className=ok?'ok':'bad'}
async function getConfig(){return chrome.storage.local.get({baseUrl:'',pairCode:'',enabled:true,privateKey:null,publicKey:null})}
async function setConfig(v){await chrome.storage.local.set(v)}
async function createKeyPair(){
  const keys=await crypto.subtle.generateKey({name:'RSA-OAEP',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['encrypt','decrypt']);
  return {publicKey:await crypto.subtle.exportKey('jwk',keys.publicKey),privateKey:await crypto.subtle.exportKey('jwk',keys.privateKey)};
}
function showPairing(base,code){
  const clean=base.replace(/\/$/,'');
  codeInput.value=code;
  const link=`${clean}/mobile/?code=${encodeURIComponent(code)}`;
  mobileUrl.textContent=link;
  qr.src=`${clean}/api/pair/qr?code=${encodeURIComponent(code)}&t=${Date.now()}`;
  qr.onerror=()=>{qr.alt='QR unavailable — use the phone link below';qr.style.display='none'};
  qr.onload=()=>{qr.style.display='block'};
  pairBox.classList.add('show');
}
async function createPairing(){
  const base=baseInput.value.trim().replace(/\/$/,'');
  if(!base){setStatus('Enter your cloud server URL first.');baseInput.focus();return}
  setStatus('Creating secure pairing…');
  try{
    const keys=await createKeyPair();
    const r=await fetch(`${base}/api/pair/create`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({publicKey:keys.publicKey}),cache:'no-store'});
    const d=await r.json();
    if(!r.ok||!d.ok||!d.e2ee)throw new Error(d.error||'Could not create pairing');
    await setConfig({baseUrl:base,pairCode:d.code,enabled:true,privateKey:keys.privateKey,publicKey:keys.publicKey});
    showPairing(base,d.code);setStatus('✓ New secure pairing created. Scan the QR code or enter the code.',true);
  }catch(e){console.error(e);setStatus(e.message||'Could not create secure pairing. Check the server URL.')}
}
(async()=>{
  const c=await getConfig();baseInput.value=c.baseUrl||'';
  if(c.baseUrl&&c.pairCode&&c.privateKey){
    try{
      const base=c.baseUrl.replace(/\/$/,'');const r=await fetch(`${base}/api/pair/status?code=${encodeURIComponent(c.pairCode)}`,{cache:'no-store'});const d=await r.json();
      if(r.ok&&d.ok&&d.e2ee)showPairing(base,c.pairCode),setStatus('✓ E2EE pairing is active.',true);
      else{await chrome.storage.local.remove(['pairCode','privateKey','publicKey']);setStatus('Pairing expired. Create a new one.')}
    }catch(_){setStatus('Server is unreachable. The saved pairing was kept.')}
  }
})();
saveButton.addEventListener('click',async()=>{const base=baseInput.value.trim().replace(/\/$/,'');if(!/^https?:\/\//i.test(base)){setStatus('Use a full URL starting with https://');return}try{const r=await fetch(`${base}/health`,{cache:'no-store'}),d=await r.json();if(!r.ok||!d.ok)throw 0;await setConfig({baseUrl:base});setStatus('✓ Server saved and reachable.',true)}catch(_){setStatus('Could not reach that server URL.')}});
pairButton.addEventListener('click',createPairing);newPairButton.addEventListener('click',createPairing);
copyButton.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(mobileUrl.textContent);setStatus('✓ Phone link copied.',true)}catch(_){setStatus('Copy failed — select the link manually.')}});
clearPair.addEventListener('click',async()=>{await chrome.storage.local.remove(['pairCode','privateKey','publicKey']);pairBox.classList.remove('show');codeInput.value='';mobileUrl.textContent='';qr.removeAttribute('src');setStatus('Pairing cleared. Create a new secure pairing.',true)});

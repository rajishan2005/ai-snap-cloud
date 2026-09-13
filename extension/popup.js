const baseInput = document.getElementById('baseUrl');
const saveButton = document.getElementById('save');
const pairButton = document.getElementById('pair');
const newPairButton = document.getElementById('newPair');
const copyButton = document.getElementById('copy');
const status = document.getElementById('status');
const pairBox = document.getElementById('pairBox');
const codeInput = document.getElementById('code');
const mobileUrl = document.getElementById('mobileUrl');

function setStatus(message, ok = false) {
  status.textContent = message;
  status.className = ok ? 'ok' : 'bad';
}
async function getConfig() { return chrome.storage.local.get({ baseUrl: '', pairCode: '', enabled: true, privateKey: null, publicKey: null }); }
async function setConfig(values) { await chrome.storage.local.set(values); }

async function createKeyPair() {
  const keys = await crypto.subtle.generateKey({name:'RSA-OAEP',modulusLength:2048,publicExponent:new Uint8Array([1,0,1]),hash:'SHA-256'},true,['encrypt','decrypt']);
  const publicKey = await crypto.subtle.exportKey('jwk', keys.publicKey);
  const privateKey = await crypto.subtle.exportKey('jwk', keys.privateKey);
  return {publicKey, privateKey};
}

async function createPairing() {
  const base = baseInput.value.trim().replace(/\/$/, '');
  if (!base) { setStatus('Enter your cloud server URL first.'); baseInput.focus(); return; }
  setStatus('Creating secure pairing…');
  try {
    const keys = await createKeyPair();
    const response = await fetch(`${base}/api/pair/create`, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({publicKey:keys.publicKey}), cache:'no-store' });
    const data = await response.json();
    if (!response.ok || !data.ok || !data.e2ee) throw new Error(data.error || 'Could not create pairing');
    await setConfig({ baseUrl:base, pairCode:data.code, enabled:true, privateKey:keys.privateKey, publicKey:keys.publicKey });
    codeInput.value = data.code;
    mobileUrl.textContent = data.mobileUrl;
    pairBox.classList.add('show');
    setStatus('✓ Secure pairing created. Your private key stays on this PC.', true);
  } catch (error) { console.error(error); setStatus('Could not create secure pairing. Check the server URL.'); }
}

(async function init() {
  const config = await getConfig();
  baseInput.value = config.baseUrl || '';
  if (config.baseUrl && config.pairCode && config.privateKey) {
    try {
      const r = await fetch(`${config.baseUrl.replace(/\/$/, '')}/api/pair/status?code=${encodeURIComponent(config.pairCode)}`, { cache:'no-store' });
      const data = await r.json();
      if (r.ok && data.ok && data.e2ee) {
        codeInput.value = config.pairCode;
        mobileUrl.textContent = `${config.baseUrl.replace(/\/$/, '')}/mobile/?code=${config.pairCode}`;
        pairBox.classList.add('show');
        setStatus('✓ E2EE pairing is active.', true);
      }
    } catch (_) {}
  }
})();

saveButton.addEventListener('click', async () => {
  const base = baseInput.value.trim().replace(/\/$/, '');
  if (!/^https?:\/\//i.test(base)) { setStatus('Use a full URL starting with https://'); return; }
  try {
    const r = await fetch(`${base}/health`, {cache:'no-store'}); const data = await r.json();
    if (!r.ok || !data.ok) throw new Error();
    await setConfig({baseUrl:base}); setStatus('✓ Server saved and reachable.', true);
  } catch (_) { setStatus('Could not reach that server URL.'); }
});
pairButton.addEventListener('click', createPairing);
newPairButton.addEventListener('click', createPairing);
copyButton.addEventListener('click', async () => { try { await navigator.clipboard.writeText(mobileUrl.textContent); setStatus('✓ Phone link copied.', true); } catch (_) { setStatus('Copy failed — long-press/select the link instead.'); } });

let eventSource = null;
let processing = new Set();

function fromB64url(value) {
  const s = value.replace(/-/g,'+').replace(/_/g,'/') + '='.repeat((4 - value.length % 4) % 4);
  const raw = atob(s);
  return Uint8Array.from(raw, c => c.charCodeAt(0));
}

async function getConfig() {
  return chrome.storage.local.get({baseUrl:'', pairCode:'', privateKey:null, enabled:true});
}

async function decryptFile(url, privateKeyJwk, ivB64, wrappedKeyB64) {
  const privateKey = await crypto.subtle.importKey('jwk', privateKeyJwk, {name:'RSA-OAEP',hash:'SHA-256'}, false, ['decrypt']);
  const rawAes = await crypto.subtle.decrypt({name:'RSA-OAEP'}, privateKey, fromB64url(wrappedKeyB64));
  const aesKey = await crypto.subtle.importKey('raw', rawAes, {name:'AES-GCM'}, false, ['decrypt']);
  const encrypted = await (await fetch(url, {cache:'no-store'})).arrayBuffer();
  return crypto.subtle.decrypt({name:'AES-GCM',iv:fromB64url(ivB64)}, aesKey, encrypted);
}

async function attachBlob(plainBuffer, mime, name) {
  const blob = new Blob([plainBuffer], {type:mime || 'image/jpeg'});
  const file = new File([blob], name || 'ai-snap.jpg', {type:blob.type});
  const inputs = [...document.querySelectorAll('input[type="file"]')];
  const input = inputs.find(element => {
    const accept = (element.getAttribute('accept') || '').toLowerCase();
    return !accept || accept.includes('image') || accept.includes('*');
  });
  if (input) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', {bubbles:true}));
    input.dispatchEvent(new Event('input', {bubbles:true}));
    return true;
  }
  try {
    await navigator.clipboard.write([new ClipboardItem({[blob.type || 'image/png']:blob})]);
    alert('AI Snap: image copied securely. Press Ctrl+V in ChatGPT to paste it.');
    return true;
  } catch (_) {
    alert('AI Snap received the image, but ChatGPT did not expose an upload input. Open the attachment button and paste with Ctrl+V.');
    return false;
  }
}

async function deliver(name) {
  if (processing.has(name)) return;
  processing.add(name);
  try {
    const config = await getConfig();
    const base = (config.baseUrl || '').replace(/\/$/,'');
    if (!config.enabled || !base || !config.pairCode || !config.privateKey) throw new Error('Secure pairing is not configured.');
    const url = `${base}/api/file/${encodeURIComponent(name)}?code=${encodeURIComponent(config.pairCode)}`;
    const response = await fetch(url, {cache:'no-store'});
    if (!response.ok) throw new Error('Could not download encrypted image.');
    const iv = response.headers.get('X-AI-Snap-IV');
    const wrappedKey = response.headers.get('X-AI-Snap-Key');
    const mime = response.headers.get('X-AI-Snap-Mime') || 'image/jpeg';
    const originalName = response.headers.get('X-AI-Snap-Name') || 'ai-snap.jpg';
    if (!iv || !wrappedKey) throw new Error('Encrypted metadata is missing.');
    const encrypted = await response.arrayBuffer();
    const privateKey = await crypto.subtle.importKey('jwk', config.privateKey, {name:'RSA-OAEP',hash:'SHA-256'}, false, ['decrypt']);
    const rawAes = await crypto.subtle.decrypt({name:'RSA-OAEP'}, privateKey, fromB64url(wrappedKey));
    const aesKey = await crypto.subtle.importKey('raw', rawAes, {name:'AES-GCM'}, false, ['decrypt']);
    const plain = await crypto.subtle.decrypt({name:'AES-GCM',iv:fromB64url(iv)}, aesKey, encrypted);
    const ok = await attachBlob(plain, mime, originalName);
    if (!ok) throw new Error('ChatGPT did not accept the image.');
    await fetch(`${base}/api/ack?code=${encodeURIComponent(config.pairCode)}`, {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name}),cache:'no-store'});
  } catch (error) {
    console.error('AI Snap:', error);
  } finally {
    processing.delete(name);
  }
}

async function checkPending() {
  const config = await getConfig();
  const base = (config.baseUrl || '').replace(/\/$/,'');
  if (!config.enabled || !base || !config.pairCode || !config.privateKey) return;
  try {
    const r = await fetch(`${base}/api/pending?code=${encodeURIComponent(config.pairCode)}`, {cache:'no-store'});
    if (!r.ok) return;
    const d = await r.json();
    for (const file of (Array.isArray(d.files) ? d.files : [])) deliver(file.name);
  } catch (_) {}
}

async function connectEvents() {
  if (eventSource) eventSource.close();
  const config = await getConfig();
  const base = (config.baseUrl || '').replace(/\/$/,'');
  if (!config.enabled || !base || !config.pairCode || !config.privateKey) return;
  eventSource = new EventSource(`${base}/api/events?code=${encodeURIComponent(config.pairCode)}`);
  eventSource.onmessage = event => {
    try { const data = JSON.parse(event.data); if (data.name) deliver(data.name); } catch (_) {}
  };
  eventSource.onerror = () => {
    if (eventSource) eventSource.close();
    setTimeout(connectEvents, 3000);
  };
  await checkPending();
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'AI_SNAP_FILE') {
    deliver(message.name).then(() => sendResponse({ok:true})).catch(error => sendResponse({ok:false,error:error.message}));
    return true;
  }
});

connectEvents();

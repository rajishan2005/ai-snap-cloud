const baseInput = document.getElementById('baseUrl');
const saveButton = document.getElementById('save');
const pairButton = document.getElementById('pair');
const newPairButton = document.getElementById('newPair');
const copyButton = document.getElementById('copy');
const status = document.getElementById('status');
const pairBox = document.getElementById('pairBox');
const codeInput = document.getElementById('code');
const mobileUrl = document.getElementById('mobileUrl');
const qr = document.getElementById('qr');

function setStatus(message, ok = false) {
  status.textContent = message;
  status.className = ok ? 'ok' : 'bad';
}

async function getConfig() {
  return chrome.storage.local.get({ baseUrl: '', pairCode: '', enabled: true });
}

async function setConfig(values) {
  await chrome.storage.local.set(values);
}

function showPairing(base, code) {
  const clean = base.replace(/\/$/, '');
  const url = `${clean}/mobile/?code=${encodeURIComponent(code)}`;
  codeInput.value = code;
  mobileUrl.textContent = url;
  qr.src = `${clean}/api/pair/qr?code=${encodeURIComponent(code)}&t=${Date.now()}`;
  pairBox.classList.add('show');
}

async function createPairing() {
  const base = baseInput.value.trim().replace(/\/$/, '');
  if (!base) {
    setStatus('Enter your cloud server URL first.');
    baseInput.focus();
    return;
  }

  setStatus('Creating pairing…');
  try {
    const response = await fetch(`${base}/api/pair/create`, { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || 'Could not create pairing');

    await setConfig({ baseUrl: base, pairCode: data.code, enabled: true });
    showPairing(base, data.code);
    setStatus('✓ Pairing is active. Scan the QR or enter the code on your phone.', true);
  } catch (error) {
    setStatus('Could not reach the cloud server. Check the URL and try again.');
  }
}

(async function init() {
  const config = await getConfig();
  baseInput.value = config.baseUrl || '';
  if (config.baseUrl && config.pairCode) {
    try {
      const base = config.baseUrl.replace(/\/$/, '');
      const r = await fetch(`${base}/api/pair/status?code=${encodeURIComponent(config.pairCode)}`, { cache: 'no-store' });
      const data = await r.json();
      if (r.ok && data.ok) {
        showPairing(base, config.pairCode);
        setStatus('✓ Pairing is active.', true);
      }
    } catch (_) {}
  }
})();

saveButton.addEventListener('click', async () => {
  const base = baseInput.value.trim().replace(/\/$/, '');
  if (!/^https?:\/\//i.test(base)) {
    setStatus('Use a full URL starting with https://');
    return;
  }
  try {
    const r = await fetch(`${base}/health`, { cache: 'no-store' });
    const data = await r.json();
    if (!r.ok || !data.ok) throw new Error();
    await setConfig({ baseUrl: base });
    setStatus('✓ Server saved and reachable.', true);
  } catch (_) {
    setStatus('Could not reach that server URL.');
  }
});

pairButton.addEventListener('click', createPairing);
newPairButton.addEventListener('click', createPairing);
copyButton.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(mobileUrl.textContent);
    setStatus('✓ Phone link copied.', true);
  } catch (_) {
    setStatus('Copy failed — select the link instead.');
  }
});

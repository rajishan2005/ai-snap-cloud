async function notifyActiveTab() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab?.id) return;
    await chrome.tabs.sendMessage(tab.id, { type: 'AI_SNAP_ACTIVE_STATE', active: true });
  } catch (_) {}
}

function bytesToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  let out = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) out += String.fromCharCode(...bytes.subarray(i, Math.min(i + chunk, bytes.length)));
  return btoa(out);
}

async function fetchJson(url) {
  const r = await fetch(url, { cache: 'no-store' });
  const text = await r.text();
  let json = null;
  try { json = JSON.parse(text); } catch (_) {}
  return { ok: r.ok, status: r.status, json, text };
}

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({ enabled: true });
  notifyActiveTab();
});
chrome.tabs.onActivated.addListener(() => notifyActiveTab());
chrome.windows.onFocusChanged.addListener(() => notifyActiveTab());

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'AI_SNAP_GET_ACTIVE_STATE') {
    chrome.tabs.query({ active: true, lastFocusedWindow: true })
      .then(([tab]) => sendResponse({ active: !!sender.tab?.id && sender.tab.id === tab?.id }))
      .catch(() => sendResponse({ active: false }));
    return true;
  }

  if (message?.type === 'AI_SNAP_FETCH_FILE' || message?.type === 'AI_SNAP_FETCH_PENDING' || message?.type === 'AI_SNAP_ACK') {
    (async () => {
      try {
        const r = await fetch(message.url, {
          method: message.method || 'GET',
          headers: message.headers || {},
          body: message.body,
          cache: 'no-store'
        });
        if (message.type === 'AI_SNAP_FETCH_FILE') {
          const data = await r.arrayBuffer();
          const headers = {};
          for (const name of ['X-AI-Snap-IV','X-AI-Snap-Key','X-AI-Snap-Mime','X-AI-Snap-Name']) headers[name] = r.headers.get(name) || '';

          // Fast path: SSE supplied the encrypted metadata with the event, so no
          // second request is needed. Keep the metadata endpoint as a fallback.
          const eventMeta = message.eventMeta || {};
          if (!headers['X-AI-Snap-IV'] && eventMeta.iv) headers['X-AI-Snap-IV'] = eventMeta.iv;
          if (!headers['X-AI-Snap-Key'] && eventMeta.wrappedKey) headers['X-AI-Snap-Key'] = eventMeta.wrappedKey;
          if (!headers['X-AI-Snap-Mime'] && eventMeta.mime) headers['X-AI-Snap-Mime'] = eventMeta.mime;
          if (!headers['X-AI-Snap-Name'] && eventMeta.originalName) headers['X-AI-Snap-Name'] = eventMeta.originalName;

          const hasMeta = !!headers['X-AI-Snap-IV'] && !!headers['X-AI-Snap-Key'];
          if (r.ok && !hasMeta && message.metaUrl) {
            const meta = await fetchJson(message.metaUrl);
            if (meta.ok && meta.json?.ok) {
              headers['X-AI-Snap-IV'] = meta.json.iv || '';
              headers['X-AI-Snap-Key'] = meta.json.wrappedKey || '';
              headers['X-AI-Snap-Mime'] = meta.json.mime || '';
              headers['X-AI-Snap-Name'] = meta.json.originalName || '';
            }
          }
          sendResponse({ ok: r.ok, status: r.status, headers, data: bytesToBase64(data) });
        } else {
          const text = await r.text();
          sendResponse({ ok: r.ok, status: r.status, text });
        }
      } catch (error) {
        sendResponse({ ok: false, error: error?.message || 'Network request failed' });
      }
    })();
    return true;
  }
});

const DEFAULT_BASE = '';
const POLL_MS = 1200;
const seen = new Set();

async function getConfig() {
  return chrome.storage.local.get({ baseUrl: DEFAULT_BASE, pairCode: '', enabled: true });
}

async function poll() {
  const config = await getConfig();
  const base = (config.baseUrl || '').replace(/\/$/, '');
  if (!config.enabled || !base || !config.pairCode) return;

  try {
    const response = await fetch(`${base}/api/pending?code=${encodeURIComponent(config.pairCode)}`, { cache: 'no-store' });
    if (!response.ok) return;

    const data = await response.json();
    const files = Array.isArray(data.files) ? data.files : [];
    if (!files.length) return;

    const tabs = await chrome.tabs.query({ url: ['https://chatgpt.com/*', 'https://chat.openai.com/*'] });
    if (!tabs.length) return;
    const tab = tabs[0];

    for (const file of files) {
      if (seen.has(file.name)) continue;
      seen.add(file.name);
      try {
        const result = await chrome.tabs.sendMessage(tab.id, {
          type: 'AI_SNAP_FILE',
          url: `${base}/api/file/${encodeURIComponent(file.name)}?code=${encodeURIComponent(config.pairCode)}`,
          name: file.name,
        });
        if (result?.ok) {
          await fetch(`${base}/api/ack?code=${encodeURIComponent(config.pairCode)}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: file.name }),
          });
        } else {
          seen.delete(file.name);
        }
      } catch (error) {
        seen.delete(file.name);
      }
    }
  } catch (error) {
    // Cloud relay may be asleep/offline; retry on next poll.
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({ enabled: true });
});

setInterval(poll, POLL_MS);
poll();

async function notifyActiveTab() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab?.id) return;
    await chrome.tabs.sendMessage(tab.id, { type: 'AI_SNAP_ACTIVE_STATE', active: true });
  } catch (_) {}
}

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.storage.local.set({ enabled: true });
  notifyActiveTab();
});

chrome.tabs.onActivated.addListener(() => notifyActiveTab());
chrome.windows.onFocusChanged.addListener(() => notifyActiveTab());

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'AI_SNAP_GET_ACTIVE_STATE') return;
  chrome.tabs.query({ active: true, lastFocusedWindow: true })
    .then(([tab]) => sendResponse({ active: !!sender.tab?.id && sender.tab.id === tab?.id }))
    .catch(() => sendResponse({ active: false }));
  return true;
});

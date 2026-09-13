async function attachImage(url, name) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) throw new Error('Could not download image from AI Snap Cloud.');

  const blob = await response.blob();
  const file = new File([blob], name, { type: blob.type || 'image/jpeg' });

  const inputs = [...document.querySelectorAll('input[type="file"]')];
  const input = inputs.find((element) => {
    const accept = (element.getAttribute('accept') || '').toLowerCase();
    return !accept || accept.includes('image') || accept.includes('*');
  });

  if (input) {
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    input.dispatchEvent(new Event('change', { bubbles: true }));
    input.dispatchEvent(new Event('input', { bubbles: true }));
    return true;
  }

  try {
    await navigator.clipboard.write([
      new ClipboardItem({ [blob.type || 'image/png']: blob })
    ]);
    alert('AI Snap: image copied. Press Ctrl+V in ChatGPT to paste it.');
  } catch (error) {
    alert('AI Snap received the image, but ChatGPT did not expose an upload input. Open the attachment button and paste with Ctrl+V.');
  }
  return false;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type !== 'AI_SNAP_FILE') return;
  attachImage(message.url, message.name)
    .then((ok) => sendResponse({ ok }))
    .catch((error) => {
      console.error('AI Snap:', error);
      sendResponse({ ok: false, error: error.message });
    });
  return true;
});

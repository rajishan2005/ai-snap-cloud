# AI Snap Cloud Test Build

This version replaces the LAN-only Python server with a small HTTPS-ready cloud relay suitable for a friend/public beta test.

## Architecture

Phone → cloud relay → Chrome extension → ChatGPT

The cloud creates a short-lived 6-character pairing code. The extension creates the code, and the phone opens the generated mobile link. Uploaded images are isolated per code and automatically cleaned up after a short period.

## Deploy to Render

1. Create a new GitHub repository and upload this folder.
2. In Render, choose **New + → Blueprint** and select the repo.
3. Render reads `render.yaml` and creates the web service.
4. Copy the resulting HTTPS URL, e.g. `https://ai-snap-cloud.onrender.com`.
5. In the extension popup, paste that URL as **Cloud server URL**.
6. Click **Create Pairing**. The extension shows a mobile link and 6-character code.
7. Open the mobile link on the phone and take a photo.

## Important beta limitations

- Render's free service may sleep when idle, so the first request can be slow.
- Temporary image storage is on the service filesystem; a service restart can clear queued images.
- Pairing codes expire after 30 minutes.
- Images are removed after 10 minutes or after the extension acknowledges receipt.
- This is a test/beta relay, not production-grade storage/auth infrastructure.

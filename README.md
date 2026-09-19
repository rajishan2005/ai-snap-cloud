# Orami

**Orami** is a fast, end-to-end encrypted phone-to-PC image bridge for AI workflows.

Take or choose an image on your phone and send it to the ChatGPT tab currently open on your PC.

## How it works

Phone → Orami cloud relay → Orami Chrome extension → ChatGPT

Images are encrypted on the phone with AES-GCM. The AES key is wrapped with the PC's RSA-OAEP public key. The relay stores and forwards only the encrypted image and metadata; decryption happens locally in the Chrome extension.

## Current flow

1. Open the Orami Chrome extension on your PC.
2. Create a secure pairing.
3. Scan the QR code or open the generated mobile link.
4. Take a photo or choose one from the gallery.
5. Orami encrypts the image on the phone.
6. The encrypted image is relayed to the PC.
7. The extension decrypts it locally and attaches it to the currently open ChatGPT chat.

## Project structure

- `extension/` — current Manifest V3 Chrome extension
- `mobile/` — mobile uploader web app
- `server/` — Python relay server
- `data/` — temporary encrypted files

## Deployment

The relay is designed to run on Railway.

Railway provides the `PORT` environment variable automatically. You can optionally set:

`PUBLIC_BASE_URL=https://your-app.up.railway.app`

Health check:

`https://YOUR-RAILWAY-DOMAIN/health`

The health response reports the Orami service name and E2EE status.

## Security and lifecycle

- Pairing codes expire after 30 minutes.
- Uploaded files are removed after delivery acknowledgement or after 10 minutes.
- Maximum encrypted upload size is 25 MB.
- The relay does not need the plaintext image to deliver it.
- A new pairing revokes the previous pairing.

## Beta limitations

- Images are temporarily stored on the relay filesystem.
- A Railway service restart/redeploy can clear queued images.
- Automatic ChatGPT attachment relies on the ChatGPT web page DOM and browser extension APIs.
- This is a beta relay architecture, not production-grade persistent storage.

## Brand

**Orami**  
*Snap on your phone. Continue on your PC.*

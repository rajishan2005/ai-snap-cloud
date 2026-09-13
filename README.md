# AI Snap Cloud — Railway Test Build

This is the cloud relay version of AI Snap, prepared for Railway.

## Architecture

Phone → Railway cloud relay → Chrome extension → ChatGPT

The cloud creates a short-lived 6-character pairing code. The Chrome extension creates the pairing, and the phone opens the generated mobile link.

## Deploy on Railway

1. Push this folder to a new GitHub repository.
2. In Railway, create a new project and choose **Deploy from GitHub Repo**.
3. Select the repository.
4. Railway will detect the Python app and use `railway.toml`.
5. Wait for the deployment to become healthy.
6. Open the service's public URL, for example:
   `https://your-app.up.railway.app/health`
7. The response should contain:
   `{"ok":true,"name":"AI Snap Cloud",...}`

## Configure the Chrome extension

Open the extension popup and put your Railway public URL into **Cloud server URL**.

Example:

`https://your-app.up.railway.app`

Click **Save Server**, then **Create Pairing**.

The extension will show a mobile URL such as:

`https://your-app.up.railway.app/mobile/?code=ABC123`

Open that on the phone and test **Take Photo** and **Choose from Gallery**.

## Railway settings

Railway provides the `PORT` environment variable automatically. The server listens on:

`0.0.0.0:$PORT`

The public pairing URL is reconstructed from Railway's forwarded HTTPS headers. You can optionally set:

`PUBLIC_BASE_URL=https://your-app.up.railway.app`

if you later add a custom domain.

## Beta limitations

- Image files are stored on the service filesystem temporarily. A service restart/redeploy can clear queued images.
- Pairing codes expire after 30 minutes.
- Images are removed after 10 minutes or after delivery acknowledgement.
- This is a private beta relay, not production-grade storage/authentication.
- The Chrome extension still relies on the ChatGPT web page DOM for automatic attachment.

## Quick health test

After deploying, open:

`https://YOUR-RAILWAY-DOMAIN/health`

You should see a JSON response with `"ok": true`.

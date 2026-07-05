# Kodi Add-ons

## Installation

Install the repository add-on once, then install add-ons from Kodi normally. This is not the official Kodi repository.

This repository is published through:

```text
https://raw.githubusercontent.com/skibish/kodi-addons/main/zips/
```

1. Open `https://github.com/skibish/kodi-addons/tree/main/zips/repository.skibish.kodi` and download `repository.skibish.kodi-0.0.1.zip`.

2. Transfer the ZIP file to your Kodi device.

3. In Kodi, go to **Settings** **> Add-ons** **> Install from zip file**.

4. Select `repository.skibish.kodi-0.0.1.zip` and install it.

5. Go to **Settings** **> Add-ons** **> Install from repository**.

6. Open **Skibish Kodi Add-ons**.

7. Install **Immich Screensaver**.

After that, Kodi can offer updates for the add-on from this third-party repository using the raw GitHub URL above.

## Repository URL

Kodi uses this repository backend URL:

```text
https://raw.githubusercontent.com/skibish/kodi-addons/main/zips/
```

## Available add-ons

### Immich Screensaver

A Kodi screensaver add-on that connects to your [Immich](https://immich.app) server and displays a random slideshow of your photos and muted videos with crossfade transitions.

#### Features

- Displays random photos from your Immich library
- Plays videos muted (no sound) as part of the screensaver
- Uses Immich-provided thumbnails for display
- Soft crossfade transitions between assets
- No local downloads — media is streamed directly from Immich
- Configurable Immich server URL and API key
- Configurable photo duration, video duration, batch size, and thumbnail quality

#### Requirements

- **Kodi 21 (Omega)** or later — tested with LibreELEC 12.2.1 (Kodi 21.3)
- **Immich 3.0.1** or later
- An Immich API key with `asset.read` and `asset.view` permissions

#### Activating the screensaver

1. In Kodi, go to **Settings** **> Interface** **> Screensaver**.
2. Set **Screensaver mode** to **Immich Screensaver**.
3. Click **Settings** (next to the screensaver mode) to configure your Immich connection.

#### Configuration

Open the add-on settings via **Settings > Interface > Screensaver > Settings**:

| Setting | Description | Default |
|---|---|---|
| Immich Server URL | URL of your Immich server (with or without `/api`) | `http://localhost:2283` |
| Immich API Key | Your Immich API key | (empty) |
| Verify SSL certificate | Disable if using self-signed certificates | On |
| Photo display duration (seconds) | Seconds each photo is shown | 8 |
| Include videos | Show muted videos in the screensaver | On |
| Video mode | `poster_only` shows video thumbnails only; `playback` plays muted videos | `poster_only` |
| Play full video length | If enabled, plays entire video instead of capping at max duration | Off |
| Encoded videos only | If enabled, only plays videos that Immich has already transcoded (smoother playback) | On |
| Enable audio during video playback | If enabled, audio is not muted during video playback | Off |
| Video prewarm size (MB) | How many MB to pre-download before starting video playback (reduces stalls) | 8 |
| Max video playback duration (seconds) | Maximum seconds to play each video (only when Play full video is off) | 30 |
| Number of assets to fetch | How many assets to request per batch | 50 |
| Thumbnail size | Image quality: `preview`, `thumbnail`, or `fullsize` | `preview` |
| Fade transition duration (milliseconds) | Crossfade duration between assets | 1000 |

#### Creating an Immich API key

1. Open your Immich web interface.
2. Go to **User Settings** (click your name/avatar).
3. Scroll to **API Keys**.
4. Click **Create API Key**, give it a name (e.g., "Kodi Screensaver").
5. Copy the generated key and paste it into the add-on settings.

Use a scoped key with `asset.read` and `asset.view`. Broader permissions are not required for this add-on.

#### Immich Server URL examples

All of these work and are normalized automatically:

```
http://192.168.1.10:2283
http://192.168.1.10:2283/
http://192.168.1.10:2283/api
https://immich.mydomain.com
https://immich.mydomain.com/api
```

#### How it works

The add-on uses a dual-entrypoint architecture to work around Kodi's screensaver/player conflict:

1. **Screensaver entry** (`entrypointscreensaver.py`): When Kodi activates the screensaver, this runs first.
   - In `poster_only` mode: runs the photo slideshow directly as a screensaver.
   - In `playback` mode: deactivates the screensaver and relaunches the add-on as a normal script via `RunAddon`, avoiding the Kodi screensaver/player conflict.

2. **Script entry** (`entrypointscript.py`): Runs the full slideshow with video playback as a normal Kodi script (not as a screensaver). This allows `xbmc.Player().play(url, windowed=True)` to work correctly.

3. The add-on calls `POST /api/search/random` on your Immich server (using the `x-api-key` header for authentication) to fetch a batch of random assets.

4. For each photo asset, Kodi loads the Immich thumbnail directly:
   ```
   GET /api/assets/{id}/thumbnail?size=preview&apiKey={key}
   ```

5. For each video asset (in `playback` mode), the add-on shows the video thumbnail poster, then plays the video muted:
   ```
   GET /api/assets/{id}/video/playback?apiKey={key}
   ```

6. Two layered image controls crossfade between assets. A `videowindow` control shows the video when `Player.HasVideo` is true.

7. The slideshow runs in a background thread. When the batch is exhausted, a new random batch is fetched.

8. Any user input stops playback, restores mute state, and closes the window.

#### Authentication method

The add-on uses two authentication methods:

- **API JSON calls** (search/random): uses the `x-api-key` HTTP header (not exposed in URLs).
- **Media URLs** (thumbnails, video playback): uses the `apiKey` query parameter, because Kodi's image and video controls cannot send custom HTTP headers.

This means the API key appears in media URLs. On a private LAN this is usually fine, but be aware it may appear in:
- Immich server access logs
- Reverse proxy (nginx/Caddy) access logs
- Kodi debug logs

If you expose Immich publicly, consider restricting the API key permissions or using a reverse proxy with URL filtering.

#### Troubleshooting

##### Blank screen / nothing shows

- Verify the Immich URL is correct and reachable from your Kodi device.
- Test the URL in a browser: `http://your-immich-url/api/server/ping`
- Check Kodi logs: `System > Settings > System > Logging`, then look at `/storage/.kodi/temp/kodi.log` on LibreELEC.

##### 401 Unauthorized

- The API key is invalid or expired. Generate a new one in Immich User Settings > API Keys.
- Confirm the key includes `asset.read` and `asset.view`.

##### No assets found

- Your Immich library may be empty, or the API key's user has no accessible assets.
- Ensure the key includes `asset.read` and `asset.view`.

##### Videos not playing

- By default, **Video mode** is set to `poster_only`, which shows video thumbnails without playing the actual video. This is the stable default.
- To enable real video playback, set **Video mode** to `playback` in add-on settings.
- In `playback` mode, the add-on deactivates the Kodi screensaver and runs as a normal script to allow video playback via `xbmc.Player().play(url, windowed=False)`.
- **Encoded videos only** is enabled by default. This ensures only Immich-transcoded videos are used, which are typically H.264/AAC MP4 files that Kodi can play smoothly. If disabled, original (potentially large/unsupported) videos may be served.
- If playback still fails, ensure **Include videos** is enabled in add-on settings.
- Check that your Immich server has generated video playbacks (transcoded videos). In Immich, go to Administration > Jobs > Video Conversion and ensure it has run.
- Check Kodi logs for playback errors.
- If you see `stream stalled` warnings in Kodi logs, try increasing Kodi's cache settings: Settings > Services > Caching.

##### SSL / self-signed certificate errors

- If your Immich server uses HTTPS with a self-signed certificate:
  - Disable **Verify SSL certificate** in the add-on settings (affects API calls only).
  - For media URLs (images/videos), Kodi uses its own SSL handling. You may need to add the certificate to your system's CA store, or use HTTP instead of HTTPS.
- On LibreELEC, the system CA store is at `/etc/ssl/certs/`. You can add your certificate there.

##### Photos look low quality

- Change **Thumbnail size** from `preview` to `fullsize` in add-on settings.
- Note: `fullsize` loads larger images and may be slower, especially on slow networks.

## Publishing

This repo is set up for GitHub-based Kodi repository publishing.

- Repository backend URL: `https://raw.githubusercontent.com/skibish/kodi-addons/main/zips/`
- Publish target repo: `https://github.com/skibish/kodi-addons`

Build the repository files with:

```bash
python3 tools/build_release.py
```

That generates:

```text
zips/
  addons.xml
  addons.xml.md5
  screensaver.immich/
    screensaver.immich-0.0.1.zip
  repository.skibish.kodi/
    repository.skibish.kodi-0.0.1.zip
```

Commit the updated `zips/` directory to `skibish/kodi-addons` on branch `main`.

## License

GPL-3.0-only

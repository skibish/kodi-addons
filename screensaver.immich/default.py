import json
import random
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_PATH = ADDON.getAddonInfo('path')

FADE_TIME = 1000
PROP_FADE1 = 'ImmichScreensaver.Fade1'
PROP_FADE2 = 'ImmichScreensaver.Fade2'
PROP_ERROR = 'ImmichScreensaver.Error'

PROP_IMAGES = 'ImmichScreensaver.Images'

HOME = xbmcgui.Window(10000)
LOCK_PROP = '{}.is_locked'.format(ADDON_ID)


def log(msg, level=xbmc.LOGINFO):
    xbmc.log('{}: {}'.format(ADDON_ID, msg), level)


def redact_url(url):
    return url.replace('apiKey=', 'apiKey=[REDACTED]')


class ImmichClient:
    def __init__(self, base_url, api_key, verify_ssl=True):
        self.api_key = api_key
        base = base_url.strip().rstrip('/')
        if base.endswith('/api'):
            base = base[:-4]
        self.base_url = base
        self.api_url = base + '/api'

        self.ssl_context = ssl.create_default_context()
        if not verify_ssl:
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    def _request(self, path, method='GET', data=None):
        url = self.api_url + path
        req = urllib.request.Request(url, method=method)
        req.add_header('x-api-key', self.api_key)
        req.add_header('Accept', 'application/json')
        if data is not None:
            req.add_header('Content-Type', 'application/json')
            req.data = json.dumps(data).encode('utf-8')
        with urllib.request.urlopen(req, context=self.ssl_context, timeout=15) as resp:
            raw = resp.read().decode('utf-8')
            return json.loads(raw)

    def get_random_assets(self, size=50, include_videos=True):
        body = {
            'size': size,
            'withExif': False,
            'withPeople': False,
            'withStacked': False,
        }
        if not include_videos:
            body['type'] = 'IMAGE'
        result = self._request('/search/random', method='POST', data=body)
        return self._parse_assets(result)

    def get_random_assets_by_type(self, size=50, asset_type='IMAGE', is_encoded=None):
        body = {
            'size': size,
            'type': asset_type,
            'withExif': False,
            'withPeople': False,
            'withStacked': False,
        }
        if is_encoded is True:
            body['isEncoded'] = True
        result = self._request('/search/random', method='POST', data=body)
        return self._parse_assets(result)

    def prewarm_video(self, asset_id, bytes_count=8388608):
        import time as _time
        url = self.video_url(asset_id)
        req = urllib.request.Request(url, method='GET')
        req.add_header('x-api-key', self.api_key)
        req.add_header('Range', 'bytes=0-{}'.format(bytes_count - 1))
        start = _time.time()
        try:
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=15) as resp:
                status = resp.status
                content_length = resp.headers.get('Content-Length', '?')
                content_range = resp.headers.get('Content-Range', '?')
                accept_ranges = resp.headers.get('Accept-Ranges', '?')
                content_type = resp.headers.get('Content-Type', '?')
                resp.read()
            elapsed = int((_time.time() - start) * 1000)
            log('Prewarm ok: id={} status={} {}ms req={}KB len={} range={} ranges={} type={}'.format(
                asset_id, status, elapsed, bytes_count // 1024,
                content_length, content_range, accept_ranges, content_type), xbmc.LOGINFO)
            return True
        except Exception as e:
            elapsed = int((_time.time() - start) * 1000)
            log('Prewarm failed: id={} {}ms err={}'.format(asset_id, elapsed, e), xbmc.LOGWARNING)
            return False

    def _parse_assets(self, result):
        if isinstance(result, dict):
            if 'items' in result:
                assets = result['items']
            elif 'assets' in result:
                assets = result['assets']
            else:
                assets = [result]
        elif isinstance(result, list):
            assets = result
        else:
            assets = []
        filtered = []
        for a in assets:
            if not isinstance(a, dict):
                continue
            asset_id = a.get('id')
            asset_type = a.get('type', 'IMAGE')
            if not asset_id:
                continue
            if asset_type not in ('IMAGE', 'VIDEO'):
                continue
            filtered.append(a)
        return filtered

    def thumbnail_url(self, asset_id, size='preview'):
        key = urllib.parse.quote(self.api_key, safe='')
        return '{}/api/assets/{}/thumbnail?size={}&apiKey={}'.format(
            self.base_url, asset_id, size, key
        )

    def video_url(self, asset_id):
        key = urllib.parse.quote(self.api_key, safe='')
        return '{}/api/assets/{}/video/playback?apiKey={}'.format(
            self.base_url, asset_id, key
        )


class PosterScreensaver(xbmcgui.WindowXML):

    class ExitMonitor(xbmc.Monitor):
        def __init__(self, exit_callback):
            super().__init__()
            self.exit_callback = exit_callback

        def onScreensaverDeactivated(self):
            self.exit_callback()

        def onAbort(self):
            self.exit_callback()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.abort = False
        self.closed = False
        self.assets = []
        self.asset_index = 0
        self.current_slot = 0
        self.immich = None
        self.monitor = None

    def onInit(self):
        immich_url = ADDON.getSetting('immich_url')
        api_key = ADDON.getSetting('api_key')
        self.photo_duration = int(ADDON.getSetting('photo_duration_seconds') or 8)
        self.include_videos = ADDON.getSetting('include_videos') == 'true'
        self.batch_size = int(ADDON.getSetting('batch_size') or 50)
        self.thumbnail_size = ADDON.getSetting('thumbnail_size') or 'preview'
        verify_ssl = ADDON.getSetting('verify_ssl') == 'true'

        self.setProperty(PROP_FADE1, '0')
        self.setProperty(PROP_FADE2, '0')
        self.setProperty(PROP_ERROR, 'hide')

        self.monitor = self.ExitMonitor(self._close_screensaver)
        log('PosterScreensaver: running in screensaver mode', xbmc.LOGINFO)

        if not immich_url:
            self._show_error(ADDON.getLocalizedString(30023))
            self._wait_for_exit()
            return
        if not api_key:
            self._show_error(ADDON.getLocalizedString(30024))
            self._wait_for_exit()
            return

        self.immich = ImmichClient(immich_url, api_key, verify_ssl)

        if not self._fetch_assets():
            self._show_error(ADDON.getLocalizedString(30021))
            self._wait_for_exit()
            return

        if not self.assets:
            self._show_error(ADDON.getLocalizedString(30022))
            self._wait_for_exit()
            return

        try:
            self._run_slideshow()
        finally:
            self._close_screensaver()

    def _fetch_assets(self):
        try:
            new_assets = self.immich.get_random_assets(
                size=self.batch_size,
                include_videos=self.include_videos
            )
            if new_assets:
                random.shuffle(new_assets)
                self.assets = new_assets
                self.asset_index = 0
                return True
            return False
        except urllib.error.URLError as e:
            log('Connection error: {}'.format(e), xbmc.LOGERROR)
            return False
        except Exception as e:
            log('Error fetching assets: {}'.format(e), xbmc.LOGERROR)
            return False

    def _get_next_asset(self):
        if self.asset_index >= len(self.assets):
            if not self._fetch_assets():
                return None
        if not self.assets:
            return None
        asset = self.assets[self.asset_index]
        self.asset_index += 1
        return asset

    def _run_slideshow(self):
        while not self.abort:
            asset = self._get_next_asset()
            if asset is None:
                self._wait(2000)
                continue
            asset_id = asset.get('id')
            self._show_photo(asset_id)
            self._wait(self.photo_duration * 1000)

    def _show_photo(self, asset_id):
        url = self.immich.thumbnail_url(asset_id, self.thumbnail_size)
        self._crossfade_image(url)

    def _crossfade_image(self, url):
        next_slot = 1 if self.current_slot == 0 else 0
        if next_slot == 0:
            next_ctrl_id = 100
            next_prop = PROP_FADE1
            old_prop = PROP_FADE2
        else:
            next_ctrl_id = 101
            next_prop = PROP_FADE2
            old_prop = PROP_FADE1

        try:
            ctrl = self.getControl(next_ctrl_id)
            ctrl.setImage(url)
        except Exception as e:
            log('Error setting image: {}'.format(e), xbmc.LOGERROR)
            return

        self.setProperty(next_prop, '0')
        self.setProperty(old_prop, '1')
        self.current_slot = next_slot
        self._wait(FADE_TIME)

    def _wait(self, ms):
        elapsed = 0
        while elapsed < ms and not self.abort:
            if self.monitor and self.monitor.abortRequested():
                self.abort = True
                break
            xbmc.sleep(100)
            elapsed += 100

    def _wait_for_exit(self):
        while not self.abort:
            if self.monitor and self.monitor.abortRequested():
                self.abort = True
                break
            xbmc.sleep(200)
        self._close_screensaver()

    def _close_screensaver(self):
        if self.closed:
            return
        self.closed = True
        self.abort = True
        try:
            self.getControl(100).setImage('')
        except Exception:
            pass
        try:
            self.getControl(101).setImage('')
        except Exception:
            pass
        self.setProperty(PROP_FADE1, '0')
        self.setProperty(PROP_FADE2, '0')
        self.setProperty(PROP_ERROR, 'hide')
        self.close()

    def _show_error(self, message):
        if not message:
            return
        try:
            label = self.getControl(200)
            label.setLabel(message)
        except Exception as e:
            log('Could not get error label control: {}'.format(e), xbmc.LOGERROR)
        self.setProperty(PROP_ERROR, 'show')

    def onAction(self, action):
        self._close_screensaver()


class ImmichPlayer(xbmc.Player):
    def __init__(self):
        super().__init__()
        self.window = None

    def onPlayBackStarted(self):
        log('Player: onPlayBackStarted', xbmc.LOGDEBUG)

    def onAVStarted(self):
        log('Player: onAVStarted', xbmc.LOGDEBUG)
        if self.window:
            self.window.on_av_started()

    def onPlayBackError(self):
        log('Player: onPlayBackError', xbmc.LOGERROR)
        if self.window:
            self.window.on_playback_error()

    def onPlayBackEnded(self):
        log('Player: onPlayBackEnded', xbmc.LOGDEBUG)
        if self.window:
            self.window.on_playback_ended()

    def onPlayBackStopped(self):
        log('Player: onPlayBackStopped', xbmc.LOGDEBUG)
        if self.window:
            self.window.on_playback_stopped()


class PlaybackScreensaver(xbmcgui.WindowXMLDialog):

    class ExitMonitor(xbmc.Monitor):
        def __init__(self, exit_callback):
            super().__init__()
            self.exit_callback = exit_callback

        def onAbort(self):
            self.exit_callback()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.abort = False
        self.closed = False
        self.assets = []
        self.asset_index = 0
        self.player = None
        self.was_muted = False
        self.mute_changed = False
        self.immich = None
        self.video_active = False
        self.stopping_for_next = False
        self.current_slot = 0
        self.monitor = None
        self.started_at = 0
        self.action_grace = 2.0
        self.prewarmed_ids = set()
        self.prewarm_thread = None

    def onInit(self):
        immich_url = ADDON.getSetting('immich_url')
        api_key = ADDON.getSetting('api_key')
        self.photo_duration = int(ADDON.getSetting('photo_duration_seconds') or 8)
        self.include_videos = ADDON.getSetting('include_videos') == 'true'
        self.play_full_video = ADDON.getSetting('play_full_video') == 'true'
        self.max_video_duration = int(ADDON.getSetting('max_video_duration_seconds') or 30)
        self.batch_size = int(ADDON.getSetting('batch_size') or 50)
        self.thumbnail_size = ADDON.getSetting('thumbnail_size') or 'preview'
        self.encoded_videos_only = ADDON.getSetting('encoded_videos_only') == 'true'
        self.enable_audio = ADDON.getSetting('enable_audio') == 'true'
        self.video_prewarm_mb = int(ADDON.getSetting('video_prewarm_mb') or 8)
        verify_ssl = ADDON.getSetting('verify_ssl') == 'true'

        self.setProperty(PROP_FADE1, '0')
        self.setProperty(PROP_FADE2, '0')
        self.setProperty(PROP_ERROR, 'hide')
        self.setProperty(PROP_IMAGES, 'show')

        self.player = ImmichPlayer()
        self.player.window = self

        self.monitor = xbmc.Monitor()
        xbmc.executebuiltin('InhibitScreensaver(true)')
        log('PlaybackScreensaver: running in script mode', xbmc.LOGINFO)

        if not immich_url:
            self._show_error(ADDON.getLocalizedString(30023))
            self._wait_for_exit()
            return
        if not api_key:
            self._show_error(ADDON.getLocalizedString(30024))
            self._wait_for_exit()
            return

        self.immich = ImmichClient(immich_url, api_key, verify_ssl)

        if not self._fetch_assets():
            self._show_error(ADDON.getLocalizedString(30021))
            self._wait_for_exit()
            return

        if not self.assets:
            self._show_error(ADDON.getLocalizedString(30022))
            self._wait_for_exit()
            return

        if not self.enable_audio:
            self.was_muted = self._get_mute()
            self._set_mute(True)
            self.mute_changed = True
            log('Audio muted for screensaver', xbmc.LOGINFO)
        else:
            log('Audio enabled for screensaver', xbmc.LOGINFO)

        self.started_at = time.time()
        log('Slideshow starting, grace period {}s'.format(self.action_grace), xbmc.LOGINFO)

        try:
            self._run_slideshow()
        finally:
            self._close_screensaver()

    def _fetch_assets(self):
        try:
            if self.include_videos:
                half = max(1, self.batch_size // 2)
                images = self.immich.get_random_assets_by_type(size=half, asset_type='IMAGE')
                if self.encoded_videos_only:
                    videos = self.immich.get_random_assets_by_type(
                        size=half, asset_type='VIDEO', is_encoded=True
                    )
                    log('Encoded-only enabled: found {} encoded videos'.format(len(videos)), xbmc.LOGINFO)
                    if not videos:
                        log('No encoded videos found; skipping video assets this batch', xbmc.LOGWARNING)
                else:
                    videos = self.immich.get_random_assets_by_type(size=half, asset_type='VIDEO')
                    log('Encoded-only disabled: {} videos (may be original or encoded)'.format(len(videos)), xbmc.LOGINFO)
                new_assets = images + videos
            else:
                new_assets = self.immich.get_random_assets_by_type(
                    size=self.batch_size, asset_type='IMAGE'
                )
            if new_assets:
                random.shuffle(new_assets)
                self.assets = new_assets
                self.asset_index = 0
                self.prewarmed_ids = set()
                return True
            return False
        except urllib.error.URLError as e:
            log('Connection error: {}'.format(e), xbmc.LOGERROR)
            return False
        except Exception as e:
            log('Error fetching assets: {}'.format(e), xbmc.LOGERROR)
            return False

    def _get_next_asset(self):
        if self.asset_index >= len(self.assets):
            if not self._fetch_assets():
                return None
        if not self.assets:
            return None
        asset = self.assets[self.asset_index]
        self.asset_index += 1
        return asset

    def _run_slideshow(self):
        log('Slideshow loop started (abort={} monitor_abort={})'.format(
            self.abort, self.monitor.abortRequested() if self.monitor else 'N/A'), xbmc.LOGINFO)
        while not self.abort and not self.monitor.abortRequested():
            asset = self._get_next_asset()
            if asset is None:
                log('No assets available, waiting', xbmc.LOGWARNING)
                self._sleep(2000)
                continue

            asset_type = asset.get('type', 'IMAGE')
            asset_id = asset.get('id')
            log('Next asset: type={} id={}'.format(asset_type, asset_id), xbmc.LOGINFO)

            if asset_type == 'VIDEO' and self.include_videos:
                self._show_video(asset_id)
            else:
                self._show_photo(asset_id)
                self._prewarm_next_video()
                self._sleep(self.photo_duration * 1000)

        log('Slideshow loop ending (abort={})'.format(self.abort), xbmc.LOGINFO)

    def _show_photo(self, asset_id):
        self.setProperty(PROP_IMAGES, 'show')
        url = self.immich.thumbnail_url(asset_id, self.thumbnail_size)
        self._crossfade_image(url)

    def _prewarm_next_video(self):
        if self.prewarm_thread and self.prewarm_thread.is_alive():
            return
        for i in range(self.asset_index, len(self.assets)):
            asset = self.assets[i]
            if asset.get('type') == 'VIDEO' and asset.get('id') not in self.prewarmed_ids:
                vid_id = asset.get('id')
                self.prewarmed_ids.add(vid_id)
                prewarm_bytes = self.video_prewarm_mb * 1024 * 1024
                log('Background prewarm next video: id={}'.format(vid_id), xbmc.LOGINFO)
                self.prewarm_thread = threading.Thread(
                    target=self.immich.prewarm_video,
                    args=(vid_id,),
                    kwargs={'bytes_count': prewarm_bytes},
                    daemon=True,
                )
                self.prewarm_thread.start()
                return

    def _crossfade_image(self, url):
        next_slot = 1 if self.current_slot == 0 else 0
        if next_slot == 0:
            next_ctrl_id = 100
            next_prop = PROP_FADE1
            old_prop = PROP_FADE2
        else:
            next_ctrl_id = 101
            next_prop = PROP_FADE2
            old_prop = PROP_FADE1

        try:
            ctrl = self.getControl(next_ctrl_id)
            ctrl.setImage(url)
        except Exception as e:
            log('Error setting image: {}'.format(e), xbmc.LOGERROR)
            return

        self.setProperty(next_prop, '0')
        self.setProperty(old_prop, '1')
        self.current_slot = next_slot
        self._sleep(FADE_TIME)

    def _show_video(self, asset_id):
        video_url = self.immich.video_url(asset_id)
        source = 'encoded-filtered' if self.encoded_videos_only else 'unfiltered'
        log('Playing video: id={} source={} url={}'.format(asset_id, source, redact_url(video_url)), xbmc.LOGINFO)

        self.video_active = False
        self.stopping_for_next = False

        log('Hiding photo controls for video', xbmc.LOGINFO)
        self.setProperty(PROP_IMAGES, 'hide')
        try:
            self.getControl(100).setImage('')
        except Exception:
            pass
        try:
            self.getControl(101).setImage('')
        except Exception:
            pass

        prewarm_bytes = self.video_prewarm_mb * 1024 * 1024
        if asset_id in self.prewarmed_ids:
            log('Video already prewarmed: id={}'.format(asset_id), xbmc.LOGINFO)
        else:
            log('Prewarming video stream: {}MB'.format(self.video_prewarm_mb), xbmc.LOGINFO)
            self.immich.prewarm_video(asset_id, bytes_count=prewarm_bytes)
        self.prewarmed_ids.discard(asset_id)

        xbmc.sleep(300)

        listitem = xbmcgui.ListItem(path=video_url)
        listitem.setContentLookup(False)
        listitem.setMimeType('video/mp4')

        xbmc.executebuiltin('Dialog.Close(busydialog,true)')
        xbmc.executebuiltin('Dialog.Close(busydialognocancel,true)')

        try:
            self.player.play(video_url, listitem=listitem, windowed=False)
        except Exception as e:
            log('Failed to start playback: {}'.format(e), xbmc.LOGERROR)
            self._sleep(1000)
            return

        timeout = 0
        while not self.video_active and timeout < 10000 and not self.abort:
            self._sleep(100)
            timeout += 100

        if not self.video_active:
            log('Video did not start within 10s, skipping', xbmc.LOGWARNING)
            if self.player.isPlaying():
                try:
                    self.stopping_for_next = True
                    self.player.stop()
                except Exception:
                    pass
            self._sleep(500)
            self._return_from_fullscreen()
            return

        log('Video active, monitoring duration', xbmc.LOGINFO)
        elapsed = 0
        max_ms = self.max_video_duration * 1000
        if self.play_full_video:
            log('Playing full video length', xbmc.LOGINFO)
            while not self.abort and self.video_active:
                self._sleep(100)
        else:
            while not self.abort and elapsed < max_ms and self.video_active:
                self._sleep(100)
                elapsed += 100

        self.stopping_for_next = True
        if self.player.isPlaying():
            try:
                self.player.stop()
            except Exception:
                pass

        self._sleep(500)
        self._return_from_fullscreen()
        log('Showing photo controls after video', xbmc.LOGINFO)
        self.setProperty(PROP_IMAGES, 'show')
        self.video_active = False
        self.stopping_for_next = False

    def _return_from_fullscreen(self):
        xbmc.sleep(200)
        if xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'):
            log('Returning from fullscreen video', xbmc.LOGINFO)
            xbmc.executebuiltin('PreviousMenu')
            xbmc.sleep(300)

    def on_av_started(self):
        log('Video playback confirmed via onAVStarted', xbmc.LOGINFO)
        self.video_active = True
        self.setProperty(PROP_IMAGES, 'hide')
        xbmc.executebuiltin('Dialog.Close(busydialog,true)')
        xbmc.executebuiltin('Dialog.Close(busydialognocancel,true)')
        xbmc.sleep(300)
        if not xbmc.getCondVisibility('Window.IsActive(fullscreenvideo)'):
            log('Forcing fullscreen video via Action(FullScreen)', xbmc.LOGINFO)
            xbmc.executebuiltin('Action(FullScreen)')

    def on_playback_ended(self):
        log('Video playback ended', xbmc.LOGINFO)
        self.video_active = False

    def on_playback_stopped(self):
        log('Video playback stopped', xbmc.LOGINFO)
        self.video_active = False
        if not self.stopping_for_next:
            log('User stopped playback, exiting screensaver', xbmc.LOGINFO)
            self.abort = True

    def on_playback_error(self):
        log('Video playback error', xbmc.LOGERROR)
        self.video_active = False

    def _sleep(self, ms):
        elapsed = 0
        while elapsed < ms and not self.abort:
            if self.monitor and self.monitor.abortRequested():
                self.abort = True
                break
            xbmc.sleep(100)
            elapsed += 100

    def _wait_for_exit(self):
        while not self.abort:
            if self.monitor and self.monitor.abortRequested():
                self.abort = True
                break
            xbmc.sleep(200)
        self._close_screensaver()

    def _close_screensaver(self):
        if self.closed:
            return
        self.closed = True
        self.abort = True

        if self.player and self.player.isPlaying():
            try:
                self.stopping_for_next = True
                self.player.stop()
            except Exception:
                pass

        if self.mute_changed:
            self._set_mute(self.was_muted)
            self.mute_changed = False

        xbmc.executebuiltin('InhibitScreensaver(false)')
        HOME.clearProperty(LOCK_PROP)

        try:
            self.getControl(100).setImage('')
        except Exception:
            pass
        try:
            self.getControl(101).setImage('')
        except Exception:
            pass

        self.setProperty(PROP_FADE1, '0')
        self.setProperty(PROP_FADE2, '0')
        self.setProperty(PROP_ERROR, 'hide')
        self.setProperty(PROP_IMAGES, 'show')
        self.close()

    def _get_mute(self):
        resp = xbmc.executeJSONRPC(json.dumps({
            'jsonrpc': '2.0',
            'method': 'Application.GetProperties',
            'params': {'properties': ['muted']},
            'id': 1
        }))
        try:
            return json.loads(resp).get('result', {}).get('muted', False)
        except Exception:
            return False

    def _set_mute(self, mute):
        xbmc.executeJSONRPC(json.dumps({
            'jsonrpc': '2.0',
            'method': 'Application.SetMute',
            'params': {'mute': mute},
            'id': 1
        }))

    def _show_error(self, message):
        if not message:
            return
        try:
            label = self.getControl(200)
            label.setLabel(message)
        except Exception as e:
            log('Could not get error label control: {}'.format(e), xbmc.LOGERROR)
        self.setProperty(PROP_ERROR, 'show')

    def onAction(self, action):
        elapsed = time.time() - self.started_at
        action_id = action.getId()
        if elapsed < self.action_grace:
            log('onAction ignored during grace: id={} elapsed={:.1f}s'.format(action_id, elapsed), xbmc.LOGINFO)
            return
        log('onAction: id={} elapsed={:.1f}s closing'.format(action_id, elapsed), xbmc.LOGINFO)
        self._close_screensaver()


def run_screensaver_mode():
    log('Starting poster screensaver mode', xbmc.LOGINFO)
    screensaver = PosterScreensaver('screen_saver.xml', ADDON_PATH, 'default', '1080i')
    screensaver.doModal()
    del screensaver
    log('Poster screensaver mode ended', xbmc.LOGINFO)


def run_script_mode():
    log('Starting playback script mode', xbmc.LOGINFO)
    HOME.setProperty(LOCK_PROP, 'true')
    screensaver = PlaybackScreensaver('screen_saver.xml', ADDON_PATH, 'default', '1080i')
    screensaver.doModal()
    del screensaver
    log('Playback script mode ended', xbmc.LOGINFO)

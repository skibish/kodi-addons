import sys

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
ADDON_PATH = ADDON.getAddonInfo('path')
HOME = xbmcgui.Window(10000)
LOCK_PROP = '{}.is_locked'.format(ADDON_ID)


def log(msg, level=xbmc.LOGINFO):
    xbmc.log('{}: {}'.format(ADDON_ID, msg), level)


class LauncherWindow(xbmcgui.WindowXMLDialog):

    class ExitMonitor(xbmc.Monitor):
        def __init__(self, activated_callback):
            super().__init__()
            self.activated_callback = activated_callback

        def onScreensaverDeactivated(self):
            self.activated_callback()

    def onInit(self):
        self.exit_monitor = self.ExitMonitor(self.exit)
        self.setProperty('ImmichScreensaver.Loading', 'true')
        log('Launcher: waiting 200ms before sending input', xbmc.LOGDEBUG)
        self.exit_monitor.waitForAbort(0.2)
        self.send_input()

    def send_input(self):
        log('Launcher: sending Input.ContextMenu', xbmc.LOGINFO)
        xbmc.executeJSONRPC('{"jsonrpc":"2.0","method":"Input.ContextMenu","id":1}')

    def exit(self):
        log('Launcher: screensaver deactivated, closing and launching script', xbmc.LOGINFO)
        self.close()
        xbmc.sleep(200)
        log('Launcher: calling RunAddon(screensaver.immich)', xbmc.LOGINFO)
        xbmc.executebuiltin('RunAddon(screensaver.immich)')

    def onAction(self, action):
        self.exit()


if __name__ == '__main__':
    video_mode = ADDON.getSetting('video_mode') or 'poster_only'
    log('Screensaver entry, video_mode={}'.format(video_mode))

    if video_mode == 'playback':
        HOME.setProperty(LOCK_PROP, 'true')
        log('Lock set, opening launcher window', xbmc.LOGINFO)
        launcher = LauncherWindow('screen_saver_launcher.xml', ADDON_PATH, 'default', '1080i')
        launcher.doModal()
        del launcher
    else:
        import default
        default.run_screensaver_mode()
    sys.modules.clear()

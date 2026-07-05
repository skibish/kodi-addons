import sys

import xbmc
import xbmcaddon
import xbmcgui

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo('id')
HOME = xbmcgui.Window(10000)
LOCK_PROP = '{}.is_locked'.format(ADDON_ID)


def log(msg, level=xbmc.LOGINFO):
    xbmc.log('{}: {}'.format(ADDON_ID, msg), level)


if __name__ == '__main__':
    is_locked = HOME.getProperty(LOCK_PROP) == 'true'
    log('Script entry, is_locked={}'.format(is_locked))

    if is_locked:
        import default
        default.run_script_mode()

    HOME.clearProperty(LOCK_PROP)
    sys.modules.clear()

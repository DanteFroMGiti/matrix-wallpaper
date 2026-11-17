from pathlib import Path
#!/usr/bin/python
import subprocess
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
from indicator import load_indicator
AppIndicator3=load_indicator()
from settings import load_profiles,activate_profile,get_paused,set_paused
from i18n import tr, get_language

class Tray:
    def __init__(self):
        self.indicator=AppIndicator3.Indicator.new('matrix-wallpaper','matrix-wallpaper',AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        self.signature=None;self.update();GLib.timeout_add_seconds(2,self.update)
    def update(self):
        signature=(tuple(load_profiles()),get_paused(),get_language())
        if signature==self.signature:return True
        self.signature=signature
        menu=Gtk.Menu()
        def item(text,callback):
            action=Gtk.MenuItem(label=text);action.connect('activate',callback);menu.append(action);return action
        item(tr('Открыть настройки'),lambda *_:subprocess.Popen([str(Path.home()/'.local/bin/matrix-wallpaper')]))
        item(tr('Продолжить') if signature[1] else tr('Пауза'),lambda *_:set_paused(not get_paused()))
        profiles=Gtk.Menu();root=item(tr('Профили'),lambda *_:None);root.set_submenu(profiles)
        for name in signature[0]:
            button=Gtk.MenuItem(label=name)
            button.connect('activate',self.profile,name);profiles.append(button)
        if not signature[0]:root.set_sensitive(False)
        item(tr('Остановить обои'),lambda *_:subprocess.Popen([str(Path.home()/'.local/bin/cmatrix-wallpaper'),'stop']))
        menu.show_all();self.indicator.set_menu(menu)
        return True
    def profile(self,item,name):
        try:
            activate_profile(name)

        except Exception as e:
            dialog=Gtk.MessageDialog(message_type=Gtk.MessageType.ERROR,buttons=Gtk.ButtonsType.NONE,text=str(e));dialog.add_button(tr('Закрыть'),Gtk.ResponseType.CLOSE);dialog.run();dialog.destroy()

if __name__ == '__main__':
    Tray();Gtk.main()

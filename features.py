"""Profiles, monitor controls, advanced effect options, pause and export UI."""
from i18n import tr
import json
import os
from pathlib import Path
import signal
import subprocess
import threading
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gdk,GLib
from settings import DEFAULTS,STATUS,SOURCE,load,validate,source_path,load_profiles,store_profile,PROFILES,atomic_json,get_paused,set_paused,matrix_settings
from runtime import monitors
from exporter import export_video

from tools_ui import Tools
from help_ui import tip

class Features(Tools):
    def install_features(self,outer,body,scroll,controls):
        self.target=None;self.profile_draft=None;self.export_cancel=None
        self.choices={};self.flags={}
        toolbar=Gtk.Box(spacing=8)
        toolbar.pack_start(Gtk.Label(label=tr('Профиль')),False,False,0)
        self.matrix_button=Gtk.Button(label=tr('Матрица'))
        self.matrix_button.set_tooltip_text(tr('Готовый режим: зелёный дождь сверху вниз, яркие головки, катакана и постепенная сборка выбранной картинки. Ограничения нагрузки сохраняются.'))
        self.matrix_button.connect('clicked',self.enable_matrix_mode)
        toolbar.pack_start(self.matrix_button,False,False,0)
        self.profiles_combo=Gtk.ComboBoxText();self.refresh_profiles()
        self.profiles_combo.connect('changed',self.choose_profile)
        toolbar.pack_start(self.profiles_combo,True,True,0)
        for label,callback in [(tr('Сохранить профиль…'),self.save_profile),(tr('Удалить'),self.delete_profile)]:
            b=Gtk.Button(label=label);b.connect('clicked',callback);toolbar.pack_start(b,False,False,0)
        outer.pack_start(toolbar,False,False,0);outer.reorder_child(toolbar,0)
        body.remove(scroll)
        tabs=Gtk.Notebook();tabs.set_size_request(355,-1)
        self.tabs=tabs
        tabs.append_page(scroll,Gtk.Label(label=tr('Оформление')))
        advanced=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);advanced.set_border_width(12)
        advanced_scroll=Gtk.ScrolledWindow();advanced_scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);advanced_scroll.add(advanced)
        tabs.append_page(advanced_scroll,Gtk.Label(label=tr('Эффекты и система')))
        body.pack_start(tabs,False,False,0);body.reorder_child(tabs,0)
        def title(text):
            label=Gtk.Label(xalign=0);label.set_markup('<b>'+text+'</b>');advanced.pack_start(label,False,False,4)
        title(tr('Мониторы'))
        self.monitor_combo=Gtk.ComboBoxText();self.monitor_combo.append('all',tr('Общие настройки для мониторов'))
        self.monitor_names=[]
        self.refresh_monitors()
        self.monitor_combo.set_active_id('all');self.monitor_combo.connect('changed',self.monitor_changed)
        advanced.pack_start(self.monitor_combo,False,False,0)
        reset_monitor=Gtk.Button(label=tr('Использовать общие настройки'))
        reset_monitor.connect('clicked',self.reset_monitor)
        advanced.pack_start(reset_monitor,False,False,0)
        title(tr('Дождь и проявление'))
        for key,label,choices in [
            ('direction',tr('Направление потоков'),[('down',tr('Сверху вниз')),('up',tr('Снизу вверх')),('right',tr('Слева направо')),('left',tr('Справа налево'))]),
            ('glyph_direction',tr('Движение символов'),[('none',tr('Неподвижно')),('left',tr('Справа налево')),('right',tr('Слева направо')),('up',tr('Снизу вверх')),('down',tr('Сверху вниз'))]),
            ('reveal',tr('Изображение'),[('steady',tr('Постоянно читается')),('reveal',tr('Плавно собирается')),('cycle',tr('Собирается и распадается'))]),
            ('color_mode',tr('Режим цвета'),[('mono',tr('Выбранный цвет')),('source',tr('Цвета исходной картинки')),('gradient',tr('Градиент')),('rainbow',tr('Радуга'))])]:
            advanced.pack_start(Gtk.Label(label=label,xalign=0),False,False,0)
            combo=Gtk.ComboBoxText()
            for ident,text in choices:combo.append(ident,text)
            combo.connect('changed',self.changed);self.choices[key]=combo;advanced.pack_start(combo,False,False,0)
        for key,label,low,high,step,digits in [('glyph_speed',tr('Скорость символов, ячеек/с'),0,8,.1,1),('tail',tr('Длина хвоста'),3,70,1,0),('density',tr('Плотность потоков'),.1,1,.05,2),('cycle',tr('Период проявления, с'),6,60,1,0),('fps',tr('Частота кадров'),5,60,1,0),('battery_fps',tr('FPS от батареи'),3,20,1,0)]:
            advanced.pack_start(Gtk.Label(label=label,xalign=0),False,False,0)
            scale=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,low,high,step);scale.set_digits(digits);scale.connect('value-changed',self.changed);self.scales[key]=scale;advanced.pack_start(scale,False,False,0)
        text_hint=Gtk.Label(label=tr('«Неподвижно» фиксирует символы. Направление и свечение потоков настраиваются отдельно.'),xalign=0);text_hint.set_line_wrap(True);text_hint.set_max_width_chars(35);advanced.pack_start(text_hint,False,False,0)
        title(tr('Экономия ресурсов'))
        for key,label in [('random_speed',tr('Случайная скорость потоков')),('eco',tr('Экономичный режим: до 12 FPS')),('pause_hidden',tr('Пауза, когда обои скрыты окнами')),('pause_locked',tr('Пауза при блокировке экрана'))]:
            check=Gtk.CheckButton(label=label);check.connect('toggled',self.changed);self.flags[key]=check;advanced.pack_start(check,False,False,0)
        hint=Gtk.Label(label=tr('В экономичном режиме FPS снижается при работе от батареи. Настройки мониторов сохраняются по кнопке «Применить».'),xalign=0);hint.set_line_wrap(True);hint.set_max_width_chars(35);advanced.pack_start(hint,False,False,0)
        self.connect('window-state-event',self.preview_window_state)
        self.install_tools(tabs,controls)

    def install_actions(self,actions):
        self.pause_button=Gtk.Button(label=tr('Пауза'));self.pause_button.connect('clicked',lambda *_:set_paused(not get_paused()));actions.pack_start(self.pause_button,False,False,0)
        b=Gtk.Button(label=tr('Экспорт MP4…'));b.connect('clicked',self.export_dialog);actions.pack_start(b,False,False,0)
        self.system_timer=0
        self.attach_metrics()

    def fill_features(self,values):
        for key,combo in self.choices.items():combo.set_active_id(values.get(key,DEFAULTS[key]))
        for key,check in self.flags.items():check.set_active(values.get(key,DEFAULTS[key]))
        self.fill_tools(values)

    def collect_features(self):
        return {**self.composition,**{key:combo.get_active_id() for key,combo in self.choices.items()},**{key:check.get_active() for key,check in self.flags.items()}}

    def refresh_monitors(self):
        names=monitors()
        if names==self.monitor_names:return
        selected=self.monitor_combo.get_active_id() or 'all'
        self.monitor_names=names
        old_loading=self.loading;self.loading=True
        self.monitor_combo.remove_all();self.monitor_combo.append('all',tr('Общие настройки для мониторов'))
        for m in names:self.monitor_combo.append(m['name'],f"{m['name']} · {m['width']}×{m['height']}")
        self.monitor_combo.set_active_id(selected if selected=='all' or any(m['name']==selected for m in names) else 'all')
        self.loading=old_loading
        if hasattr(self,'target') and self.target and not any(m['name']==self.target for m in names):
            self.target=None
            values=self.profile_draft or load();self.values=values;self.fill(values);self.changed()

    def monitor_changed(self,combo):
        if self.loading:return
        key=combo.get_active_id()
        if not key:return
        self.target=None if key=='all' else key
        base=self.profile_draft or load();values=base['monitors'].get(self.target,base)
        self.values=values;self.fill(values);self.changed()
        monitor=next((m for m in self.monitor_names if m['name']==key),self.monitor_names[0] if self.monitor_names else None)
        if monitor:self.preview_frame.set_property('ratio',monitor['width']/monitor['height'])

    def reset_monitor(self,button):
        if not self.target:return
        self.profile_draft=self.profile_draft or load()
        self.profile_draft['monitors'].pop(self.target,None)
        # Return to the shared configuration so Apply removes the override.
        self.monitor_combo.set_active_id('all')
        self.status.set_text(tr('Нажмите «Применить», чтобы убрать отдельные настройки'))

    def configuration(self):
        current=validate(self.profile_draft or load());values=self.collect()
        if self.target:current['monitors'][self.target]=dict(values,monitors={})
        else:current=dict(values,monitors=current['monitors'])
        return validate(current)

    def current_source(self):
        values=self.profile_draft or load()
        return source_path(self.target) if self.target in values['monitors'] else SOURCE

    def refresh_profiles(self,selected='custom'):
        self.profiles_combo.remove_all();self.profiles_combo.append('custom',tr('Текущие настройки'));self.profiles_combo.append('builtin:matrix',tr('Матрица — готовый режим'))
        for name in load_profiles():self.profiles_combo.append('profile:'+name,name)
        self.profiles_combo.set_active_id(selected)

    def choose_profile(self,combo):
        if getattr(self,'matrix_switching',False):return
        key=combo.get_active_id() or ''
        if key=='builtin:matrix':
            self.enable_matrix_mode()
            return
        if not key.startswith('profile:'):return
        self.profile_draft=validate(load_profiles()[key[8:]])
        self.target=None;self.monitor_combo.set_active_id('all');self.fill(self.profile_draft);self.changed()

    def enable_matrix_mode(self,button=None):
        if self.busy:return
        try:values=matrix_settings(self.collect())
        except Exception as e:self.error(str(e));return
        self.matrix_switching=True
        try:
            autostart=self.autostart.get_active()
            self.fill(values)
            self.autostart.set_active(autostart)
            self.charset.set_active_id('custom')
            self.palette.set_active(0)
            self.profiles_combo.set_active_id('builtin:matrix')
            self.status.set_text(tr('Матрица — нажмите «Применить»'))
        finally:self.matrix_switching=False
        self.changed()

    def name_dialog(self,title):
        dialog=Gtk.Dialog(title=title,transient_for=self,modal=True);dialog.add_buttons(tr('Отмена'),Gtk.ResponseType.CANCEL,tr('Сохранить'),Gtk.ResponseType.OK)
        entry=Gtk.Entry();entry.set_max_length(80);entry.set_activates_default(True)
        content=dialog.get_content_area();content.set_border_width(16);content.add(entry)
        dialog.set_default_response(Gtk.ResponseType.OK);dialog.set_response_sensitive(Gtk.ResponseType.OK,False)
        entry.connect('changed',lambda e:dialog.set_response_sensitive(Gtk.ResponseType.OK,bool(e.get_text().strip())))
        dialog.show_all();answer=dialog.run();name=entry.get_text().strip();dialog.destroy()
        return name if answer==Gtk.ResponseType.OK else None

    def save_profile(self,button):
        try:values=self.configuration()
        except Exception as e:self.error(str(e));return
        name=self.name_dialog(tr('Название профиля'))
        if name:
            try:store_profile(name,values);self.refresh_profiles('profile:'+name)
            except Exception as e:self.error(str(e))

    def delete_profile(self,button):
        key=self.profiles_combo.get_active_id() or ''
        if key.startswith('profile:'):
            values=load_profiles();values.pop(key[8:],None);atomic_json(PROFILES,values);self.refresh_profiles()

    def preview_window_state(self,window,event):
        hidden=bool(event.new_window_state & (Gdk.WindowState.ICONIFIED|Gdk.WindowState.WITHDRAWN))
        self.preview_hidden=hidden
        if self.preview_process and self.preview_process.poll() is None:
            self.preview_process.send_signal(signal.SIGSTOP if hidden else signal.SIGCONT)
        return False

    def update_system(self):
        if self.closed:return False
        try:
            self.refresh_monitors();self.pause_button.set_label(tr('Продолжить') if get_paused() else tr('Пауза'))
            if not self.busy:
                status=json.loads(STATUS.read_text());self.update_metrics(status);screens=status.get('monitors',{})
                if screens:
                    item=screens.get(self.target) or next(iter(screens.values()))
                    self.status.set_text(tr(item['reason']) if item['paused'] else tr('Обои · {value0} FPS').format(value0=item['fps']))
                else:self.status.set_text(tr('Обои остановлены'))
        except (OSError,ValueError,subprocess.SubprocessError):pass
        return True

    def export_dialog(self,button):
        if self.busy:return
        try:values=self.collect()
        except Exception as e:self.error(str(e));return
        dialog=Gtk.FileChooserDialog(title=tr('Экспорт анимации в MP4'),transient_for=self,action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(tr('Отмена'),Gtk.ResponseType.CANCEL,tr('Экспортировать'),Gtk.ResponseType.OK)
        dialog.set_current_name('matrix-wallpaper.mp4');dialog.set_do_overwrite_confirmation(True)
        video_filter=Gtk.FileFilter();video_filter.set_name(tr('Видео MP4'));video_filter.add_pattern('*.mp4');dialog.add_filter(video_filter)
        extra=Gtk.Grid(column_spacing=12,row_spacing=8);extra.set_border_width(12)
        duration=Gtk.SpinButton.new_with_range(2,60,1);duration.set_value(8)
        rate=Gtk.SpinButton.new_with_range(5,60,1);rate.set_value(20)
        resolution=Gtk.ComboBoxText()
        for ident,name in [('854x480','480p · 854×480'),('1280x720','720p · 1280×720'),('1920x1080','1080p · 1920×1080')]:resolution.append(ident,name)
        resolution.set_active_id('1280x720')
        for widget,key in [(duration,'duration'),(rate,'export_fps'),(resolution,'resolution')]:tip(widget,key)
        for row,(label,widget) in enumerate([(tr('Длительность, с'),duration),(tr('Кадров в секунду'),rate),(tr('Размер видео'),resolution)]):extra.attach(Gtk.Label(label=label,xalign=0),0,row,1,1);extra.attach(widget,1,row,1,1)
        dialog.set_extra_widget(extra);extra.show_all()
        answer=dialog.run();filename=dialog.get_filename();seconds=duration.get_value_as_int();fps=rate.get_value_as_int();width,height=map(int,resolution.get_active_id().split('x'));dialog.destroy()
        if answer!=Gtk.ResponseType.OK:return
        if not filename.lower().endswith('.mp4'):
            filename+='.mp4'
            if Path(filename).exists():
                confirm=Gtk.MessageDialog(transient_for=self,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.NONE,text=tr('Заменить существующее видео?'))
                confirm.add_buttons(tr('Нет'),Gtk.ResponseType.NO,tr('Да'),Gtk.ResponseType.YES)
                confirm.format_secondary_text(filename);replace=confirm.run();confirm.destroy()
                if replace!=Gtk.ResponseType.YES:return
        source=Path(values['image'])
        if not source.exists():source=self.current_source()
        self.export_cancel=threading.Event()
        progress_dialog=Gtk.Dialog(title=tr('Экспорт видео'),transient_for=self,modal=False)
        progress_dialog.add_button(tr('Отменить'),Gtk.ResponseType.CANCEL)
        progressbar=Gtk.ProgressBar();progressbar.set_show_text(True);progressbar.set_text(tr('Подготовка…'));progressbar.set_size_request(340,-1)
        content=progress_dialog.get_content_area();content.set_border_width(20);content.add(progressbar);progress_dialog.show_all()
        def cancel(*_):self.export_cancel.set();return True
        progress_dialog.connect('response',cancel);progress_dialog.connect('delete-event',cancel)
        def report(value):
            def update():
                if not self.closed:progressbar.set_fraction(value);progressbar.set_text(f'{value:.0%}')
                return False
            GLib.idle_add(update)
        def run():
            try:export_video(values,source,filename,width,height,fps,seconds,self.export_cancel,report)
            except InterruptedError:return tr('Экспорт отменён')
            finally:GLib.idle_add(progress_dialog.destroy)
            return tr('Видео сохранено: ')+Path(filename).name
        self.status.set_text(tr('Экспорт…'));self.work(run)

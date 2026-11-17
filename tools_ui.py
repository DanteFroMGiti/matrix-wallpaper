"""Composition, sound, portable profiles, schedules and resource controls."""
from i18n import tr
import json
from pathlib import Path
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,GLib
from settings import DEFAULTS,STATUS,load_profiles
from composition import Composition
from portable import export_bundle,import_bundle
from audio import AudioAnalyzer
from schedule import read_schedule,save_schedule

class Tools:
    def install_tools(self,tabs,controls):
        self.composition={key:DEFAULTS[key] for key in ('zoom','pan_x','pan_y','focus_mask')}
        self.preview_audio=None
        self.audio_timer=GLib.timeout_add(100,self.poll_preview_audio)
        button=Gtk.Button(label=tr('Кадрирование и выделение…'));button.connect('clicked',self.edit_composition);controls.pack_start(button,False,False,0);controls.reorder_child(button,2)
        panel=Gtk.Box(orientation=Gtk.Orientation.VERTICAL,spacing=12);panel.set_border_width(12)
        scroll=Gtk.ScrolledWindow();scroll.set_policy(Gtk.PolicyType.NEVER,Gtk.PolicyType.AUTOMATIC);scroll.add(panel);tabs.append_page(scroll,Gtk.Label(label=tr('Инструменты')))
        def title(text):
            label=Gtk.Label(xalign=0);label.set_markup('<b>'+text+'</b>');panel.pack_start(label,False,False,4)
        title(tr('Объект и глубина'))
        for key,label,low,high,step,digits in [('focus_strength',tr('Сохранение деталей объекта'),0,1,.05,2),('layers',tr('Количество слоёв'),1,3,1,0),('depth',tr('Глубина слоёв'),0,1,.05,2),('transition',tr('Переход профилей, с'),0,8,.25,2),('music_sensitivity',tr('Чувствительность к музыке'),.1,5,.1,1),('music_amount',tr('Сила реакции / вспышек'),0,.3,.01,2),('cpu_limit',tr('Цель CPU, % одного потока'),5,100,1,0)]:
            if key=='music_sensitivity':title(tr('Звук и производительность'))
            panel.pack_start(Gtk.Label(label=label,xalign=0),False,False,0)
            scale=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,low,high,step);scale.set_digits(digits);scale.connect('value-changed',self.changed);self.scales[key]=scale;panel.pack_start(scale,False,False,0)
        for key,label in [('music',tr('Реагировать на воспроизводимый звук')),('auto_limit',tr('Автоматически подбирать FPS по CPU'))]:
            flag=Gtk.CheckButton(label=label);flag.connect('toggled',self.changed);self.flags[key]=flag;panel.pack_start(flag,False,False,0)
        info=Gtk.Label(label=tr('Звук берётся с выхода системы, без микрофона. Громкость меняет яркость, басы — скорость. Сила вспышек ограничена выбранным значением.'),xalign=0);info.set_line_wrap(True);info.set_max_width_chars(34);panel.pack_start(info,False,False,0)
        self.choices['backend']=Gtk.ComboBoxText()
        for key,label in [('auto',tr('GPU автоматически, CPU при ошибке')),('gpu',tr('GPU с запасным режимом CPU')),('cpu','CPU / Cairo')]:self.choices['backend'].append(key,label)
        self.choices['backend'].connect('changed',self.changed);panel.pack_start(self.choices['backend'],False,False,0)
        title(tr('Профили и расписание'))
        for label,callback in [(tr('Импортировать профиль…'),self.import_profile_bundle),(tr('Экспортировать оформление…'),self.export_profile_bundle),(tr('Расписание профилей…'),self.edit_schedule)]:
            button=Gtk.Button(label=label);button.connect('clicked',callback);panel.pack_start(button,False,False,0)
        self.metrics_label=Gtk.Label(label=tr('Нагрузка появится после запуска обоев.'),xalign=0);self.metrics_label.set_line_wrap(True);self.metrics_label.set_max_width_chars(65)

    def attach_metrics(self):
        box=self.preview_message.get_parent();box.pack_start(self.metrics_label,False,False,0)

    def fill_tools(self,values):
        self.composition={key:values.get(key,DEFAULTS[key]) for key in self.composition}

    def edit_composition(self,button):
        try:
            source=Path(self.image_path)
            if not source.exists():source=self.current_source()
            dialog=Composition(self,source,self.collect(),self.preview_frame.get_property('ratio'))
            if dialog.run()==Gtk.ResponseType.OK:self.composition=dialog.result();self.changed()
            dialog.destroy()
        except Exception as e:self.error(str(e))

    def preview_audio_environment(self,values,env):
        if values['music']:
            env['MATRIX_AUDIO_FILE']=str(Path(self.temp.name)/'audio-level')
            if self.preview_audio is None:self.preview_audio=AudioAnalyzer(Path(env['MATRIX_AUDIO_FILE']))
        elif self.preview_audio:self.preview_audio.stop();self.preview_audio=None

    def poll_preview_audio(self):
        if self.closed:return False
        if self.preview_audio:
            if getattr(self,'preview_hidden',False):
                if self.preview_audio.process:self.preview_audio.stop()
            else:
                try:self.preview_audio.poll()
                except Exception as e:
                    self.preview_message.set_text(tr('Звук: ')+str(e));self.preview_audio.stop();self.preview_audio=None
        return True

    def update_metrics(self,status):
        screens=status.get('monitors',{});item=screens.get(self.target) or next(iter(screens.values()),None)
        if item:
            text=tr('{value0} · {value1:.1f} FPS · CPU {value2:.1f}% потока · RAM {value3:.1f} МБ').format(value0=tr(item.get('backend', '…')), value1=item.get('actual_fps', 0), value2=item.get('cpu', 0), value3=item.get('memory_mb', 0))
            if item['paused']:text+=' · '+tr(item['reason'])
            if status.get('audio_error'):text+=tr('\nЗвук: ')+status['audio_error']
            if status.get('schedule_error'):text+=tr('\nРасписание: ')+status['schedule_error']
            self.metrics_label.set_text(text)
        else:self.metrics_label.set_text(tr('Обои остановлены'))

    def bundle_dialog(self,save):
        dialog=Gtk.FileChooserDialog(title=tr('Экспорт профиля') if save else tr('Импорт профиля'),transient_for=self,action=Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(tr('Отмена'),Gtk.ResponseType.CANCEL,tr('Сохранить') if save else tr('Открыть'),Gtk.ResponseType.OK)
        if save:dialog.set_current_name('matrix-profile.mwp');dialog.set_do_overwrite_confirmation(True)
        filt=Gtk.FileFilter();filt.set_name(tr('Профиль Matrix Wallpaper (*.mwp)'));filt.add_pattern('*.mwp');dialog.add_filter(filt)
        response=dialog.run();path=dialog.get_filename();dialog.destroy()
        if response!=Gtk.ResponseType.OK:return None
        if save and not path.lower().endswith('.mwp'):
            path+='.mwp'
            if Path(path).exists():
                confirm=Gtk.MessageDialog(transient_for=self,modal=True,message_type=Gtk.MessageType.QUESTION,buttons=Gtk.ButtonsType.NONE,text=tr('Заменить существующий профиль?'));confirm.add_buttons(tr('Нет'),Gtk.ResponseType.NO,tr('Да'),Gtk.ResponseType.YES);confirm.format_secondary_text(path);answer=confirm.run();confirm.destroy()
                if answer!=Gtk.ResponseType.YES:return None
        return path
    def export_profile_bundle(self,button):
        try:values=self.configuration()
        except Exception as e:self.error(str(e));return
        path=self.bundle_dialog(True)
        if path:
            try:
                name=self.profiles_combo.get_active_text() or tr('Мои обои');export_bundle(values,name,path);self.status.set_text(tr('Профиль экспортирован'))
            except Exception as e:self.error(str(e))
    def import_profile_bundle(self,button):
        path=self.bundle_dialog(False)
        if path:
            try:name=import_bundle(path);self.refresh_profiles('profile:'+name);self.status.set_text(tr('Профиль импортирован — нажмите «Применить»'))
            except Exception as e:self.error(str(e))

    def edit_schedule(self,button):
        dialog=Gtk.Dialog(title=tr('Расписание профилей'),transient_for=self,modal=True);dialog.add_buttons(tr('Отмена'),Gtk.ResponseType.CANCEL,tr('Сохранить'),Gtk.ResponseType.OK);dialog.set_default_size(500,420)
        content=dialog.get_content_area();content.set_border_width(16);content.set_spacing(12)
        data=read_schedule();enabled=Gtk.CheckButton(label=tr('Переключать профили по местному времени'));enabled.set_active(data['enabled']);content.pack_start(enabled,False,False,0)
        enabled.set_tooltip_text(tr('Включить ежедневное расписание при сохранении этого окна. Соответствующий текущему времени профиль может примениться сразу; обои должны быть запущены.'))
        model=Gtk.ListStore(str,str)
        for row in data['entries']:model.append([row['time'],row['profile']])
        view=Gtk.TreeView(model=model);time_cell=Gtk.CellRendererText(editable=True);time_cell.connect('edited',lambda c,path,value:model.set_value(model.get_iter(path),0,value))
        view.append_column(Gtk.TreeViewColumn(tr('ЧЧ:ММ'),time_cell,text=0))
        view.set_tooltip_text(tr('Дважды нажмите ячейку, чтобы изменить время в формате ЧЧ:ММ или выбрать сохранённый профиль. Время местное, расписание повторяется каждый день.'))
        profiles=Gtk.ListStore(str)
        for name in load_profiles():profiles.append([name])
        profile_cell=Gtk.CellRendererCombo(editable=True,model=profiles,text_column=0,has_entry=False)
        profile_cell.connect('edited',lambda c,path,value:model.set_value(model.get_iter(path),1,value));view.append_column(Gtk.TreeViewColumn(tr('Профиль'),profile_cell,text=1))
        scroll=Gtk.ScrolledWindow();scroll.add(view);content.pack_start(scroll,True,True,0)
        row=Gtk.Box(spacing=8)
        add=Gtk.Button(label=tr('Добавить'));add.connect('clicked',lambda *_:model.append(['08:00',profiles[0][0] if len(profiles) else '']))
        remove=Gtk.Button(label=tr('Удалить'))
        add.set_tooltip_text(tr('Добавить время переключения и выбрать один из сохранённых профилей.'))
        remove.set_tooltip_text(tr('Удалить выбранную строку расписания. Сам сохранённый профиль останется.'))
        def delete(*_):
            selected,it=view.get_selection().get_selected()
            if it:selected.remove(it)
        remove.connect('clicked',delete);row.pack_start(add,False,False,0);row.pack_start(remove,False,False,0);content.pack_start(row,False,False,0)
        hint=Gtk.Label(label=tr('Применяется последняя запись до текущего времени, включая предыдущий день. При включении расписания соответствующий профиль может примениться сразу.'),xalign=0);hint.set_line_wrap(True);hint.set_max_width_chars(60);content.pack_start(hint,False,False,0)
        dialog.show_all()
        while dialog.run()==Gtk.ResponseType.OK:
            try:save_schedule({'enabled':enabled.get_active(),'entries':[{'time':r[0],'profile':r[1]} for r in model]});break
            except Exception as e:self.error(str(e))
        dialog.destroy()

    def cleanup_tools(self):
        if self.audio_timer:GLib.source_remove(self.audio_timer)
        if self.preview_audio:self.preview_audio.stop()

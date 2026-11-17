#!/usr/bin/python
"""GTK editor and live preview for Matrix Wallpaper on XFCE/X11."""
import os
import signal
from pathlib import Path
import subprocess
import tempfile
import threading
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Gdk', '3.0')
gi.require_version('GdkX11', '3.0')
from gi.repository import Gtk, Gdk, GdkX11, GLib, Gio
from settings import BASE, SOURCE, AUTOSTART, DEFAULTS, load, validate, save, prepare_image, environment, set_autostart, load_presets, save_presets, commit_all, CONFIG, STATUS, MATRIX_LOOK

CHARSETS = {
    'Классические': DEFAULTS['characters'],
    'Матрица (кино)': MATRIX_LOOK['characters'],
    'Двоичный код': '01',
    'Кириллица': 'АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ0123456789',
    'Катакана': 'アイウエオカキクケコサシスセソタチツテトナニヌネノ0123456789',
    'Знаки': '░▒▓█@#$%&*+=<>/\\|{}[]',
}
PHRASESETS = {
    'SQL-запросы': "SELECT * FROM users;\nSELECT name, email FROM users WHERE active = TRUE;\nINSERT INTO logs (message) VALUES ('hello matrix');\nUPDATE users SET status = 'online' WHERE id = 42;\nDELETE FROM sessions WHERE expires_at < NOW();\nSELECT COUNT(*) FROM orders GROUP BY status;\nSELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id;\nBEGIN; COMMIT;\nCREATE INDEX idx_users_email ON users(email);",
    'Русский мат': 'блядь\nпиздец\nнахуй\nебать\nзаебись\nохуенно\nёбаный рот\nда ну нахуй\nкакого хуя\nвсё пиздато\nну и хуй с ним\nзаебало\nохуеть\nебучий случай\nпиздец подкрался незаметно\nёб твою мать',
}

class TextInput(Gtk.TextView):
    def get_text(self):
        buffer = self.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
    def set_text(self, text):
        self.get_buffer().set_text(text)

PALETTES = {
    'Матрица': ('#2bff59', '#000000', '#bcffd2'),
    'Лёд': ('#21caff', '#020912', '#d4faff'),
    'Фиолетовый': ('#bd73ff', '#08020f', '#f0d9ff'),
    'Янтарь': ('#ffb52b', '#0d0700', '#fff3c9'),
}

from features import Features
from help_ui import install_help

class Editor(Features, Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title='Матричные обои')
        self.set_icon_name('matrix-wallpaper')
        self.set_default_size(1080, 850)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.preview_process = None
        self.preview_timer = 0
        self.closed = False
        self.busy = False
        self.loading = True
        self.temp = tempfile.TemporaryDirectory(prefix='matrix-wallpaper-preview-')
        self.preview_file = Path(self.temp.name) / 'image.png'
        self.preview_source = None
        self.preview_dimensions = None
        self.values = load()
        self.image_path = self.values['image']
        self.saved_presets = load_presets()
        self.colors = {}
        self.scales = {}
        header = Gtk.HeaderBar(title='Матричные обои', subtitle='Изображение из падающих символов')
        header.set_show_close_button(True)
        self.set_titlebar(header)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        outer.set_border_width(20)
        self.add(outer)
        body = Gtk.Box(spacing=24)
        outer.pack_start(body, True, True, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_size_request(300, -1)
        controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        controls.set_margin_end(12)
        scroll.add(controls)
        body.pack_start(scroll, False, False, 0)
        def title(text):
            label = Gtk.Label(xalign=0)
            label.set_markup('<b>' + text + '</b>')
            controls.pack_start(label, False, False, 3)
        title('Изображение')
        image_button = Gtk.Button(label='Выбрать картинку…')
        image_button.connect('clicked', self.choose_image)
        controls.pack_start(image_button, False, False, 0)
        self.filename = Gtk.Label(xalign=0, max_width_chars=30)
        self.filename.set_ellipsize(3)
        controls.pack_start(self.filename, False, False, 0)
        title('Символы')
        self.charset = Gtk.ComboBoxText()
        self.refresh_presets()
        self.charset.connect('changed', self.charset_changed)
        controls.pack_start(self.charset, False, False, 0)
        self.text_mode = Gtk.ComboBoxText()
        self.text_mode.append('characters', 'Отдельные символы')
        self.text_mode.append('phrases', 'Слова и фразы — строка на выражение')
        self.text_mode.set_active_id('characters')
        self.text_mode.connect('changed', self.changed)
        controls.pack_start(self.text_mode, False, False, 0)
        self.characters = TextInput()
        self.characters.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.characters.set_left_margin(6)
        self.characters.set_right_margin(6)
        self.characters.set_top_margin(6)
        self.characters.set_bottom_margin(6)
        self.characters.set_tooltip_text('Введите свои символы. В режиме слов и фраз пишите каждое выражение с новой строки.')
        self.characters.get_buffer().connect('changed', self.changed)
        text_scroll = Gtk.ScrolledWindow()
        text_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        text_scroll.set_min_content_height(86)
        text_scroll.set_max_content_height(86)
        text_scroll.add(self.characters)
        controls.pack_start(text_scroll, False, False, 0)
        preset_actions = Gtk.Box(spacing=6)
        add_preset = Gtk.Button(label='Сохранить свой набор…')
        add_preset.connect('clicked', self.save_symbol_preset)
        preset_actions.pack_start(add_preset, True, True, 0)
        self.delete_preset = Gtk.Button.new_from_icon_name('edit-delete-symbolic', Gtk.IconSize.BUTTON)
        self.delete_preset.set_tooltip_text('Удалить выбранный собственный набор')
        self.delete_preset.set_sensitive(False)
        self.delete_preset.connect('clicked', self.delete_symbol_preset)
        preset_actions.pack_start(self.delete_preset, False, False, 0)
        controls.pack_start(preset_actions, False, False, 0)
        title('Цвета')
        self.palette = Gtk.ComboBoxText()
        self.palette.append_text('Свои цвета')
        for name in PALETTES: self.palette.append_text(name)
        self.palette.set_active(0)
        self.palette.connect('changed', self.palette_changed)
        controls.pack_start(self.palette, False, False, 0)
        color_row = Gtk.Box(spacing=16)
        for key, label in [('foreground', 'Символы'), ('background', 'Фон'), ('highlight', 'Головки')]:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            button = Gtk.ColorButton()
            button.set_title(label)
            button.connect('color-set', self.changed)
            box.pack_start(button, False, False, 0)
            box.pack_start(Gtk.Label(label=label), False, False, 0)
            self.colors[key] = button
            color_row.pack_start(box, True, True, 0)
        controls.pack_start(color_row, False, False, 0)
        title('Движение и детализация')
        for key, label, low, high, step, digits in [
            ('size', 'Размер символов', 8, 32, 1, 0),
            ('speed', 'Скорость', .2, 3, .1, 1),
            ('brightness', 'Яркость', .3, 2, .05, 2),
            ('contrast', 'Контраст', .5, 2, .05, 2),
        ]:
            row = Gtk.Box(spacing=10)
            row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, step)
            scale.set_size_request(150, -1)
            scale.set_digits(digits)
            scale.connect('value-changed', self.changed)
            row.pack_start(scale, False, False, 0)
            controls.pack_start(row, False, False, 0)
            self.scales[key] = scale
        self.autostart = Gtk.CheckButton(label='Запускать при входе в систему')
        controls.pack_start(self.autostart, False, False, 6)
        self.install_features(outer, body, scroll, controls)
        preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        body.pack_start(preview_box, True, True, 0)
        label = Gtk.Label(xalign=0)
        label.set_markup('<b>Живой предпросмотр</b>')
        preview_box.pack_start(label, False, False, 0)
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(520, 320)
        self.area.connect('realize', self.changed)
        self.area.connect('size-allocate', self.preview_resized)
        display = Gdk.Display.get_default()
        monitors = [display.get_monitor(i).get_geometry() for i in range(display.get_n_monitors())]
        ratio = (max(m.x + m.width for m in monitors) - min(m.x for m in monitors)) / (max(m.y + m.height for m in monitors) - min(m.y for m in monitors))
        frame = Gtk.AspectFrame(xalign=.5, yalign=.5, ratio=ratio, obey_child=False)
        self.preview_frame = frame
        frame.add(self.area)
        preview_box.pack_start(frame, True, True, 0)
        self.preview_message = Gtk.Label(label='Настройки предпросмотра не меняют обои до нажатия «Применить».', xalign=0)
        self.preview_message.set_line_wrap(True)
        self.preview_message.set_max_width_chars(65)
        preview_box.pack_start(self.preview_message, False, False, 0)
        actions = Gtk.Box(spacing=10)
        outer.pack_end(actions, False, False, 0)
        self.status = Gtk.Label(label='Готово', xalign=0)
        actions.pack_start(self.status, True, True, 0)
        self.install_actions(actions)
        reset = Gtk.Button(label='Сбросить настройки')
        reset.connect('clicked', self.reset)
        actions.pack_start(reset, False, False, 0)
        self.stop_button = Gtk.Button(label='Остановить обои')
        self.stop_button.connect('clicked', self.stop_wallpaper)
        actions.pack_start(self.stop_button, False, False, 0)
        self.apply_button = Gtk.Button(label='Применить к рабочему столу')
        self.apply_button.get_style_context().add_class('suggested-action')
        self.apply_button.connect('clicked', self.apply)
        actions.pack_start(self.apply_button, False, False, 0)
        self.connect('destroy', self.cleanup)
        install_help(self, header)
        self.fill(self.values)
        self.loading = False
        self.show_all()
        self.changed()
        self.poll_timer = GLib.timeout_add_seconds(3, self.poll_status)

    def fill(self, values):
        self.loading = True
        self.image_path = values['image']
        self.filename.set_text(Path(self.image_path).name)
        self.filename.set_tooltip_text(self.image_path)
        self.characters.set_text(values['characters'])
        self.text_mode.set_active_id(values.get('mode', 'characters'))
        for key, button in self.colors.items():
            rgba = Gdk.RGBA()
            rgba.parse(values[key])
            button.set_rgba(rgba)
        for key, scale in self.scales.items(): scale.set_value(values.get(key, DEFAULTS[key]))
        self.fill_features(values)
        self.autostart.set_active(AUTOSTART.exists() and 'Hidden=true' not in AUTOSTART.read_text())
        self.loading = False

    def collect(self):
        values = {'image': self.image_path, 'characters': self.characters.get_text(), 'mode': self.text_mode.get_active_id()}
        for key, button in self.colors.items():
            c = button.get_rgba()
            values[key] = '#%02x%02x%02x' % tuple(round(v * 255) for v in (c.red, c.green, c.blue))
        for key, scale in self.scales.items(): values[key] = scale.get_value()
        values.update(self.collect_features())
        return validate(values)

    def choose_image(self, button):
        dialog = Gtk.FileChooserDialog(title='Картинка для матричных обоев', transient_for=self, action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons('Отмена', Gtk.ResponseType.CANCEL, 'Выбрать', Gtk.ResponseType.OK)
        filt = Gtk.FileFilter()
        filt.set_name('Изображения (PNG, JPEG, WebP и другие)')
        filt.add_mime_type('image/*')
        dialog.add_filter(filt)
        if Path(self.image_path).exists(): dialog.set_filename(self.image_path)
        if dialog.run() == Gtk.ResponseType.OK:
            self.image_path = dialog.get_filename()
            self.composition = {key: DEFAULTS[key] for key in self.composition}
            self.filename.set_text(Path(self.image_path).name)
            self.filename.set_tooltip_text(self.image_path)
            self.changed()
        dialog.destroy()

    def refresh_presets(self, selected='custom'):
        self.charset.remove_all()
        self.charset.append('custom', 'Свой набор / редактировать')
        for name in CHARSETS: self.charset.append('built:' + name, name)
        for name in PHRASESETS: self.charset.append('phrase:' + name, name)
        for name in self.saved_presets: self.charset.append('saved:' + name, 'Мой: ' + name)
        self.charset.set_active_id(selected)

    def charset_changed(self, combo):
        key = combo.get_active_id() or 'custom'
        saved = key.startswith('saved:')
        self.delete_preset.set_sensitive(saved)
        if key.startswith('built:'):
            self.text_mode.set_active_id('characters')
            self.characters.set_text(CHARSETS[key[6:]])
        elif key.startswith('phrase:'):
            self.text_mode.set_active_id('phrases')
            self.characters.set_text(PHRASESETS[key[7:]])
        elif saved:
            preset = self.saved_presets[key[6:]]
            self.text_mode.set_active_id(preset['mode'])
            self.characters.set_text(preset['characters'])
        self.changed()

    def save_symbol_preset(self, button):
        try: values = self.collect()
        except Exception as e:
            self.error(str(e))
            return
        dialog = Gtk.Dialog(title='Сохранить свой набор', transient_for=self, modal=True)
        dialog.add_buttons('Отмена', Gtk.ResponseType.CANCEL, 'Сохранить', Gtk.ResponseType.OK)
        content = dialog.get_content_area()
        content.set_border_width(16)
        content.set_spacing(8)
        content.pack_start(Gtk.Label(label='Название набора', xalign=0), False, False, 0)
        entry = Gtk.Entry()
        entry.set_max_length(60)
        entry.set_placeholder_text('Например: Мои команды')
        entry.set_activates_default(True)
        content.pack_start(entry, False, False, 0)
        dialog.set_default_response(Gtk.ResponseType.OK)
        dialog.set_response_sensitive(Gtk.ResponseType.OK, False)
        entry.connect('changed', lambda field: dialog.set_response_sensitive(Gtk.ResponseType.OK, bool(field.get_text().strip())))
        dialog.show_all()
        response = dialog.run()
        name = entry.get_text().strip()
        dialog.destroy()
        if response == Gtk.ResponseType.OK and name:
            updated = self.saved_presets | {name: {'characters': values['characters'], 'mode': values['mode']}}
            try: save_presets(updated)
            except Exception as e:
                self.error(str(e))
                return
            self.saved_presets = updated
            self.refresh_presets('saved:' + name)

    def delete_symbol_preset(self, button):
        key = self.charset.get_active_id() or ''
        if key.startswith('saved:'):
            updated = {k: v for k, v in self.saved_presets.items() if k != key[6:]}
            try: save_presets(updated)
            except Exception as e:
                self.error(str(e))
                return
            self.saved_presets = updated
            self.refresh_presets()

    def palette_changed(self, combo):
        name = combo.get_active_text()
        if name in PALETTES:
            for key, value in zip(('foreground', 'background', 'highlight'), PALETTES[name]):
                rgba = Gdk.RGBA()
                rgba.parse(value)
                self.colors[key].set_rgba(rgba)
            self.changed()

    def changed(self, *args):
        if self.loading or self.closed: return
        if self.preview_timer: GLib.source_remove(self.preview_timer)
        self.preview_timer = GLib.timeout_add(350, self.update_preview)

    def preview_resized(self, area, allocation):
        dimensions = (allocation.width, allocation.height)
        if dimensions != self.preview_dimensions:
            self.preview_dimensions = dimensions
            self.changed()

    def stop_preview(self):
        if self.preview_process:
            if self.preview_process.poll() is None: self.preview_process.send_signal(signal.SIGCONT)
            self.preview_process.terminate()
            try: self.preview_process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.preview_process.kill()
                self.preview_process.wait()
            self.preview_process = None

    def update_preview(self):
        self.preview_timer = 0
        if not self.area.get_realized() or self.closed: return False
        try:
            values = self.collect()
            # Use the saved internal image when the original was moved or deleted.
            source = Path(values['image'])
            if not source.exists() and values['image'] == self.values['image']: source = self.current_source()
            fingerprint = (str(source), source.stat().st_mtime_ns)
            if fingerprint != self.preview_source:
                prepare_image(source, self.preview_file)
                self.preview_source = fingerprint
            self.stop_preview()
            env = environment(values)
            env['MATRIX_PREVIEW'] = '1'
            self.preview_audio_environment(values, env)
            if values['eco']: env['MATRIX_FPS'] = str(min(12, values['fps']))
            xid = self.area.get_window().get_xid()
            self.preview_process = subprocess.Popen([str(BASE / 'renderer'), str(self.preview_file), '-', str(xid)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if getattr(self, 'preview_hidden', False): self.preview_process.send_signal(signal.SIGSTOP)
            self.preview_message.set_text('Предпросмотр обновляется автоматически. Нажмите «Применить», чтобы установить эти обои.')
        except Exception as e:
            self.preview_message.set_text(str(e))
        return False

    def error(self, message):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR, buttons=Gtk.ButtonsType.CLOSE, text='Не удалось выполнить действие')
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()

    def work(self, function):
        if self.busy: return
        self.busy = True
        self.apply_button.set_sensitive(False)
        self.stop_button.set_sensitive(False)
        def run():
            try:
                message = function()
                GLib.idle_add(self.finish, message, None)
            except Exception as e: GLib.idle_add(self.finish, None, str(e))
        threading.Thread(target=run, daemon=False).start()

    def finish(self, message, error):
        self.busy = False
        if self.closed: return False
        self.apply_button.set_sensitive(True)
        self.stop_button.set_sensitive(True)
        if error:
            self.status.set_text('Ошибка')
            self.error(error)
        else: self.status.set_text(message)
        return False

    def apply(self, button):
        try: values = self.configuration()
        except Exception as e:
            self.error(str(e))
            return
        autostart = self.autostart.get_active()
        self.status.set_text('Применяю…')
        def update():
            commit_all(values)
            set_autostart(autostart)
            result = subprocess.run([str(Path.home()/'.local/bin/cmatrix-wallpaper'), 'start'], capture_output=True, text=True)
            if result.returncode: raise RuntimeError(result.stderr)
            import time
            import json
            wanted = CONFIG.stat().st_mtime_ns
            deadline = time.monotonic()+8
            while time.monotonic()<deadline:
                try:
                    if json.loads(STATUS.read_text()).get('config_mtime') == wanted: break
                except (FileNotFoundError,ValueError): pass
                time.sleep(.2)
            else: raise RuntimeError('Менеджер не применил настройки. Проверьте журнал обоев.')
            if subprocess.run(['systemctl', '--user', 'is-active', '--quiet', 'matrix-wallpaper.service']).returncode:
                log = subprocess.run(['journalctl', '--user', '-u', 'matrix-wallpaper.service', '-n', '8', '--no-pager'], capture_output=True, text=True)
                raise RuntimeError(log.stdout)
            self.values = values['monitors'].get(self.target, values)
            self.profile_draft = None
            return 'Обои применены'
        self.work(update)

    def stop_wallpaper(self, button):
        self.status.set_text('Останавливаю…')
        def stop():
            return 'Обои остановлены'
        self.work(stop)

    def reset(self, button):
        values = DEFAULTS.copy()
        values['image'] = self.image_path
        self.fill(values)
        self.charset.set_active(0)
        self.palette.set_active(0)
        self.changed()

    def poll_status(self):
        if self.closed: return False
        self.update_system()
        if self.preview_process and self.preview_process.poll() is not None:
            self.preview_message.set_text('Предпросмотр остановлен. Измените настройку, чтобы запустить его снова.')
        return True

    def cleanup(self, *args):
        self.closed = True
        if self.export_cancel: self.export_cancel.set()
        self.cleanup_tools()
        if getattr(self, 'system_timer', 0): GLib.source_remove(self.system_timer)
        if self.preview_timer: GLib.source_remove(self.preview_timer)
        if getattr(self, 'poll_timer', 0): GLib.source_remove(self.poll_timer)
        self.stop_preview()
        self.temp.cleanup()

class Application(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='local.dante.MatrixWallpaper', flags=Gio.ApplicationFlags.FLAGS_NONE)
    def do_activate(self):
        window = self.get_active_window()
        if window: window.present()
        else: Editor(self)

if __name__ == '__main__':
    import sys
    application=Application()
    def shutdown():
        for window in application.get_windows():window.destroy()
        application.quit()
        return False
    signal.signal(signal.SIGTERM, lambda *_: GLib.idle_add(shutdown))
    raise SystemExit(application.run(sys.argv))

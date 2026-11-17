"""Translation coverage, persisted preferences and live GUI language switching."""
import ast
import json
from pathlib import Path
import string
import tempfile
import unittest
from unittest.mock import patch, MagicMock

import i18n

BASE = Path(__file__).resolve().parent


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='matrix-language-test-')
        self.preference = Path(self.temp.name) / 'ui.json'
        self.override = patch.object(i18n, 'LANGUAGE_FILE', self.preference)
        self.override.start()

    def tearDown(self):
        self.override.stop()
        self.temp.cleanup()

    def test_preference_is_separate_and_recovers_from_invalid_data(self):
        self.assertEqual(i18n.get_language(), 'ru')
        i18n.set_language('en')
        self.assertEqual(i18n.get_language(), 'en')
        self.assertEqual(json.loads(self.preference.read_text()), {'language': 'en'})
        self.assertEqual(i18n.tr('Матричные обои'), 'Matrix Wallpaper')
        from settings import validate, DEFAULTS
        self.assertNotIn('language', validate(dict(DEFAULTS, language='en')))
        self.preference.write_text('{broken')
        self.assertEqual(i18n.get_language(), 'ru')
        self.preference.write_text('{"language": "xx"}')
        self.assertEqual(i18n.get_language(), 'ru')
        self.preference.write_text('{"language": []}')
        self.assertEqual(i18n.get_language(), 'ru')
        with self.assertRaises(ValueError): i18n.set_language('xx')

    def test_catalog_covers_controls_tooltips_guide_and_builtins(self):
        import app
        import help_ui
        expected = set(app.CHARSETS) | set(app.PHRASESETS) | set(app.PALETTES)
        for title, text, _ in help_ui.PARAMETERS.values(): expected.update((title, text))
        for title, text in help_ui.GUIDES.values(): expected.update((title, text))
        expected.update(help_ui.BUTTON_TIPS)
        expected.update(help_ui.BUTTON_TIPS.values())
        for name in ['app.py','features.py','tools_ui.py','composition.py','help_ui.py','settings.py','portable.py','schedule.py','audio.py','exporter.py','runtime.py','tray.py','indicator.py']:
            for node in ast.walk(ast.parse((BASE / name).read_text())):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr' and node.args and isinstance(node.args[0], ast.Constant):
                    expected.add(node.args[0].value)
        expected.update(('Пауза','Экран заблокирован','Скрыты окнами','Подготовка первого кадра','Запуск'))
        self.assertFalse(expected - i18n.ENGLISH.keys(), sorted(expected - i18n.ENGLISH.keys()))
        self.assertTrue(all(i18n.ENGLISH[text].strip() for text in expected))

    def test_translations_preserve_format_fields(self):
        formatter = string.Formatter()
        def fields(text):
            return sorted((field, spec, conversion) for _, field, spec, conversion in formatter.parse(text) if field is not None)
        for original, translated in i18n.ENGLISH.items():
            self.assertEqual(fields(original), fields(translated), original)

    def test_tray_refreshes_language_without_renaming_user_profiles(self):
        from gi.repository import Gtk
        if not Gtk.init_check()[0]: self.skipTest('GUI display unavailable')
        from tray import Tray
        tray = object.__new__(Tray)
        tray.indicator = MagicMock()
        tray.signature = None
        menus = []
        with patch('tray.load_profiles', return_value={'Матрица': {}}), patch('tray.get_paused', return_value=False):
            try:
                for code, title in [('en', 'Open settings'), ('ru', 'Открыть настройки')]:
                    i18n.set_language(code)
                    self.assertTrue(tray.update())
                    menu = tray.indicator.set_menu.call_args.args[0]
                    menus.append(menu)
                    items = menu.get_children()
                    self.assertEqual(items[0].get_label(), title)
                    self.assertEqual(items[2].get_submenu().get_children()[0].get_label(), 'Матрица')
            finally:
                for menu in menus: menu.destroy()

    def test_switch_preserves_draft_user_names_and_invalid_text(self):
        from app import Editor
        from help_ui import open_guide
        from settings import CONFIG, load
        import gi
        gi.require_version('Gtk', '3.0')
        from gi.repository import Gtk, Gio
        if not Gtk.init_check()[0]: self.skipTest('GUI display unavailable')
        application = Gtk.Application(application_id='local.dante.MatrixWallpaper.TranslationTest', flags=Gio.ApplicationFlags.NON_UNIQUE)
        application.register(None)
        applied = CONFIG.read_bytes() if CONFIG.exists() else None
        profile = load()
        custom_set = {'Матрица': {'mode': 'phrases', 'characters': 'мой текст'}}
        with patch('features.load_profiles', return_value={'Матрица': profile}), patch('app.load_presets', return_value=custom_set):
            editor = Editor(application)
            try:
                editor.profiles_combo.set_active_id('profile:Матрица')
                editor.charset.set_active_id('saved:Матрица')
                editor.palette.set_active_id('Матрица')
                editor.characters.set_text('SELECT имя FROM users;\nМои слова stay unchanged')
                editor.scales['size'].set_value(19)
                editor.scales['speed'].set_value(1.7)
                editor.autostart.set_active(not editor.autostart.get_active())
                editor.tabs.set_current_page(2)
                before = editor.snapshot_ui()
                editor.language_combo.set_active_id('en')
                self.assertTrue(editor.closed)
                editor = next(window for window in application.get_windows() if isinstance(window, Editor) and not window.closed)
                self.assertEqual(editor.get_title(), 'Matrix Wallpaper')
                self.assertEqual(editor.apply_button.get_label(), 'Apply to desktop')
                self.assertEqual(editor.collect_raw(), before['raw'])
                self.assertEqual(editor.profile_draft, before['draft'])
                self.assertEqual(editor.autostart.get_active(), before['autostart'])
                self.assertEqual(editor.tabs.get_current_page(), 2)
                self.assertEqual(editor.profiles_combo.get_active_text(), 'Матрица')
                self.assertEqual(editor.charset.get_active_text(), 'My set: Матрица')
                self.assertEqual(editor.palette.get_active_id(), 'Матрица')
                self.assertEqual(editor.palette.get_active_text(), 'Matrix')
                self.assertIn('workload', editor.scales['size'].get_tooltip_text())
                open_guide(editor)
                guide = editor.guide_window
                guide.search.set_text('battery'); guide.filter_entries()
                self.assertTrue(any(guide.matches(row) for row in guide.results.get_children()))
                guide.search.set_text('no_such_parameter_qwerty'); guide.filter_entries()
                self.assertIn('No results', guide.buffer.get_text(guide.buffer.get_start_iter(), guide.buffer.get_end_iter(), True))
                guide.destroy()
                # Empty text is an unfinished edit, not a reason to discard or block a language change.
                editor.characters.set_text('')
                editor.language_combo.set_active_id('ru')
                editor = next(window for window in application.get_windows() if isinstance(window, Editor) and not window.closed)
                self.assertEqual(editor.get_title(), 'Матричные обои')
                self.assertEqual(editor.characters.get_text(), '')
                self.assertEqual(editor.palette.get_active_id(), 'Матрица')
                self.assertEqual(editor.profiles_combo.get_active_text(), 'Матрица')
                self.assertEqual(CONFIG.read_bytes() if CONFIG.exists() else None, applied)
                editor.busy = True
                editor.language_combo.set_active_id('en')
                self.assertEqual(i18n.get_language(), 'ru')
                self.assertEqual(editor.language_combo.get_active_id(), 'ru')
            finally:
                for window in application.get_windows(): window.destroy()
                while Gtk.events_pending(): Gtk.main_iteration_do(False)


if __name__ == '__main__':
    unittest.main(verbosity=2)

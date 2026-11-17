"""Load either supported GTK3 tray implementation across distributions."""
import importlib
import gi


def load_indicator():
    for name in ('AppIndicator3', 'AyatanaAppIndicator3'):
        try:
            gi.require_version(name, '0.1')
            return importlib.import_module('gi.repository.' + name)
        except (ValueError, ImportError):
            continue
    raise ImportError('Нужен AppIndicator3 или AyatanaAppIndicator3 (GTK 3).')

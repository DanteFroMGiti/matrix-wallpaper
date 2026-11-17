"""Russian source messages with an English catalog and a separate UI preference."""
import json
from pathlib import Path
import tempfile

LANGUAGE_FILE = Path.home() / '.config/matrix-wallpaper/ui.json'
LANGUAGES = {'ru': 'Русский', 'en': 'English'}
_signature = None
_language = 'ru'
try:
    ENGLISH = json.loads(Path(__file__).with_name('messages_en.json').read_text())
except (OSError, ValueError):
    ENGLISH = {}


def get_language():
    global _signature, _language
    try:
        signature = (str(LANGUAGE_FILE), LANGUAGE_FILE.stat().st_mtime_ns)
    except OSError:
        signature = (str(LANGUAGE_FILE), None)
    if signature != _signature:
        try:
            preference = json.loads(LANGUAGE_FILE.read_text()).get('language', 'ru')
        except (OSError, ValueError, AttributeError):
            preference = 'ru'
        _language = preference if isinstance(preference, str) and preference in LANGUAGES else 'ru'
        _signature = signature
    return _language


def set_language(language):
    if language not in LANGUAGES:
        raise ValueError('Unsupported interface language: ' + str(language))
    try:
        preferences = json.loads(LANGUAGE_FILE.read_text())
        if not isinstance(preferences, dict): preferences = {}
    except (OSError, ValueError):
        preferences = {}
    preferences['language'] = language
    LANGUAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=LANGUAGE_FILE.parent, prefix='.ui-', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(preferences, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        temporary.replace(LANGUAGE_FILE)
    finally:
        if temporary: temporary.unlink(missing_ok=True)


def tr(message):
    return ENGLISH.get(message, message) if get_language() == 'en' else message

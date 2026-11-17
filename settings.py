"""Shared settings and image preparation for Matrix Wallpaper."""
from i18n import tr
import json
import hashlib
import math
import uuid
import os
from pathlib import Path
from PIL import Image, ImageOps

BASE = Path(__file__).resolve().parent
CONFIG = Path.home() / '.config/matrix-wallpaper/settings.json'
PRESETS = CONFIG.with_name('symbol-presets.json')
PROFILES = CONFIG.with_name('profiles.json')
CACHE = Path.home() / '.cache/matrix-wallpaper'
CONTROL = CACHE / 'control.json'
STATUS = CACHE / 'status.json'
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', '/run/user/'+str(os.getuid()))) / 'matrix-wallpaper'
SOURCE = BASE / 'source.png'
AUTOSTART = Path.home() / '.config/autostart/cmatrix-wallpaper.desktop'
DEFAULTS = {
    'image': str(BASE / 'default.png'),
    'characters': '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#$',
    'mode': 'characters',
    'foreground': '#2bff59', 'background': '#000000', 'highlight': '#bcffd2',
    'size': 12, 'speed': 1.0, 'brightness': 1.0, 'contrast': 1.0,
    'fps': 20, 'eco': True, 'battery_fps': 8, 'pause_hidden': True, 'pause_locked': True,
    'tail': 22, 'density': 1.0, 'direction': 'down', 'random_speed': True,
    'glyph_direction': 'none', 'glyph_speed': 1.0,
    'color_mode': 'mono', 'reveal': 'reveal', 'cycle': 16,
    'zoom': 1.0, 'pan_x': 0.0, 'pan_y': 0.0, 'focus_mask': '', 'focus_strength': .7,
    'layers': 1, 'depth': .5, 'music': False, 'music_sensitivity': 1.0, 'music_amount': .15,
    'backend': 'auto', 'cpu_limit': 25, 'auto_limit': True, 'transition': 1.5,
    'monitors': {},
}

# A visual recipe: keep the chosen image, crop, masks and resource limits.
MATRIX_LOOK = {
    'characters': '0123456789Z:･.=*+-<>ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝ',
    'mode': 'characters',
    'foreground': '#00d840', 'background': '#000000', 'highlight': '#d0ffe2',
    'size': 14, 'speed': 1.0, 'brightness': 1.15, 'contrast': 1.25,
    'direction': 'down', 'glyph_direction': 'down', 'glyph_speed': 5.0,
    'tail': 28, 'density': .75, 'random_speed': True,
    'color_mode': 'mono', 'reveal': 'reveal',
    'layers': 2, 'depth': .25, 'music': False,
}

def matrix_settings(values):
    """Apply the Matrix look to the current picture, keeping user resource limits."""
    return validate(dict(values, **MATRIX_LOOK))

def load():
    result = DEFAULTS.copy()
    if CONFIG.exists():
        result.update(json.loads(CONFIG.read_text()))
    return validate(result)

def validate(values):
    result = {key: values.get(key, default) for key, default in DEFAULTS.items()}
    for key in ('image','characters','focus_mask'):
        if not isinstance(result[key],str):raise ValueError(tr('Ожидается текст: ')+key)
    if result['mode'] not in ('characters', 'phrases'):
        raise ValueError(tr('Неизвестный режим текста.'))
    if result['mode'] == 'phrases':
        lines = [' '.join(line.split()) for line in result['characters'].splitlines() if line.strip()]
        if not lines or len(lines) > 128 or any(len(line) > 512 for line in lines):
            raise ValueError(tr('Введите от 1 до 128 строк, не более 512 символов в строке.'))
        result['characters'] = '\n'.join(lines)
    else:
        result['characters'] = ''.join(dict.fromkeys(c for c in result['characters'] if c.isprintable() and not c.isspace()))
    if not 1 <= len(set(result['characters'])) <= 256:
        raise ValueError(tr('Введите от 1 до 256 различных видимых символов.'))
    for key in ('foreground', 'background', 'highlight'):
        value = result[key]
        if len(value) != 7 or value[0] != '#':
            raise ValueError(tr('Цвет должен иметь формат #RRGGBB.'))
        int(value[1:], 16)
    for key, choices in {'direction': ('down', 'up', 'right', 'left'), 'glyph_direction': ('none', 'left', 'right', 'up', 'down'), 'color_mode': ('mono', 'source', 'gradient', 'rainbow'), 'reveal': ('steady', 'reveal', 'cycle'), 'backend': ('auto', 'gpu', 'cpu')}.items():
        if result[key] not in choices: raise ValueError(tr('Неизвестное значение: ') + key)
    for key in ('eco', 'pause_hidden', 'pause_locked', 'random_speed', 'music', 'auto_limit'):
        result[key] = bool(result[key])
    for key, low, high in [('size', 8, 32), ('speed', .2, 3), ('glyph_speed', 0, 8), ('brightness', .3, 2), ('contrast', .5, 2), ('fps', 5, 60), ('battery_fps', 3, 20), ('tail', 3, 70), ('density', .1, 1), ('cycle', 6, 60), ('zoom', 1, 5), ('pan_x', -1, 1), ('pan_y', -1, 1), ('focus_strength', 0, 1), ('layers', 1, 3), ('depth', 0, 1), ('music_sensitivity', .1, 5), ('music_amount', 0, .3), ('cpu_limit', 5, 100), ('transition', 0, 8)]:
        number = float(result[key])
        if not math.isfinite(number): raise ValueError(tr('Число должно быть конечным: ') + key)
        result[key] = max(low, min(high, number))
    for key in ('size', 'fps', 'battery_fps', 'tail', 'cycle', 'layers'): result[key] = int(result[key])
    monitors = result['monitors']
    if not isinstance(monitors, dict) or len(monitors)>32: raise ValueError(tr('Неверные настройки мониторов.'))
    result['monitors'] = {str(name): validate(dict(value, monitors={})) for name, value in monitors.items()}
    return result

def load_presets():
    if not PRESETS.exists():
        return {}
    presets = json.loads(PRESETS.read_text())
    for name, value in presets.items():
        validate(DEFAULTS | value)
    return presets

def save_presets(presets):
    PRESETS.parent.mkdir(parents=True, exist_ok=True)
    tmp = PRESETS.with_suffix('.tmp')
    tmp.write_text(json.dumps(presets, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(PRESETS)

def save(values):
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG.with_suffix('.tmp')
    tmp.write_text(json.dumps(validate(values), ensure_ascii=False, indent=2) + '\n')
    tmp.replace(CONFIG)

def prepare_image(source, target):
    with Image.open(source) as im:
        im = ImageOps.exif_transpose(im).convert('RGBA')
        background = Image.new('RGBA', im.size, 'black')
        background.alpha_composite(im)
        # Avoid keeping a huge decoded photograph in the renderer.
        background.thumbnail((7680, 4320), Image.Resampling.LANCZOS)
        background.convert('RGB').save(str(target) + '.tmp', format='PNG')
    Path(str(target) + '.tmp').replace(target)

def environment(values):
    env = os.environ.copy()
    for key in DEFAULTS:
        if key not in ('image', 'monitors'):
            env['MATRIX_' + key.upper()] = str(values[key])
    return env

def set_autostart(enabled):
    AUTOSTART.parent.mkdir(parents=True, exist_ok=True)
    AUTOSTART.write_text('''[Desktop Entry]
Type=Application
Name=Matrix Wallpaper
Comment=Animated image made of falling symbols
Exec="{launcher}" start
OnlyShowIn=XFCE;
X-XFCE-Autostart-Delay=5
Terminal=false
Hidden=''' .format(launcher=str(Path.home()/'.local/bin/cmatrix-wallpaper')) + ('false' if enabled else 'true') + '\n')


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)

def source_path(monitor=None):
    if monitor is None: return SOURCE
    folder = BASE / 'sources'
    folder.mkdir(exist_ok=True)
    return folder / (hashlib.sha256(monitor.encode()).hexdigest()[:16] + '.png')

def commit(values, target=None):
    values = validate(values)
    image = Path(values['image'])
    destination = source_path(target)
    if image.exists(): prepare_image(image, destination)
    elif not destination.exists(): raise ValueError(tr('Картинка не найдена: ') + str(image))
    current = load()
    if target:
        current['monitors'][target] = dict(values, monitors={})
    else:
        current = dict(values, monitors=current['monitors'])
    save(current)
    return current

def load_profiles():
    return json.loads(PROFILES.read_text()) if PROFILES.exists() else {}

def store_profile(name, values):
    if not name.strip(): raise ValueError(tr('Введите имя профиля.'))
    values = validate(values)
    assets = BASE / 'profile-images'
    assets.mkdir(exist_ok=True)
    for monitor, item in [(None, values), *values['monitors'].items()]:
        original = Path(item['image'])
        if not original.exists(): original = source_path(monitor)
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        snapshot = assets / (digest + '.png')
        if not snapshot.exists(): prepare_image(original, snapshot)
        item['image'] = str(snapshot)
        if item['focus_mask']:
            mask=Path(item['focus_mask'])
            mask_target=assets/(hashlib.sha256(mask.read_bytes()).hexdigest()+'-mask.png')
            if not mask_target.exists():prepare_image(mask,mask_target)
            item['focus_mask']=str(mask_target)
    profiles = load_profiles()
    profiles[name] = values
    atomic_json(PROFILES, profiles)

def activate_profile(name):
    values = validate(load_profiles()[name])
    prepare_image(values['image'], SOURCE)
    for monitor, item in values['monitors'].items(): prepare_image(item['image'], source_path(monitor))
    save(values)
    return values

def set_paused(paused):
    atomic_json(CONTROL, {'paused': bool(paused)})

def get_paused():
    try: return bool(json.loads(CONTROL.read_text()).get('paused', False))
    except (FileNotFoundError, ValueError): return False

def commit_all(values):
    """Decode all inputs before replacing the active managed images/settings."""
    values = validate(values)
    staged = []
    try:
        for monitor,item in [(None,values), *values['monitors'].items()]:
            target=source_path(monitor)
            source=Path(item['image'])
            if not source.exists():
                if target.exists():continue
                raise ValueError(tr('Картинка не найдена: ')+str(source))
            temp=target.with_name(target.stem+'.'+uuid.uuid4().hex+'.png')
            prepare_image(source,temp);staged.append((temp,target))
        for temp,target in staged:temp.replace(target)
        save(values)
    finally:
        for temp,target in staged:temp.unlink(missing_ok=True)

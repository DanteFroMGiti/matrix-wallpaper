#!/usr/bin/python
"""Install/update/uninstall for the current user, without root privileges."""
import argparse
import importlib
import json
import hashlib
import signal
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

FILES=['app.py','features.py','tools_ui.py','help_ui.py','composition.py','portable.py','settings.py','runtime.py','audio.py','schedule.py','exporter.py','tray.py','indicator.py','i18n.py','messages_en.json','start.py','control.py','renderer.c','gpu.h','build.sh','README.md','README.en.md','tests_v2.py','tests_v3.py','default.png','VERSION','install.py','install-online.sh','tests_install.py','tests_i18n.py','matrix-wallpaper.svg','build_release.py','desktop_layer.py','tests_v4.py']

def dependencies():
    errors=[]
    for module in ['PIL','Xlib','numpy','gi']:
        try:importlib.import_module(module)
        except ImportError:errors.append('Python: '+module)
    try:
        import gi
        for module,version in [('Gtk','3.0')]:
            try:gi.require_version(module,version)
            except ValueError:errors.append(module)
        for name in ('AppIndicator3','AyatanaAppIndicator3'):
            try:gi.require_version(name,'0.1');break
            except ValueError:pass
        else:errors.append('AppIndicator3 / AyatanaAppIndicator3')
    except ImportError:pass
    for tool in ['cc','pkg-config','systemctl','systemd-run','xfconf-query','xrandr','ffmpeg','ffprobe','pactl','parec']:
        if not shutil.which(tool):errors.append(tool)
    if shutil.which('pkg-config'):
        result=subprocess.run(['pkg-config','--exists','x11','xext','xcomposite','cairo','pangocairo','epoxy'])
        if result.returncode:errors.append('pkg-config: x11 xext xcomposite cairo pangocairo epoxy')
    return errors

def install(home):
    errors=dependencies()
    if errors:raise RuntimeError('Установите зависимости средствами дистрибутива: '+', '.join(errors))
    source=Path(__file__).resolve().parent
    if (source/'payload').is_dir():source=source/'payload'
    checksums=source/'checksums.json'
    if checksums.exists():
        for name,digest in json.loads(checksums.read_text()).items():
            if Path(name).name!=name or hashlib.sha256((source/name).read_bytes()).hexdigest()!=digest:raise RuntimeError('Проверка целостности не прошла: '+name)
    destination=home/'.local/share/matrix-wallpaper';destination.mkdir(parents=True,exist_ok=True)
    # Compile in a staging directory, leaving the running version intact on failure.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='matrix-wallpaper-install-') as folder:
        staging=Path(folder)
        for name in FILES:
            if (source/name).exists():shutil.copy2(source/name,staging/name)
        subprocess.run(['bash',str(staging/'build.sh')],check=True)
        for path in staging.iterdir():
            if path.is_file():
                temp=destination/(path.name+'.install-tmp');shutil.copy2(path,temp);temp.replace(destination/path.name)
        installed=[p.name for p in staging.iterdir() if p.is_file()]
    bindir=home/'.local/bin';bindir.mkdir(parents=True,exist_ok=True)
    for name,module in [('matrix-wallpaper','app.py'),('cmatrix-wallpaper','control.py')]:
        path=bindir/name;path.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(destination/module))+' "$@"\n');path.chmod(0o755)
    applications=home/'.local/share/applications';applications.mkdir(parents=True,exist_ok=True)
    (applications/'matrix-wallpaper.desktop').write_text('[Desktop Entry]\nType=Application\nName=Матричные обои\nName[en]=Matrix Wallpaper\nComment=Animated matrix wallpaper editor\nExec="'+str(bindir/'matrix-wallpaper')+'"\nIcon=matrix-wallpaper\nTerminal=false\nCategories=Settings;DesktopSettings;\n')
    icon=home/'.local/share/icons/hicolor/scalable/apps/matrix-wallpaper.svg';icon.parent.mkdir(parents=True,exist_ok=True)
    if (destination/'matrix-wallpaper.svg').exists():shutil.copy2(destination/'matrix-wallpaper.svg',icon)
    (destination/'installed-files.json').write_text(json.dumps(installed))
    if home==Path.home():
        if shutil.which('update-desktop-database'):subprocess.run(['update-desktop-database',str(applications)],check=False)
        if shutil.which('gtk-update-icon-cache'):subprocess.run(['gtk-update-icon-cache','-f','-t',str(home/'.local/share/icons/hicolor')],check=False)
        # A running manager needs the new Python modules; renderer snapshots are retained.
        active=subprocess.run(['systemctl','--user','is-active','--quiet','matrix-wallpaper.service']).returncode==0
        if active:subprocess.run(['systemctl','--user','restart','matrix-wallpaper.service'],check=True)
    print('Установлено: '+str(destination))

def uninstall(home,purge):
    destination=home/'.local/share/matrix-wallpaper'
    if home==Path.home():
        subprocess.run(['systemctl','--user','stop','matrix-wallpaper.service','matrix-wallpaper-editor.service'],stderr=subprocess.DEVNULL,check=False)
        # Also close an editor started directly from the applications menu.
        for path in Path('/proc').iterdir():
            if not path.name.isdigit():continue
            try:
                argv=(path/'cmdline').read_bytes().split(b'\0')
                if os.fsencode(destination/'app.py') in argv and path.stat().st_uid==os.getuid():os.kill(int(path.name),signal.SIGTERM)
            except (FileNotFoundError,ProcessLookupError,PermissionError):pass
    if home==Path.home():shutil.rmtree(Path(os.environ.get('XDG_RUNTIME_DIR','/run/user/'+str(os.getuid())))/'matrix-wallpaper',ignore_errors=True)
    manifest=destination/'installed-files.json'
    files=json.loads(manifest.read_text()) if manifest.exists() else FILES+['renderer']
    for name in files:
        if Path(name).name!=name:continue
        (destination/name).unlink(missing_ok=True)
    manifest.unlink(missing_ok=True)
    shutil.rmtree(destination/'__pycache__',ignore_errors=True)
    for path in [home/'.local/bin/matrix-wallpaper',home/'.local/bin/cmatrix-wallpaper',home/'.local/share/applications/matrix-wallpaper.desktop',home/'.local/share/icons/hicolor/scalable/apps/matrix-wallpaper.svg',home/'.config/autostart/cmatrix-wallpaper.desktop']:path.unlink(missing_ok=True)
    if purge:
        shutil.rmtree(destination,ignore_errors=True);shutil.rmtree(home/'.config/matrix-wallpaper',ignore_errors=True);shutil.rmtree(home/'.cache/matrix-wallpaper',ignore_errors=True)
    print('Приложение удалено.'+(' Пользовательские настройки и картинки сохранены.' if not purge else ' Данные удалены.'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check',action='store_true');parser.add_argument('--update',action='store_true');parser.add_argument('--uninstall',action='store_true');parser.add_argument('--purge-data',action='store_true');parser.add_argument('--home',type=Path,default=Path.home())
    args=parser.parse_args()
    if args.purge_data and not args.uninstall:parser.error('--purge-data применяется только с --uninstall')
    if args.check:
        errors=dependencies();print('Отсутствуют: '+', '.join(errors) if errors else 'Все зависимости доступны.');return int(bool(errors))
    if args.uninstall:uninstall(args.home,args.purge_data)
    else:install(args.home)
    return 0

if __name__=='__main__':
    try:raise SystemExit(main())
    except (RuntimeError,subprocess.SubprocessError,OSError) as e:print(str(e),file=sys.stderr);raise SystemExit(1)

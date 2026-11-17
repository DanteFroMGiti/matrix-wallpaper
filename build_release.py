#!/usr/bin/env python3
"""Create an installable source archive without any personal settings or photos."""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
from install import FILES
BASE=Path(__file__).resolve().parent
version=(BASE/'VERSION').read_text().strip()
output=BASE/'dist'/f'matrix-wallpaper-{version}.tar.gz';output.parent.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='matrix-release-') as folder:
    package=Path(folder)/f'matrix-wallpaper-{version}';payload=package/'payload';payload.mkdir(parents=True)
    for name in FILES:
        source=BASE/name
        if not source.exists():raise FileNotFoundError(source)
        shutil.copy2(source,payload/name)
    checksums={name:hashlib.sha256((payload/name).read_bytes()).hexdigest() for name in FILES}
    (payload/'checksums.json').write_text(json.dumps(checksums,indent=2)+'\n')
    shutil.copy2(BASE/'install.py',package/'install.py')
    (package/'install.sh').write_text('#!/bin/sh\nexec python3 "$(dirname "$0")/install.py" "$@"\n');(package/'install.sh').chmod(0o755)
    (package/'INSTALL.txt').write_text('Matrix Wallpaper '+version+'\n\nТребуется XFCE/X11.\nПроверка: python3 install.py --check\nУстановка: python3 install.py\nОбновление: python3 install.py --update\nУдаление с сохранением данных: python3 install.py --uninstall\nПолное удаление: python3 install.py --uninstall --purge-data\n\nПодробности: payload/README.md\nЛичные картинки и настройки в этот архив не включены.\n')
    with tarfile.open(output,'w:gz') as archive:archive.add(package,arcname=package.name)
print(output)

"""Portable profile bundles; only known, validated assets are imported."""
from i18n import tr
import hashlib
import json
from pathlib import Path,PurePosixPath
import zipfile
from PIL import Image
from settings import BASE,validate,load_profiles,store_profile,source_path

def export_bundle(values,name,destination):
    values=validate(values);assets={}
    for monitor,item in [(None,values),*values['monitors'].items()]:
        for key in ('image','focus_mask'):
            if not item[key]:continue
            path=Path(item[key])
            if not path.exists() and key=='image':path=source_path(monitor)
            content=path.read_bytes();asset='assets/'+hashlib.sha256(content).hexdigest()+'.png'
            assets[asset]=content;item[key]=asset
    manifest={'format':'matrix-wallpaper-profile','version':1,'name':name,'settings':values}
    destination=Path(destination);temporary=destination.with_name(destination.name+'.tmp')
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
            for path,content in assets.items():archive.writestr(path,content)
        temporary.replace(destination)
    finally:temporary.unlink(missing_ok=True)

def import_bundle(source):
    with zipfile.ZipFile(source) as archive:
        infos=archive.infolist()
        if len(infos)>100 or sum(i.file_size for i in infos)>256*1024*1024:raise ValueError(tr('Слишком большой архив профиля.'))
        if any(PurePosixPath(i.filename).is_absolute() or '..' in PurePosixPath(i.filename).parts for i in infos):raise ValueError(tr('Неверные пути в архиве.'))
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!='matrix-wallpaper-profile' or manifest.get('version')!=1:raise ValueError(tr('Неизвестный формат профиля.'))
        values=validate(manifest['settings']);decoded={}
        for monitor,item in [(None,values),*values['monitors'].items()]:
            for key in ('image','focus_mask'):
                path=item[key]
                if not path:continue
                if not path.startswith('assets/') or path not in archive.namelist():raise ValueError(tr('Не найдена картинка профиля.'))
                content=archive.read(path)
                import io
                with Image.open(io.BytesIO(content)) as image:image.verify()
                target=BASE/'profile-images'/(hashlib.sha256(content).hexdigest()+'.png')
                decoded[target]=content;item[key]=str(target)
        # All entries have been validated before any profile is registered.
        for path,content in decoded.items():path.parent.mkdir(exist_ok=True);path.write_bytes(content)
    name=str(manifest.get('name',tr('Импортированный профиль'))).strip()[:80] or tr('Импортированный профиль')
    existing=load_profiles();base=name;i=2
    while name in existing:name=f'{base} ({i})';i+=1
    store_profile(name,values);return name

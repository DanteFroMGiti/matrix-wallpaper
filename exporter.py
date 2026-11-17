"""Export only the generated animation, never the desktop or its icons."""
from i18n import tr
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid
from settings import BASE,environment,prepare_image

def export_video(values,source,destination,width=1280,height=720,fps=20,duration=8,cancel=None,progress=None):
    if not shutil.which('ffmpeg'):raise RuntimeError(tr('Для экспорта нужен ffmpeg.'))
    destination=Path(destination)
    if not destination.parent.exists():raise ValueError(tr('Папка для видео не найдена.'))
    temporary=destination.with_name('.'+destination.stem+'-'+uuid.uuid4().hex+'.part.mp4')
    renderer=encoder=None
    try:
        with tempfile.TemporaryDirectory(prefix='matrix-export-') as folder:
            image=Path(folder)/'image.png';prepare_image(source,image)
            env=environment(values);env.update(MATRIX_EXPORT='1',MATRIX_WIDTH=str(width),MATRIX_HEIGHT=str(height),MATRIX_FPS=str(fps),MATRIX_DURATION=str(duration))
            logs=Path(folder)/'encoder.log';stats=Path(folder)/'progress.txt'
            with logs.open('wb') as log:
                renderer=subprocess.Popen([str(BASE/'renderer'),str(image),'-','0'],env=env,stdout=subprocess.PIPE,stderr=log)
                encoder=subprocess.Popen(['ffmpeg','-hide_banner','-loglevel','error','-f','rawvideo','-pixel_format','bgr0','-video_size',f'{width}x{height}','-framerate',str(fps),'-i','pipe:0','-an','-c:v','libx264','-preset','veryfast','-crf','20','-threads','2','-pix_fmt','yuv420p','-movflags','+faststart','-progress',str(stats),'-y',str(temporary)],stdin=renderer.stdout,stdout=subprocess.DEVNULL,stderr=log)
                renderer.stdout.close()
                while encoder.poll() is None:
                    if cancel and cancel.is_set():raise InterruptedError(tr('Экспорт отменён'))
                    if progress and stats.exists():
                        lines=stats.read_text().splitlines();frames=[int(line[6:]) for line in lines if line.startswith('frame=')]
                        if frames:progress(min(1,frames[-1]/(fps*duration)))
                    time.sleep(.1)
                renderer.wait(timeout=5)
                if renderer.returncode or encoder.returncode:
                    raise RuntimeError(logs.read_text(errors='replace')[-3000:] or tr('Не удалось создать видео.'))
            if cancel and cancel.is_set():raise InterruptedError(tr('Экспорт отменён'))
            os.replace(temporary,destination)
            if progress:progress(1)
    finally:
        for process in (renderer,encoder):
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=2)
                except subprocess.TimeoutExpired:process.kill();process.wait()
        temporary.unlink(missing_ok=True)

"""Desktop inspection, energy policy and renderer supervision."""
from i18n import tr
import json
import hashlib
import threading
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from Xlib import X, display
from Xlib.ext import composite
from PIL import Image
from settings import BASE,CACHE,RUNTIME,STATUS,CONFIG,load,source_path,environment,prepare_image,get_paused,atomic_json,activate_profile,load_profiles
from audio import AudioAnalyzer
from desktop_layer import DesktopPointer
from schedule import read_schedule,due,SCHEDULE_STATE

def monitors():
    result = subprocess.run(['xrandr','--listmonitors'],capture_output=True,text=True,check=True)
    found=[]
    for line in result.stdout.splitlines()[1:]:
        match=re.search(r'\s(\d+)/(?:\d+)x(\d+)/(?:\d+)\+(-?\d+)\+(-?\d+)\s+(\S+)\s*$',line)
        if match:
            w,h,x,y,name=match.groups();found.append({'name':name,'x':int(x),'y':int(y),'width':int(w),'height':int(h)})
    return found

def on_battery():
    for path in Path('/sys/class/power_supply').glob('*/status'):
        if path.read_text().strip()=='Discharging':return True
    return False

def locked():
    # logind also works with XFCE's screen locker; D-Bus covers other lockers.
    session=os.environ.get('XDG_SESSION_ID')
    if session:
        result=subprocess.run(['loginctl','show-session',session,'-p','LockedHint','--value'],capture_output=True,text=True,timeout=1)
        if result.stdout.strip()=='yes':return True
    from gi.repository import Gio,GLib
    bus=Gio.bus_get_sync(Gio.BusType.SESSION,None)
    for service,path,interface in [('org.xfce.ScreenSaver','/org/xfce/ScreenSaver','org.xfce.ScreenSaver'),('org.freedesktop.ScreenSaver','/org/freedesktop/ScreenSaver','org.freedesktop.ScreenSaver')]:
        try:
            answer=bus.call_sync(service,path,interface,'GetActive',None,GLib.VariantType.new('(b)'),Gio.DBusCallFlags.NO_AUTO_START,200,None)
            if answer.unpack()[0]:return True
        except GLib.Error:pass
    return False

def subtract(rect,cut):
    x,y,w,h=rect;cx,cy,cw,ch=cut
    l=max(x,cx);t=max(y,cy);r=min(x+w,cx+cw);b=min(y+h,cy+ch)
    if l>=r or t>=b:return [rect]
    return [a for a in [(x,y,w,t-y),(x,b,w,y+h-b),(x,t,l-x,b-t),(r,t,x+w-r,b-t)] if a[2]>0 and a[3]>0]

def covered(rect,windows):
    remaining=[rect]
    for cut in windows:
        remaining=[piece for old in remaining for piece in subtract(old,cut)]
        if not remaining:return True
    return False

def energy_policy(values, battery=False, is_locked=False, manual=False, hidden=False):
    fps=min(values['fps'],12) if values['eco'] else values['fps']
    if values['eco'] and battery:fps=min(fps,values['battery_fps'])
    reason='Пауза' if manual else 'Экран заблокирован' if values['pause_locked'] and is_locked else 'Скрыты окнами' if values['pause_hidden'] and hidden else ''
    return fps,reason

def feedback_rate(desired,cap,cpu,target,recover=False):
    if cpu>target*1.12:return max(3,min(desired,int(min(desired,cap)*.8)))
    if cpu<target*.65 and recover:return min(desired,cap+1)
    return min(desired,cap)

class Desktop:
    def __init__(self):
        self.d=display.Display();self.root=self.d.screen().root
    def property(self,window,name,default=()):
        value=window.get_full_property(self.d.intern_atom(name),X.AnyPropertyType)
        return value.value if value else default
    def frames(self):
        found=[]
        for wid in self.property(self.root,'_NET_CLIENT_LIST'):
            w=self.d.create_resource_object('window',int(wid))
            if 'xfdesktop' in (w.get_wm_class() or ()):
                frame=w
                while frame.query_tree().parent.id!=self.root.id:frame=frame.query_tree().parent
                geo=frame.get_geometry();pos=self.root.translate_coords(frame,0,0)
                found.append((frame,pos.x,pos.y,geo.width,geo.height))
        return found
    def normal_windows(self):
        if list(self.property(self.root,'_NET_SHOWING_DESKTOP',[0]))==[1]:return []
        desk=int(self.property(self.root,'_NET_CURRENT_DESKTOP',[0])[0]);rects=[]
        for wid in self.property(self.root,'_NET_CLIENT_LIST_STACKING'):
            try:
                w=self.d.create_resource_object('window',int(wid))
                if w.get_attributes().map_state!=X.IsViewable:continue
                types=[self.d.get_atom_name(int(t)) for t in self.property(w,'_NET_WM_WINDOW_TYPE')]
                if types and '_NET_WM_WINDOW_TYPE_NORMAL' not in types:continue
                if 'MatrixWallpaper' in (w.get_wm_class() or ()):continue
                states=[self.d.get_atom_name(int(t)) for t in self.property(w,'_NET_WM_STATE')]
                if any(t in states for t in ['_NET_WM_STATE_HIDDEN','_NET_WM_STATE_SHADED']):continue
                if int(self.property(w,'_NET_WM_DESKTOP',[desk])[0]) not in (desk,0xffffffff):continue
                if int(self.property(w,'_NET_WM_WINDOW_OPACITY',[0xffffffff])[0])<0xfcffffff:continue
                geo=w.get_geometry();pos=self.root.translate_coords(w,0,0)
                # Include the frame, so maximized windows covering the work area count.
                ext=list(self.property(w,'_NET_FRAME_EXTENTS',[0,0,0,0]));l,r,t,b=(ext+[0]*4)[:4]
                rects.append((pos.x-l,pos.y-t,geo.width+l+r,geo.height+t+b))
            except Exception:continue
        return rects
    @staticmethod
    def frame_image(frame,width,height):
        pixmap=frame.composite_name_window_pixmap()
        try:
            raw=pixmap.get_image(0,0,width,height,X.ZPixmap,0xffffffff)
            return Image.frombytes('RGB',(width,height),raw.data,'raw','BGRX')
        finally:pixmap.free()
    @staticmethod
    def frame_for(m,frames):
        return max(frames,key=lambda f:max(0,min(m['x']+m['width'],f[1]+f[3])-max(m['x'],f[1]))*max(0,min(m['y']+m['height'],f[2]+f[4])-max(m['y'],f[2])))
    def capture(self,layout):
        frames=self.frames()
        if not frames:raise RuntimeError(tr('Рабочий стол XFCE не найден.'))
        props=subprocess.run(['xfconf-query','-c','xfce4-desktop','-lv'],capture_output=True,text=True)
        backdrop='\n'.join(line for line in props.stdout.splitlines() if line.startswith('/backdrop/'))
        stamps=[]
        for line in backdrop.splitlines():
            value=line.split(None,1)
            if len(value)==2:
                try:stamps.append((value[1],Path(value[1]).stat().st_mtime_ns))
                except OSError:pass
        signature=hashlib.sha256(json.dumps([layout,backdrop,stamps],sort_keys=True).encode()).hexdigest()
        metadata=CACHE/'desktop-baselines.json'
        files={m['name']:CACHE/(source_path(m['name']).stem+'-baseline.png') for m in layout}
        try:cached=json.loads(metadata.read_text()).get('signature')==signature
        except (OSError,ValueError):cached=False
        cached=cached and all(path.exists() for path in files.values())
        if cached:
            try:
                for m in layout:
                    with Image.open(files[m['name']]) as image:
                        if image.size!=(m['width'],m['height']):cached=False;break
                        image.verify()
            except (OSError,ValueError):cached=False
        old=subprocess.run(['xfconf-query','-c','xfce4-desktop','-p','/desktop-icons/style'],capture_output=True,text=True)
        if old.returncode or old.stdout.strip()!='2':
            cmd=['xfconf-query','-c','xfce4-desktop','-p','/desktop-icons/style','-s','2']
            if old.returncode:cmd+=['--create','-t','int']
            subprocess.run(cmd,check=True);time.sleep(.2)
        if not cached:
            # Adopt an existing clean baseline on upgrade when only icon pixels differ.
            if all(path.exists() for path in files.values()):
                import numpy as np
                try:
                    valid=True
                    for m in layout:
                        frame,fx,fy,fw,fh=self.frame_for(m,frames)
                        current=self.frame_image(frame,fw,fh).crop((m['x']-fx,m['y']-fy,m['x']-fx+m['width'],m['y']-fy+m['height']))
                        base=Image.open(files[m['name']]).convert('RGB')
                        if current.size!=base.size:valid=False;break
                        changed=(np.abs(np.asarray(current,dtype=np.int16)-np.asarray(base,dtype=np.int16)).sum(2)>12).sum()
                        if not 64<int(changed)<m['width']*m['height']*.12:valid=False;break
                    cached=valid
                except (OSError,ValueError):cached=False
            if not cached:
                # Needed only for a genuinely new ordinary XFCE background/layout.
                # KillMode=mixed lets finally restore file icons during service shutdown.
                try:
                    subprocess.run(['xfconf-query','-c','xfce4-desktop','-p','/desktop-icons/style','-s','0'],check=True)
                    time.sleep(.45);frames=self.frames()
                    snapshots={frame.id:self.frame_image(frame,fw,fh) for frame,fx,fy,fw,fh in frames}
                    for m in layout:
                        frame,fx,fy,fw,fh=self.frame_for(m,frames);x=m['x']-fx;y=m['y']-fy
                        if min(x,y)<0 or x+m['width']>fw or y+m['height']>fh:raise RuntimeError(tr('Область монитора выходит за границы рабочего стола.'))
                        snapshots[frame.id].crop((x,y,x+m['width'],y+m['height'])).save(files[m['name']])
                finally:
                    subprocess.run(['xfconf-query','-c','xfce4-desktop','-p','/desktop-icons/style','-s','2'],check=True,timeout=3)
                time.sleep(.35)
            atomic_json(metadata,{'signature':signature})
        frames=self.frames();result={}
        for m in layout:
            frame,fx,fy,fw,fh=self.frame_for(m,frames)
            result[m['name']]=(str(files[m['name']]),frame.id,m['x']-fx,m['y']-fy)
        return result

class Manager:
    def __init__(self):
        self.running=True;self.workers={};self.layout=[];self.desktop=Desktop();self.tray=None;self.frame_signature=None;self.background_signature=None;self.config_signature=None;self.retiring=[];self.audio=None;self.sample_state={};self.schedule_error="";self.audio_error="";self.interaction_event=threading.Event();self.pointer=DesktopPointer(self)
        RUNTIME.mkdir(parents=True,exist_ok=True)
        CACHE.mkdir(parents=True,exist_ok=True)
    @staticmethod
    def stop_group(group):
        for worker in group.values():
            process=worker['process']
            if process.poll() is None:process.send_signal(signal.SIGCONT);process.terminate()
        for worker in group.values():
            try:worker['process'].wait(timeout=2)
            except subprocess.TimeoutExpired:worker['process'].kill();worker['process'].wait()
            if worker.get('ready'):worker['ready'].unlink(missing_ok=True)
    def stop_workers(self):
        self.stop_group(self.workers);self.workers={}
        for deadline,group in getattr(self,'retiring',[]):self.stop_group(group)
        self.retiring=[]
    def metrics(self,process):
        try:
            pid=process.pid;fields=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split();ticks=int(fields[11])+int(fields[12]);now=time.monotonic()
            old=self.sample_state.get(pid);self.sample_state[pid]=(ticks,now)
            cpu=0 if not old else (ticks-old[0])/os.sysconf('SC_CLK_TCK')/(now-old[1])*100
            rss=int(Path(f'/proc/{pid}/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
            return round(cpu,1),round(rss/1048576,1)
        except (FileNotFoundError,ValueError,ProcessLookupError):return 0,0
    def schedule_tick(self):
        choice=due(read_schedule())
        if choice:
            key,name=choice
            previous=json.loads(SCHEDULE_STATE.read_text()).get('key') if SCHEDULE_STATE.exists() else None
            if key!=previous:
                if name not in load_profiles():raise ValueError(tr('Профиль расписания не найден: ')+name)
                activate_profile(name);atomic_json(SCHEDULE_STATE,{'key':key})
    def rebuild(self,layout):
        RUNTIME.mkdir(parents=True,exist_ok=True)
        values=load();previous=self.workers;self.workers={}
        for worker in previous.values():
            if worker['process'].poll() is None:worker['process'].send_signal(signal.SIGSTOP)
        if previous:
            if not hasattr(self,'retiring'):self.retiring=[]
            self.retiring.append((time.monotonic()+values['transition']+1,previous))
        captures=self.desktop.capture(layout)
        for m in layout:
            v=values['monitors'].get(m['name'],values)
            src=source_path(m['name']) if m['name'] in values['monitors'] else source_path()
            if not src.exists():prepare_image(v['image'],src)
            baseline,frame,x,y=captures[m['name']];env=environment(v)
            for key in ('x','y','width','height'):env['MATRIX_'+key.upper()]=str(m[key])
            rate=CACHE/(source_path(m['name']).stem+'-fps');rate.write_text(str(v['fps']))
            stats=CACHE/(source_path(m['name']).stem+'-stats');stats.unlink(missing_ok=True)
            ready=CACHE/(source_path(m['name']).stem+f'-{time.monotonic_ns()}.ready')
            icons=RUNTIME/(source_path(m['name']).stem+f"-{m['width']}x{m['height']}-icons.argb")
            animation=RUNTIME/(source_path(m['name']).stem+'-animation-paused');animation.write_text('0')
            env.update(MATRIX_ICONS_FILE=str(icons),MATRIX_ANIMATION_PAUSE_FILE=str(animation),MATRIX_CAPTURE_X=str(x),MATRIX_CAPTURE_Y=str(y),MATRIX_RATE_FILE=str(rate),MATRIX_STATS_FILE=str(stats),MATRIX_READY_FILE=str(ready),MATRIX_AUDIO_FILE=str(CACHE/'audio-level'),MATRIX_FADE_SECONDS=str(values['transition'] if previous else 0))
            process=subprocess.Popen([str(BASE/'renderer'),str(src),baseline,hex(frame)],env=env)
            self.workers[m['name']]={'process':process,'values':v,'rate':rate,'paused':False,'fps':v['fps'],'stats':stats,'ready':ready,'limit':v['fps'],'icons':icons,'animation':animation,'monitor':dict(m),'suspended':False}
        self.layout=layout
    def run(self):
        signal.signal(signal.SIGTERM,lambda *_:setattr(self,'running',False))
        signal.signal(signal.SIGINT,lambda *_:setattr(self,'running',False))
        self.tray=subprocess.Popen([sys.executable,str(BASE/'tray.py')])
        self.pointer.start()
        check=0
        try:
            while self.running:
                if check%3==0:
                    try:self.schedule_tick();self.schedule_error=''
                    except Exception as e:self.schedule_error=str(e)
                    config_signature=CONFIG.stat().st_mtime_ns if CONFIG.exists() else 0
                    layout=monitors()
                    frames=tuple((f[0].id,*f[1:]) for f in self.desktop.frames())
                    props=subprocess.run(['xfconf-query','-c','xfce4-desktop','-lv'],capture_output=True,text=True)
                    backdrop='\n'.join(line for line in props.stdout.splitlines() if line.startswith('/backdrop/'))
                    if config_signature!=self.config_signature or layout!=self.layout or frames!=self.frame_signature or backdrop!=self.background_signature or any(w['process'].poll() is not None for w in self.workers.values()):
                        self.rebuild(layout);self.frame_signature=tuple((f[0].id,*f[1:]) for f in self.desktop.frames());self.background_signature=backdrop;self.config_signature=config_signature
                    self.battery=on_battery();self.is_locked=locked()
                retired=[]
                for deadline,group in self.retiring:
                    if time.monotonic()>=deadline:self.stop_group(group)
                    else:retired.append((deadline,group))
                self.retiring=retired
                music_enabled=any(w['values']['music'] and not w['paused'] for w in self.workers.values())
                if music_enabled:
                    if self.audio is None:self.audio=AudioAnalyzer(CACHE/'audio-level')
                    try:self.audio.poll();self.audio_error=''
                    except Exception as e:
                        self.audio_error=str(e);self.audio.stop();self.audio=None
                else:
                    if self.audio:self.audio.stop();self.audio=None
                    self.audio_error=''
                rects=self.desktop.normal_windows();manual=get_paused();status={}
                for m in self.layout:
                    worker=self.workers[m['name']];v=worker['values']
                    # Panels occupy reserved edges but the wallpaper beneath them is hidden too.
                    reason='Пауза' if manual else 'Экран заблокирован' if v['pause_locked'] and self.is_locked else ''
                    if not reason and v['pause_hidden']:
                        work=list(self.desktop.property(self.desktop.root,'_NET_WORKAREA'))
                        area=(m['x'],m['y'],m['width'],m['height'])
                        desk=int(self.desktop.property(self.desktop.root,'_NET_CURRENT_DESKTOP',[0])[0])
                        if len(work)>=4*(desk+1):
                            wx,wy,ww,wh=work[desk*4:desk*4+4];left=max(area[0],int(wx));top=max(area[1],int(wy));right=min(area[0]+area[2],int(wx+ww));bottom=min(area[1]+area[3],int(wy+wh));area=(left,top,max(0,right-left),max(0,bottom-top))
                        if area[2] and area[3] and covered(area,rects):reason='Скрыты окнами'
                    ready=worker['ready'].exists()
                    paused=bool(reason) and ready
                    if reason and not ready:reason='Подготовка первого кадра'

                    suspended=paused and reason!='Пауза'
                    if suspended!=worker['suspended'] and worker['process'].poll() is None:
                        worker['process'].send_signal(signal.SIGSTOP if suspended else signal.SIGCONT);worker['suspended']=suspended
                    if paused!=worker['paused']:
                        worker['animation'].write_text('1' if paused and reason=='Пауза' else '0');worker['paused']=paused
                    cpu,memory=self.metrics(worker['process'])
                    fps,_=energy_policy(v,battery=self.battery)
                    if v['auto_limit'] and not paused:
                        worker['limit']=feedback_rate(fps,worker['limit'],cpu,v['cpu_limit'],check%4==0)
                        fps=min(fps,worker['limit'])
                    if paused and not suspended:fps=min(fps,5)
                    if fps!=worker['fps']:worker['rate'].write_text(str(fps));worker['fps']=fps
                    actual_fps=0;backend='Запуск'
                    try:
                        parts=worker['stats'].read_text().split();actual_fps=float(parts[0]);backend=parts[1]
                    except (OSError,ValueError,IndexError):pass
                    status[m['name']]={'paused':paused,'reason':reason,'fps':fps,'actual_fps':0 if paused else round(actual_fps,1),'backend':backend,'cpu':cpu,'memory_mb':memory,'pid':worker['process'].pid}
                atomic_json(STATUS,{'monitors':status,'battery':self.battery,'manual_pause':manual,'audio_error':self.audio_error,'schedule_error':self.schedule_error,'audio_level':self.audio.energy if self.audio else 0,'config_mtime':self.config_signature})
                check+=1;self.interaction_event.wait(.75);self.interaction_event.clear()
        except subprocess.CalledProcessError:
            if self.running:raise
        finally:
            self.pointer.stop()
            self.stop_workers()
            if self.audio:self.audio.stop()
            if self.tray and self.tray.poll() is None:self.tray.terminate();self.tray.wait(timeout=2)
            self.desktop.d.close();atomic_json(STATUS,{'monitors':{}})

if __name__=='__main__':Manager().run()

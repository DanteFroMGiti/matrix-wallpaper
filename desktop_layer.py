"""Read-only pointer tracking for desktop rubber-band selection.

Mouse events are always handled by XFCE. Only the rectangle is communicated to
our input-transparent wallpaper windows; no input is grabbed or replayed.
"""
import os
from pathlib import Path
import signal
import subprocess
import threading
import time
import numpy as np
from Xlib import X,Xatom,display

SELECTION_ATOM='_MATRIX_WALLPAPER_SELECTION'

def rectangle(start,end):
    x,y=start;xx,yy=end
    return min(x,xx),min(y,yy),abs(xx-x),abs(yy-y)

def icon_hit(path,width,height,x,y,padding=12):
    if x<0 or y<0 or x>=width or y>=height:return False
    try:
        data=np.memmap(path,dtype=np.uint8,mode='r',shape=(height,width,4))
        alpha=data[max(0,y-padding):min(height,y+padding+1),max(0,x-padding):min(width,x+padding+1),3]
        result=bool(np.any(alpha));del data
        return result
    except (OSError,ValueError):return False

class DesktopPointer:
    def __init__(self,manager):
        self.manager=manager;self.event=threading.Event();self.thread=None;self.last_motion_wake=0
    def start(self):
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()
    def stop(self):
        self.event.set()
        if self.thread:self.thread.join(timeout=1)
    @staticmethod
    def desktop_window(window,root):
        if window in (0,None):return True
        try:
            candidate=root.display.create_resource_object('window',int(window)) if isinstance(window,int) else window
            windows=[candidate,*candidate.query_tree().children]
            return any(any(name in (w.get_wm_class() or ()) for name in ('xfdesktop','Xfdesktop','MatrixWallpaper')) for w in windows)
        except Exception:return False
    def blank(self,x,y):
        for worker in list(self.manager.workers.values()):
            m=worker.get('monitor')
            if m and m['x']<=x<m['x']+m['width'] and m['y']<=y<m['y']+m['height']:
                return not icon_hit(worker['icons'],m['width'],m['height'],x-m['x'],y-m['y'],padding=2)
        return True
    def wake(self,rect=None):
        if rect is not None:
            now=time.monotonic()
            if now-self.last_motion_wake<1/30:return
            self.last_motion_wake=now
        for worker in list(self.manager.workers.values()):
            process=worker['process'];m=worker.get('monitor')
            if rect is not None and m:
                x,y,w,h=rect
                if x+w<m['x'] or y+h<m['y'] or x>m['x']+m['width'] or y>m['y']+m['height']:continue
            try:
                if process.poll() is None:
                    if worker.get('suspended') or not worker['ready'].exists():continue
                    process.send_signal(signal.SIGUSR1)
            except ProcessLookupError:pass
    def run(self):
        d=display.Display();root=d.screen().root;atom=d.intern_atom(SELECTION_ATOM)
        start=None;was_down=False;last=None;directory_stamp=None;file_check=0
        try:
            path=subprocess.run(['xdg-user-dir','DESKTOP'],capture_output=True,text=True,timeout=1).stdout.strip()
            desktop=Path(path) if path else Path.home()/'Desktop'
        except (OSError,subprocess.SubprocessError):desktop=Path.home()/'Desktop'
        try:
            root.change_property(atom,Xatom.CARDINAL,32,[0,0,0,0,0]);d.flush()
            while not self.event.is_set():
                q=root.query_pointer();down=bool(q.mask & X.Button1Mask)
                x,y=int(q.root_x),int(q.root_y)
                if down and not was_down:
                    start=(x,y) if self.desktop_window(q.child,root) and self.blank(x,y) else None
                if not down:start=None
                value=[0,0,0,0,0];rect=None
                if down and start:
                    rect=rectangle(start,(x,y))
                    if rect[2]>=4 and rect[3]>=4:value=[1,*rect]
                if value!=last:
                    root.change_property(atom,Xatom.CARDINAL,32,value);d.flush()
                    self.wake(rect if value[0] else (tuple(last[1:]) if last and last[0] else None));last=value
                # Left clicks on icons also need an immediate highlight refresh.
                if down!=was_down:
                    self.wake();self.manager.interaction_event.set()
                was_down=down
                file_check+=1
                if file_check%30==0:
                    try:stamp=desktop.stat().st_mtime_ns
                    except OSError:stamp=None
                    if directory_stamp is not None and stamp!=directory_stamp:self.wake()
                    directory_stamp=stamp
                self.event.wait(1/60)
        finally:
            root.change_property(atom,Xatom.CARDINAL,32,[0,0,0,0,0]);d.flush();d.close()

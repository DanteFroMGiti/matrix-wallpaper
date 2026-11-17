"""Analyze playback monitor audio locally; microphone devices are never selected."""
from i18n import tr
import os
from pathlib import Path
import select
import signal
import subprocess
import time
import threading
import numpy as np

class AudioAnalyzer:
    def __init__(self,path):self.path=Path(path);self.process=None;self.buffer=bytearray();self.energy=0;self.bass=0;self.error='';self.thread=None;self.event=threading.Event()
    def start(self):
        sink=subprocess.run(['pactl','get-default-sink'],capture_output=True,text=True,timeout=2)
        if sink.returncode:raise RuntimeError(tr('Не найден аудиовыход PulseAudio/PipeWire.'))
        self.process=subprocess.Popen(['parec','--device='+sink.stdout.strip()+'.monitor','--format=float32le','--rate=22050','--channels=1','--latency-msec=80'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        os.set_blocking(self.process.stdout.fileno(),False)
    def poll(self):
        if self.error:raise RuntimeError(self.error)
        if not self.process:
            self.event.clear();self.start()
            self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
        return self.energy,self.bass
    def loop(self):
        while not self.event.is_set():
            try:self.sample()
            except Exception as e:self.error=str(e);return
            self.event.wait(.05)
    def sample(self):
        if self.process.poll() is not None:raise RuntimeError(tr('Поток звука недоступен.'))
        try:self.buffer.extend(os.read(self.process.stdout.fileno(),65536))
        except BlockingIOError:pass
        if len(self.buffer)>=4096:
            data=bytes(self.buffer[-4096:]);self.buffer.clear();values=self.analyze(data)
            self.energy=.7*self.energy+.3*values[0];self.bass=.7*self.bass+.3*values[1]
        else:self.energy*=.95;self.bass*=.95
        self.path.write_text(f'{self.energy:.5f} {self.bass:.5f}\n')
        return self.energy,self.bass
    @staticmethod
    def analyze(data):
        samples=np.frombuffer(data,dtype='<f4');samples=np.nan_to_num(samples,nan=0,posinf=0,neginf=0)
        rms=float(np.sqrt(np.mean(samples*samples)))
        spectrum=np.abs(np.fft.rfft(samples*np.hanning(len(samples))))/max(1,len(samples))
        frequencies=np.fft.rfftfreq(len(samples),1/22050)
        bass=float(np.sqrt(np.sum(spectrum[(frequencies>=30)&(frequencies<=200)]**2)))
        return min(1,rms*5),min(1,bass*12)
    def stop(self):
        self.event.set()
        if self.thread:self.thread.join(timeout=.4);self.thread=None
        if self.process:
            self.process.terminate()
            try:self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
            self.process=None
        self.path.write_text('0 0\n')

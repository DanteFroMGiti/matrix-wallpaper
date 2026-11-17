#!/usr/bin/python
"""Portable command line entry point for the user service."""
import os
import subprocess
import sys
from pathlib import Path
from settings import BASE,set_paused

def main():
    action=sys.argv[1] if len(sys.argv)>1 else 'start'
    unit='matrix-wallpaper.service'
    if action in ('pause','resume'):set_paused(action=='pause');return 0
    if action=='stop':return subprocess.run(['systemctl','--user','stop',unit],stderr=subprocess.DEVNULL).returncode if subprocess.run(['systemctl','--user','is-active','--quiet',unit]).returncode==0 else 0
    if action=='status':return subprocess.run(['systemctl','--user','status',unit,'--no-pager']).returncode
    if action!='start':print('Использование: cmatrix-wallpaper [start|stop|pause|resume|status]',file=sys.stderr);return 2
    if subprocess.run(['systemctl','--user','is-active','--quiet',unit]).returncode==0:return 0
    env=['DISPLAY='+os.environ.get('DISPLAY',':0'),'XAUTHORITY='+os.environ.get('XAUTHORITY',str(Path.home()/'.Xauthority'))]
    if os.environ.get('XDG_SESSION_ID'):env+=['XDG_SESSION_ID='+os.environ['XDG_SESSION_ID']]
    return subprocess.run(['systemd-run','--user','--unit=matrix-wallpaper','--collect','--property=Restart=on-failure','--property=RestartSec=2','--property=KillMode=mixed','/usr/bin/env',*env,sys.executable,str(BASE/'start.py')]).returncode

if __name__=='__main__':raise SystemExit(main())

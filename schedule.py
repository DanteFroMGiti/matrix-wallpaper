"""Daily profile schedule, evaluated in the user's local timezone."""
from datetime import datetime,timedelta
import json
import re
from settings import CONFIG,CACHE,load_profiles,atomic_json
SCHEDULE=CONFIG.with_name('schedule.json')
SCHEDULE_STATE=CACHE/'schedule-state.json'
def read_schedule():
    return json.loads(SCHEDULE.read_text()) if SCHEDULE.exists() else {'enabled':False,'entries':[]}
def save_schedule(data):
    profiles=load_profiles();entries=[]
    for item in data['entries']:
        value=item['time']
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',value):raise ValueError('Введите время в формате ЧЧ:ММ.')
        if item['profile'] not in profiles:raise ValueError('Профиль не найден: '+item['profile'])
        entries.append({'time':value,'profile':item['profile']})
    if data['enabled'] and not entries:raise ValueError('Добавьте хотя бы один пункт расписания.')
    if len({e['time'] for e in entries})!=len(entries):raise ValueError('Время в расписании повторяется.')
    atomic_json(SCHEDULE,{'enabled':bool(data['enabled']),'entries':sorted(entries,key=lambda e:e['time'])})
def due(data,now=None):
    if not data.get('enabled') or not data.get('entries'):return None
    now=now or datetime.now();clock=now.strftime('%H:%M');entries=sorted(data['entries'],key=lambda e:e['time'])
    eligible=[e for e in entries if e['time']<=clock]
    item=eligible[-1] if eligible else entries[-1];day=now.date() if eligible else (now-timedelta(days=1)).date()
    return f"{day}:{item['time']}:{item['profile']}",item['profile']

"""Regression checks for settings, energy policy, monitor crops, profiles and export."""
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch,MagicMock
from PIL import Image
import settings as st
import runtime as rt
from exporter import export_video

class FeaturesTests(unittest.TestCase):
    def test_coverage_union_and_holes(self):
        self.assertTrue(rt.covered((0,0,200,100),[(0,0,100,100),(100,0,100,100)]))
        self.assertFalse(rt.covered((0,0,200,100),[(0,0,99,100),(100,0,100,100)]))
        self.assertFalse(rt.covered((0,0,200,100),[(0,0,200,99)]))
        self.assertTrue(rt.covered((100,30,100,100),[(0,0,300,200)]))

    def test_power_and_pause_policies(self):
        v=st.validate(st.DEFAULTS)
        self.assertEqual(rt.energy_policy(v),(12,''))
        self.assertEqual(rt.energy_policy(v,battery=True),(8,''))
        self.assertEqual(rt.energy_policy(v,is_locked=True)[1],'Экран заблокирован')
        self.assertEqual(rt.energy_policy(v,hidden=True)[1],'Скрыты окнами')
        self.assertEqual(rt.energy_policy(v,manual=True)[1],'Пауза')
        v.update(eco=False,pause_hidden=False,pause_locked=False,fps=30)
        self.assertEqual(rt.energy_policy(v,battery=True,is_locked=True,hidden=True),(30,''))

    def test_validation_and_migration(self):
        v=st.validate({'characters':'ААБ★'})
        self.assertEqual(v['characters'],'АБ★');self.assertTrue(v['eco']);self.assertEqual(v['monitors'],{})
        with self.assertRaises(ValueError):st.validate(dict(st.DEFAULTS,speed=float('nan')))
        with self.assertRaises(ValueError):st.validate(dict(st.DEFAULTS,direction='unknown'))
        self.assertEqual(st.validate(dict(st.DEFAULTS,mode='phrases',characters='SELECT * FROM users;\nёб твою мать'))['characters'],'SELECT * FROM users;\nёб твою мать')

    def test_profile_retains_images_and_monitor_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'original.jpg';Image.new('RGB',(64,40),'red').save(image)
            with patch.multiple(st,BASE=root,CONFIG=root/'settings.json',PROFILES=root/'profiles.json',SOURCE=root/'source.png'):
                value=st.validate(dict(st.DEFAULTS,image=str(image),monitors={'HDMI':dict(st.DEFAULTS,image=str(image),direction='left')}))
                st.store_profile('Профиль ★',value);image.unlink()
                profile=st.load_profiles()['Профиль ★'];self.assertTrue(Path(profile['image']).exists())
                st.activate_profile('Профиль ★')
                self.assertEqual(st.load()['monitors']['HDMI']['direction'],'left')
                self.assertTrue(st.source_path('HDMI').exists())

    def test_monitor_crop_for_adjacent_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=Image.new('RGB',(256,128),'red');image.paste('blue',(128,0,256,128))
            raw=image.tobytes('raw','BGRX');frame=MagicMock();frame.id=42
            frame.composite_name_window_pixmap.return_value.get_image.return_value.data=raw
            desk=object.__new__(rt.Desktop);desk.frames=lambda:[(frame,0,0,256,128)]
            result=MagicMock(returncode=0,stdout='2\n')
            layout=[{'name':'left','x':0,'y':0,'width':128,'height':128},{'name':'right','x':128,'y':0,'width':128,'height':128}]
            with patch.object(rt,'CACHE',root),patch.object(rt,'source_path',lambda n:root/(n+'.png')),patch.object(rt.subprocess,'run',return_value=result),patch.object(rt.time,'sleep'):
                captures=desk.capture(layout)
            self.assertEqual(Image.open(captures['left'][0]).getpixel((40,40)),(255,0,0))
            self.assertEqual(Image.open(captures['right'][0]).getpixel((40,40)),(0,0,255))
            self.assertEqual(captures['right'][2:],(128,0))

    def test_manager_rebuilds_workers_on_monitor_disconnect(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=root/'source.png';Image.new('RGB',(100,100),'white').save(source)
            manager=object.__new__(rt.Manager);manager.workers={};manager.layout=[]
            manager.desktop=MagicMock()
            manager.desktop.capture.side_effect=lambda layout:{m['name']:('baseline.png',42,m['x'],m['y']) for m in layout}
            first={'name':'left','x':0,'y':0,'width':100,'height':100}
            second={'name':'right','x':100,'y':0,'width':100,'height':100}
            values=st.validate(dict(st.DEFAULTS,image=str(source),monitors={'right':dict(st.DEFAULTS,image=str(source),foreground='#ff0000')}))
            children=[]
            def child(*args,**kwargs):
                process=MagicMock();process.poll.return_value=None;process.pid=100+len(children);children.append(process);return process
            with patch.object(rt,'CACHE',root),patch.object(rt,'RUNTIME',root),patch.object(rt,'source_path',lambda monitor=None:source),patch.object(rt,'load',return_value=values),patch.object(rt.subprocess,'Popen',side_effect=child) as popen:
                manager.rebuild([first,second])
                self.assertEqual(set(manager.workers),{'left','right'})
                self.assertEqual(popen.call_args_list[1].kwargs['env']['MATRIX_X'],'100')
                self.assertEqual(popen.call_args_list[1].kwargs['env']['MATRIX_FOREGROUND'],'#ff0000')
                manager.rebuild([first])
                self.assertEqual(set(manager.workers),{'left'})
                self.assertEqual(len(manager.retiring),1)
                self.assertFalse(children[0].terminate.called)
                manager.stop_workers()
                self.assertTrue(children[0].terminate.called);self.assertTrue(children[1].terminate.called)

    def test_export_dimensions_frame_count_and_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'image.png';Image.new('RGB',(100,100),'cyan').save(image)
            output=root/'video.mp4';v=st.validate(dict(st.DEFAULTS,direction='left',color_mode='rainbow',reveal='cycle'))
            export_video(v,image,output,160,90,10,2)
            data=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=width,height,nb_frames','-of','json',str(output)],text=True))['streams'][0]
            self.assertEqual((data['width'],data['height'],int(data['nb_frames'])),(160,90,20))
            before=output.read_bytes();cancel=threading.Event();cancel.set()
            with self.assertRaises(InterruptedError):export_video(v,image,output,320,180,20,20,cancel)
            self.assertEqual(output.read_bytes(),before);self.assertFalse(list(root.glob('*.part.mp4')))

if __name__=='__main__':unittest.main(verbosity=2)

"""Regression coverage for portable bundles, audio, schedules and both backends."""
from datetime import datetime
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import numpy as np
from PIL import Image
import settings as st
import portable
import schedule
from audio import AudioAnalyzer

class V3Tests(unittest.TestCase):
    def test_matrix_preset_preserves_picture_and_resource_limits(self):
        original=st.validate(dict(st.DEFAULTS,image='/tmp/my-picture.jpg',zoom=2.3,pan_x=-.25,focus_mask='/tmp/subject.png',fps=9,eco=True,cpu_limit=7,battery_fps=3,monitors={'HDMI':dict(st.DEFAULTS,image='/tmp/other.png')}))
        before=json.loads(json.dumps(original))
        result=st.matrix_settings(original)
        self.assertEqual(original,before)
        for key in ('image','zoom','pan_x','pan_y','focus_mask','focus_strength','fps','eco','cpu_limit','auto_limit','battery_fps','pause_hidden','pause_locked','monitors'):
            self.assertEqual(result[key],original[key],key)
        for key,value in st.MATRIX_LOOK.items():self.assertEqual(result[key],value,key)
        self.assertEqual(result['glyph_direction'],'down')
        self.assertEqual(result['reveal'],'reveal')
        self.assertIn('ｱ',result['characters'])
        self.assertGreaterEqual(result['tail'],20)

    def test_matrix_preset_renders_on_both_backends(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'image.png';Image.new('RGB',(160,90),'white').save(path)
            for backend in ('cpu','gpu'):
                frames=self.render(path,backend,**st.MATRIX_LOOK)
                self.assertGreater(frames[:,:,:,1].mean(),frames[:,:,:,0].mean())
                self.assertFalse(np.array_equal(frames[0],frames[-1]))

    def test_adaptive_fps_feedback(self):
        from runtime import feedback_rate
        self.assertEqual(feedback_rate(20,20,50,25),16)
        self.assertEqual(feedback_rate(20,10,5,25,True),11)
        self.assertEqual(feedback_rate(20,3,100,25),3)
        self.assertEqual(feedback_rate(8,20,0,25),8)

    def test_audio_bass_and_silence(self):
        samples=np.arange(4096)/22050
        bass=(.2*np.sin(2*np.pi*80*samples)).astype('<f4').tobytes()
        treble=(.2*np.sin(2*np.pi*2000*samples)).astype('<f4').tobytes()
        low=AudioAnalyzer.analyze(bass);high=AudioAnalyzer.analyze(treble)
        self.assertGreater(low[1],high[1]*10)
        self.assertEqual(AudioAnalyzer.analyze(bytes(4096)),(0,0))
        self.assertLessEqual(low[0],1)

    def test_schedule_midnight_and_duplicates(self):
        data={'enabled':True,'entries':[{'time':'08:00','profile':'утро'},{'time':'20:00','profile':'вечер'}]}
        self.assertEqual(schedule.due(data,datetime(2026,11,16,9))[1],'утро')
        self.assertEqual(schedule.due(data,datetime(2026,11,16,2)),('2026-11-15:20:00:вечер','вечер'))
        with patch.object(schedule,'load_profiles',return_value={'утро':{}}):
            with self.assertRaises(ValueError):schedule.save_schedule({'enabled':True,'entries':[{'time':'99:00','profile':'утро'}]})
            with self.assertRaises(ValueError):schedule.save_schedule({'enabled':True,'entries':[]})

    def test_bundle_roundtrip_with_mask_and_rename(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);image=root/'photo.jpg';mask=root/'mask.png';Image.new('RGB',(64,48),'red').save(image);Image.new('RGB',(64,48),'white').save(mask)
            with patch.multiple(st,BASE=root,CONFIG=root/'settings.json',PROFILES=root/'profiles.json',SOURCE=root/'source.png'),patch.object(portable,'BASE',root):
                values=st.validate(dict(st.DEFAULTS,image=str(image),focus_mask=str(mask),zoom=2,layers=3))
                portable.export_bundle(values,'Мой профиль',root/'profile.mwp');image.unlink();mask.unlink()
                name=portable.import_bundle(root/'profile.mwp');self.assertEqual(name,'Мой профиль')
                profile=st.load_profiles()[name]
                self.assertTrue(Path(profile['image']).exists());self.assertTrue(Path(profile['focus_mask']).exists());self.assertEqual(profile['layers'],3)
                self.assertEqual(portable.import_bundle(root/'profile.mwp'),'Мой профиль (2)')

    def test_bundle_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'bad.mwp'
            with zipfile.ZipFile(path,'w') as archive:archive.writestr('../bad.txt','bad')
            with self.assertRaises(ValueError):portable.import_bundle(path)
            self.assertFalse((Path(folder).parent/'bad.txt').exists())

    def render(self,image,backend,**overrides):
        values=st.validate(st.DEFAULTS | dict(image=str(image),characters='X',size=12,color_mode='source',reveal='steady') | overrides)
        env=st.environment(values);env.update(MATRIX_EXPORT='1',MATRIX_WIDTH='160',MATRIX_HEIGHT='90',MATRIX_FPS='5',MATRIX_DURATION='1',MATRIX_BACKEND=backend)
        result=subprocess.run([str(st.BASE/'renderer'),str(image),'-','0'],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
        self.assertEqual(len(result.stdout),160*90*4*5)
        pixels=np.frombuffer(result.stdout,dtype=np.uint8).reshape(5,90,160,4)
        self.assertGreater(pixels[:,:,:,:3].max(),0)
        if backend=='gpu':self.assertIn(b'GPU backend:',result.stderr)
        return pixels

    def test_symbol_motion_can_stop_and_move_independently(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'white.png';Image.new('RGB',(160,90),'white').save(path)
            stable=dict(characters='01AB',foreground='#ffffff',highlight='#ffffff',color_mode='mono',brightness=2)
            for backend in ('cpu','gpu'):
                stopped=self.render(path,backend,**stable,glyph_direction='none',glyph_speed=8)
                for frame in stopped[1:]:self.assertTrue(np.array_equal(stopped[0],frame),backend)
                zero=self.render(path,backend,**stable,glyph_direction='right',glyph_speed=0)
                for frame in zero[1:]:self.assertTrue(np.array_equal(zero[0],frame),backend)
                for direction in ('left','right','up','down'):
                    moved=self.render(path,backend,**stable,glyph_direction=direction,glyph_speed=1)
                    self.assertFalse(np.array_equal(moved[0],moved[1]),(backend,direction))
                    if direction in ('left','right'):
                        expected=np.roll(moved[0],-32 if direction=='left' else 32,axis=1)
                        self.assertTrue(np.array_equal(expected,moved[1]),(backend,direction))
                phrases=self.render(path,backend,**(stable | dict(characters='SELECT * FROM users;\nUPDATE users SET active = TRUE;',mode='phrases',glyph_direction='none')))
                for frame in phrases[1:]:self.assertTrue(np.array_equal(phrases[0],frame),(backend,'phrases'))

    def test_cycle_has_visible_first_and_midpoint_frames(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.png';Image.new('RGB',(160,90),'white').save(path)
            for backend in ('cpu','gpu'):
                frames=self.render(path,backend,reveal='cycle')
                self.assertGreater(frames[0,:,:,:3].mean(),1)
                self.assertGreater(frames[2,:,:,:3].mean(),.1)

    def test_gpu_and_cpu_composition_and_layers(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'source.png';image=Image.new('RGB',(320,90),'red');image.paste('blue',(160,0,320,90));image.save(path)
            for backend in ('cpu','gpu'):
                left=self.render(path,backend,zoom=2,pan_x=-1)
                right=self.render(path,backend,zoom=2,pan_x=1)
                self.assertGreater(left[:,:,:,2].mean(),left[:,:,:,0].mean())
                self.assertGreater(right[:,:,:,0].mean(),right[:,:,:,2].mean())
                layers=self.render(path,backend,layers=3,depth=1)
                one=self.render(path,backend,layers=1,depth=1)
                self.assertFalse(np.array_equal(layers,one))

if __name__=='__main__':unittest.main(verbosity=2)

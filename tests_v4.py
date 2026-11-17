"""Desktop layer regression checks; no mouse events or real desktop files changed."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock,patch
import numpy as np
from PIL import Image
import runtime as rt
from desktop_layer import rectangle,icon_hit,DesktopPointer

class DesktopLayerTests(unittest.TestCase):
    def test_rectangle_in_all_drag_directions(self):
        for a,b in [((10,20),(80,100)),((80,100),(10,20)),((10,100),(80,20)),((80,20),(10,100))]:
            self.assertEqual(rectangle(a,b),(10,20,70,80))
        self.assertEqual(rectangle((0,0),(0,0)),(0,0,0,0))

    def test_icon_hit_uses_shared_alpha(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'icons.argb';data=np.zeros((20,20,4),dtype=np.uint8);data[7,5,3]=255;path.write_bytes(data.tobytes())
            self.assertTrue(icon_hit(path,20,20,5,7,padding=0))
            self.assertFalse(icon_hit(path,20,20,15,17,padding=0))
            self.assertFalse(icon_hit(path,20,20,-1,7,padding=0))
            self.assertFalse(icon_hit(path.with_name('missing'),20,20,5,7))

    def test_pointer_only_targets_desktop_windows(self):
        root=MagicMock();window=MagicMock();window.query_tree.return_value.children=[]
        for name in ('MatrixWallpaper','xfdesktop','Xfdesktop'):
            window.get_wm_class.return_value=(name,)
            self.assertTrue(DesktopPointer.desktop_window(window,root))
        window.get_wm_class.return_value=('Thunar',)
        self.assertFalse(DesktopPointer.desktop_window(window,root))
        self.assertTrue(DesktopPointer.desktop_window(0,root))

    def test_cached_background_never_hides_icons_on_profile_change(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);frame=MagicMock();frame.id=42
            image=Image.new('RGB',(120,80),'navy')
            frame.composite_name_window_pixmap.return_value.get_image.return_value.data=image.tobytes('raw','BGRX')
            desk=object.__new__(rt.Desktop);desk.frames=lambda:[(frame,0,0,120,80)]
            result=MagicMock(returncode=0,stdout='2\n')
            layout=[dict(name='eDP',x=0,y=0,width=120,height=80)]
            with patch.object(rt,'CACHE',root),patch.object(rt,'source_path',lambda name:root/(name+'.png')),patch.object(rt.subprocess,'run',return_value=result) as run,patch.object(rt.time,'sleep'):
                first=desk.capture(layout);original=Path(first['eDP'][0]).read_bytes()
                run.reset_mock();frame.id=77
                second=desk.capture(layout)
                self.assertEqual(second['eDP'][1],77)
                self.assertEqual(Path(second['eDP'][0]).read_bytes(),original)
                self.assertFalse(any('-s' in c.args[0] for c in run.call_args_list))
                # A damaged cache recovers rather than permanently hiding the desktop.
                Path(second['eDP'][0]).write_bytes(b'broken')
                run.reset_mock();desk.capture(layout)
                self.assertTrue(any(c.args[0][-2:]==['-s','0'] for c in run.call_args_list))
                self.assertEqual(run.call_args_list[-1].args[0][-2:],['-s','2'])

if __name__=='__main__':unittest.main(verbosity=2)

"""Interactive crop, pan, zoom and foreground mask painting."""
from i18n import tr
from pathlib import Path
import uuid
import gi
gi.require_version('Gtk','3.0')
from gi.repository import Gtk,Gdk,GdkPixbuf,GLib
from PIL import Image,ImageOps,ImageDraw
from settings import BASE
from help_ui import tip, button_tips

def pixbuf(image):
    image=image.convert('RGBA');w,h=image.size
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(image.tobytes()),GdkPixbuf.Colorspace.RGB,True,8,w,h,w*4)

class Composition(Gtk.Dialog):
    def __init__(self,parent,source,values,ratio=16/9):
        super().__init__(title=tr('Кадрирование и выделение объекта'),transient_for=parent,modal=True)
        self.add_buttons(tr('Отмена'),Gtk.ResponseType.CANCEL,tr('Сохранить'),Gtk.ResponseType.OK)
        self.set_default_size(850,650)
        self.values=values.copy();self.image=ImageOps.exif_transpose(Image.open(source)).convert('RGB');self.image.thumbnail((1920,1920))
        self.mask=Image.new('L',self.image.size,0)
        path=values.get('focus_mask')
        if path and Path(path).exists():self.mask=Image.open(path).convert('L').resize(self.image.size)
        self.image_buffer=pixbuf(self.image);self.mask_buffer=None;self.undo=[];self.pressed=False;self.last=None
        content=self.get_content_area();content.set_border_width(12);content.set_spacing(12)
        toolbar=Gtk.Box(spacing=10)
        self.tool=Gtk.ComboBoxText()
        for key,text in [('drag',tr('Переместить картинку')),('paint',tr('Выделить объект кистью')),('erase',tr('Стереть выделение'))]:self.tool.append(key,text)
        self.tool.set_active_id('drag');toolbar.pack_start(self.tool,False,False,0)
        self.tool.set_tooltip_text(tr('Выберите действие левой кнопки: двигать кадр, отмечать главный объект или стирать маску. Красная маска видна только в редакторе.'))
        for text,callback in [(tr('Отменить мазок'),self.undo_stroke),(tr('Очистить'),self.clear),(tr('Сбросить кадр'),self.reset_crop)]:
            b=Gtk.Button(label=text);b.connect('clicked',callback);toolbar.pack_start(b,False,False,0)
        content.pack_start(toolbar,False,False,0)
        self.area=Gtk.DrawingArea();self.area.set_size_request(720,360)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK|Gdk.EventMask.BUTTON_RELEASE_MASK|Gdk.EventMask.POINTER_MOTION_MASK|Gdk.EventMask.SCROLL_MASK)
        self.area.connect('draw',self.draw);self.area.connect('button-press-event',self.press);self.area.connect('motion-notify-event',self.move);self.area.connect('button-release-event',self.release);self.area.connect('scroll-event',self.scroll)
        frame=Gtk.AspectFrame(ratio=ratio,obey_child=False);frame.add(self.area);content.pack_start(frame,True,True,0)
        self.sliders={}
        for key,label,low,high,step,default in [('zoom',tr('Масштаб'),1,5,.05,1),('pan_x',tr('Положение по горизонтали'),-1,1,.02,0),('pan_y',tr('Положение по вертикали'),-1,1,.02,0),('brush',tr('Размер кисти'),5,120,1,35)]:
            row=Gtk.Box(spacing=10);row.pack_start(Gtk.Label(label=label,xalign=0),False,False,0)
            scale=Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL,low,high,step);scale.set_digits(0 if key=='brush' else 2);scale.set_value(values.get(key,default));scale.connect('value-changed',lambda *_:self.area.queue_draw());row.pack_start(scale,True,True,0);self.sliders[key]=scale;content.pack_start(row,False,False,0)
            tip(scale,key)
        hint=Gtk.Label(label=tr('Красная область — главный объект: его детали сохраняются, фон сильнее растворяется в символах. Картинку можно двигать мышью, масштаб — колесом.'),xalign=0);hint.set_line_wrap(True);content.pack_start(hint,False,False,0)
        button_tips(self)
        self.area.set_tooltip_text(tr('Тяните левой кнопкой, чтобы выполнить выбранное действие. Колесо приближает или отдаляет картинку. Исходный файл не изменяется.'))
        self.show_all()
    def transform(self):
        w,h=self.area.get_allocated_width(),self.area.get_allocated_height();iw,ih=self.image.size
        scale=max(w/iw,h/ih)*self.sliders['zoom'].get_value()
        return scale,(w-iw*scale)/2*(1+self.sliders['pan_x'].get_value()),(h-ih*scale)/2*(1+self.sliders['pan_y'].get_value())
    def draw(self,area,cr):
        cr.set_source_rgb(0,0,0);cr.paint();scale,x,y=self.transform();cr.save();cr.translate(x,y);cr.scale(scale,scale);Gdk.cairo_set_source_pixbuf(cr,self.image_buffer,0,0);cr.paint()
        if self.mask_buffer is None:
            overlay=Image.new('RGBA',self.mask.size,(255,55,65,0));overlay.putalpha(self.mask.point(lambda n:int(n*.38)));self.mask_buffer=pixbuf(overlay)
        Gdk.cairo_set_source_pixbuf(cr,self.mask_buffer,0,0);cr.paint();cr.restore();return False
    def press(self,area,event):
        if event.button!=1:return False
        self.pressed=True;self.last=(event.x,event.y)
        if self.tool.get_active_id()!='drag':
            self.undo.append(self.mask.copy());self.undo=self.undo[-15:];self.paint(event.x,event.y,event.x,event.y)
        return True
    def move(self,area,event):
        if not self.pressed:return False
        old=self.last;self.last=(event.x,event.y)
        if self.tool.get_active_id()=='drag':
            scale,x,y=self.transform();w,h=self.area.get_allocated_width(),self.area.get_allocated_height();iw,ih=self.image.size
            for key,delta,excess in [('pan_x',event.x-old[0],iw*scale-w),('pan_y',event.y-old[1],ih*scale-h)]:
                if excess>1:self.sliders[key].set_value(self.sliders[key].get_value()-2*delta/excess)
        else:self.paint(*old,event.x,event.y)
        self.area.queue_draw();return True
    def paint(self,x1,y1,x2,y2):
        scale,ox,oy=self.transform();radius=self.sliders['brush'].get_value()/scale
        a=((x1-ox)/scale,(y1-oy)/scale);b=((x2-ox)/scale,(y2-oy)/scale);color=0 if self.tool.get_active_id()=='erase' else 255
        pen=ImageDraw.Draw(self.mask);pen.line([a,b],fill=color,width=max(1,int(radius*2)))
        for x,y in (a,b):pen.ellipse((x-radius,y-radius,x+radius,y+radius),fill=color)
        self.mask_buffer=None;self.area.queue_draw()
    def release(self,*_):self.pressed=False;return False
    def scroll(self,area,event):
        delta=.1 if event.direction==Gdk.ScrollDirection.UP else -.1
        self.sliders['zoom'].set_value(self.sliders['zoom'].get_value()+delta);return True
    def undo_stroke(self,*_):
        if self.undo:self.mask=self.undo.pop();self.mask_buffer=None;self.area.queue_draw()
    def clear(self,*_):
        self.undo.append(self.mask.copy());self.mask=Image.new('L',self.image.size);self.mask_buffer=None;self.area.queue_draw()
    def reset_crop(self,*_):
        for key,value in [('zoom',1),('pan_x',0),('pan_y',0)]:self.sliders[key].set_value(value)
    def result(self):
        result={key:self.sliders[key].get_value() for key in ('zoom','pan_x','pan_y')}
        result['focus_mask']=''
        if self.mask.getbbox():
            folder=BASE/'masks';folder.mkdir(exist_ok=True);path=folder/(uuid.uuid4().hex+'.png');self.mask.convert('RGB').save(path);result['focus_mask']=str(path)
        return result

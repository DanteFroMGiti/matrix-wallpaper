#define _DEFAULT_SOURCE
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <X11/Xutil.h>
#include <X11/extensions/shape.h>
#include <X11/extensions/Xcomposite.h>
#include <cairo/cairo.h>
#include <cairo/cairo-xlib.h>
#include <pango/pangocairo.h>
#include <math.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include "gpu.h"

static volatile sig_atomic_t running=1;
static volatile sig_atomic_t interaction_dirty=0;
static void wake_frame(int sig){(void)sig;interaction_dirty=1;}
static int selection_rect(Display*d,Window root,int ox,int oy,int rect[4]){
 Atom type;int format;unsigned long n,left;unsigned char*data=NULL;
 int result=0;
 if(XGetWindowProperty(d,root,XInternAtom(d,"_MATRIX_WALLPAPER_SELECTION",False),0,5,False,XA_CARDINAL,&type,&format,&n,&left,&data)==Success&&data&&format==32&&n==5){
  unsigned long*v=(unsigned long*)data;
  if(v[0]){rect[0]=(int)v[1]-ox;rect[1]=(int)v[2]-oy;rect[2]=(int)v[3];rect[3]=(int)v[4];result=rect[2]>0&&rect[3]>0;}
 }
 if(data){XFree(data);}
 return result;
}
static double clamp(double v,double lo,double hi){return fmax(lo,fmin(hi,v));}
static double smooth(double v){v=clamp(v,0,1);return v*v*(3-2*v);}
static void rainbow(double phase,double rgb[3]){
 for(int i=0;i<3;i++)rgb[i]=clamp(fabs(fmod(phase*6+6+(i==0?0:i==1?4:2),6)-3)-1,0,1);
}
static void stop(int sig){(void)sig; running=0;}
static double now(void){struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return t.tv_sec+t.tv_nsec/1e9;}
static Atom atom(Display*d,const char*n){return XInternAtom(d,n,False);}
static void prop(Display*d,Window w,const char*n,Atom type,unsigned long*v,int count){XChangeProperty(d,w,atom(d,n),type,32,PropModeReplace,(unsigned char*)v,count);}
static int xerror(Display*d,XErrorEvent*e){char s[160];XGetErrorText(d,e->error_code,s,sizeof s);fprintf(stderr,"X11: %s\n",s);return 0;}
/* Xfwm reparents desktop windows into its own full-screen frame. Both the
 * client and that frame must have empty input regions to pass clicks through. */
static void pass_pointer(Display*d,Window win,Window root){
 Window current=win;
 while(current!=root && current!=None){
  XShapeCombineRectangles(d,current,ShapeInput,0,0,NULL,0,ShapeSet,Unsorted);
  Window actual_root,parent,*children=NULL;unsigned int count=0;
  if(!XQueryTree(d,current,&actual_root,&parent,&children,&count))break;
  if(children)XFree(children);
  current=parent;
 }
}
static double setting(const char *name,double fallback,double low,double high){
 const char *v=getenv(name);double n=v?strtod(v,NULL):fallback;
 return isfinite(n)?fmax(low,fmin(high,n)):fallback;
}
static void color(const char *name,const char *fallback,double rgb[3]){
 const char *s=getenv(name);unsigned int r,g,b;
 if(!s||strlen(s)!=7||sscanf(s,"#%2x%2x%2x",&r,&g,&b)!=3)sscanf(fallback,"#%2x%2x%2x",&r,&g,&b);
 rgb[0]=r/255.;rgb[1]=g/255.;rgb[2]=b/255.;
}
static void phrase_row(int *chars,int row,int cols,int phrases[128][512],int *lengths,int count){
 int x=0;
 while(x<cols){int p=rand()%count;
  for(int i=0;i<lengths[p]&&x<cols;i++)chars[row*cols+x++]=phrases[p][i];
  for(int i=0;i<3&&x<cols;i++)chars[row*cols+x++]=0;
 }
}
int main(int argc,char**argv){
 if(argc!=4){fprintf(stderr,"renderer IMAGE BASELINE DESKTOP_FRAME\n");return 1;}
 signal(SIGTERM,stop);signal(SIGINT,stop);signal(SIGUSR1,wake_frame);XSetErrorHandler(xerror);
 Display*d=XOpenDisplay(NULL);if(!d)return 1;int sc=DefaultScreen(d);Window root=RootWindow(d,sc);int w=DisplayWidth(d,sc),h=DisplayHeight(d,sc);
 int preview=getenv("MATRIX_PREVIEW")!=NULL, exporting=getenv("MATRIX_EXPORT")!=NULL;
 int ox=setting("MATRIX_X",0,0,32768),oy=setting("MATRIX_Y",0,0,32768);
 int capture_x=setting("MATRIX_CAPTURE_X",0,0,32768),capture_y=setting("MATRIX_CAPTURE_Y",0,0,32768);
 w=setting("MATRIX_WIDTH",w,64,16384);h=setting("MATRIX_HEIGHT",h,64,16384);
 double fps=setting("MATRIX_FPS",20,3,60),duration=setting("MATRIX_DURATION",8,1,300),tail=setting("MATRIX_TAIL",22,3,70),density=setting("MATRIX_DENSITY",1,.1,1),cycle=setting("MATRIX_CYCLE",16,6,60);
 const char *dir=getenv("MATRIX_DIRECTION"),*cm=getenv("MATRIX_COLOR_MODE"),*reveal=getenv("MATRIX_REVEAL");
 const char*glyph_dir=getenv("MATRIX_GLYPH_DIRECTION");
 int glyph_direction=!glyph_dir||!strcmp(glyph_dir,"none")?0:!strcmp(glyph_dir,"left")?1:!strcmp(glyph_dir,"right")?2:!strcmp(glyph_dir,"up")?3:4;
 double glyph_speed=setting("MATRIX_GLYPH_SPEED",1,0,8);
 int horizontal=dir&&(!strcmp(dir,"left")||!strcmp(dir,"right"));
 int reverse=dir&&(!strcmp(dir,"left")||!strcmp(dir,"up"));
 int color_mode=!cm||!strcmp(cm,"mono")?0:!strcmp(cm,"source")?1:!strcmp(cm,"gradient")?2:3;
 int reveal_mode=!reveal||!strcmp(reveal,"reveal")?1:!strcmp(reveal,"cycle")?2:0;
 int random_speed=!getenv("MATRIX_RANDOM_SPEED")||strcmp(getenv("MATRIX_RANDOM_SPEED"),"False");
 Window frame=strtoul(argv[3],NULL,0);
 if(preview){XWindowAttributes pa;if(!XGetWindowAttributes(d,frame,&pa))return 1;w=pa.width;h=pa.height;}
 double fg[3],bg[3],hi[3];color("MATRIX_FOREGROUND","#2bff59",fg);color("MATRIX_BACKGROUND","#000000",bg);color("MATRIX_HIGHLIGHT","#bcffd2",hi);
 double tempo=setting("MATRIX_SPEED",1,.2,3),gain=setting("MATRIX_BRIGHTNESS",1,.3,2),contrast=setting("MATRIX_CONTRAST",1,.5,2);
 double zoom=setting("MATRIX_ZOOM",1,1,5),pan_x=setting("MATRIX_PAN_X",0,-1,1),pan_y=setting("MATRIX_PAN_Y",0,-1,1);
 double focus_strength=0,depth=setting("MATRIX_DEPTH",.5,0,1),music_amount=setting("MATRIX_MUSIC_AMOUNT",.15,0,.3),fade=setting("MATRIX_FADE_SECONDS",0,0,8);
 int layers=setting("MATRIX_LAYERS",1,1,3),music=getenv("MATRIX_MUSIC")&&!strcmp(getenv("MATRIX_MUSIC"),"True");
 int font_size=setting("MATRIX_SIZE",12,8,32);
 int original_font_size=font_size;
 if(preview)font_size=fmax(5,font_size*w/(double)DisplayWidth(d,sc));
 char alphabet[256][8];gunichar codepoints[256];int count=0;
 int phrase_mode=getenv("MATRIX_MODE")&&strcmp(getenv("MATRIX_MODE"),"phrases")==0;
 int phrase_indices[128][512],phrase_lengths[128],phrase_count=0;
 if(phrase_mode){strcpy(alphabet[0]," ");codepoints[0]=' ';count=1;}
 const char *text=getenv("MATRIX_CHARACTERS");if(!text||!*text)text="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz#$";
 if(!g_utf8_validate(text,-1,NULL)){fprintf(stderr,"Invalid UTF-8 characters\n");return 1;}
 for(const char *c=text;*c;c=g_utf8_next_char(c)){
  gunichar cp=g_utf8_get_char(c);if(cp=='\n'||cp=='\r')continue;
  int exists=0;for(int i=0;i<count;i++)if(codepoints[i]==cp)exists=1;
  int len=g_utf8_next_char(c)-c;
  if(!exists&&count<256&&len>0&&len<8){memcpy(alphabet[count],c,len);alphabet[count][len]=0;codepoints[count]=cp;count++;}
 }
 if(phrase_mode){
  gchar **lines=g_strsplit(text,"\n",-1);
  for(int j=0;lines[j]&&phrase_count<128;j++){
   int n=0;for(const char *c=lines[j];*c&&n<512;c=g_utf8_next_char(c)){
    gunichar cp=g_utf8_get_char(c);for(int k=0;k<count;k++)if(codepoints[k]==cp){phrase_indices[phrase_count][n++]=k;break;}
   }if(n)phrase_lengths[phrase_count++]=n;
  }g_strfreev(lines);if(!phrase_count)return 1;
 }
 if(!count)return 1;
 cairo_surface_t*src=cairo_image_surface_create_from_png(argv[1]);
 cairo_surface_t*baseline=(preview||exporting)?cairo_image_surface_create(CAIRO_FORMAT_RGB24,w,h):cairo_image_surface_create_from_png(argv[2]);
 if(cairo_surface_status(src)||cairo_surface_status(baseline)){fprintf(stderr,"Cannot read image\n");return 1;}
 int sw=cairo_image_surface_get_width(src),sh=cairo_image_surface_get_height(src);
 cairo_surface_t*sample=cairo_image_surface_create(CAIRO_FORMAT_RGB24,w,h);cairo_t*cs=cairo_create(sample);
 double scale=fmax((double)w/sw,(double)h/sh)*zoom;
 double image_x=(w-sw*scale)/2*(1+pan_x),image_y=(h-sh*scale)/2*(1+pan_y);
 cairo_translate(cs,image_x,image_y);cairo_scale(cs,scale,scale);cairo_set_source_surface(cs,src,0,0);cairo_paint(cs);cairo_destroy(cs);cairo_surface_flush(sample);
 cairo_surface_t*focus=cairo_image_surface_create(CAIRO_FORMAT_RGB24,w,h);
 const char*focus_file=getenv("MATRIX_FOCUS_MASK");
 if(focus_file&&*focus_file){cairo_surface_t*f=cairo_image_surface_create_from_png(focus_file);
  if(cairo_surface_status(f)==CAIRO_STATUS_SUCCESS){cs=cairo_create(focus);cairo_translate(cs,image_x,image_y);cairo_scale(cs,scale*sw/cairo_image_surface_get_width(f),scale*sh/cairo_image_surface_get_height(f));cairo_set_source_surface(cs,f,0,0);cairo_paint(cs);cairo_destroy(cs);focus_strength=setting("MATRIX_FOCUS_STRENGTH",.7,0,1);}
  cairo_surface_destroy(f);
 }cairo_surface_flush(focus);

 const int cw=(int)ceil(font_size*2./3),ch=font_size,cols=(w+cw-1)/cw,rows=(h+ch-1)/ch;
 int streams=cols>rows?cols:rows;
 float*lum=calloc(cols*rows,sizeof(float));float*source_rgb=calloc(cols*rows*3,sizeof(float));int*chars=calloc(cols*rows,sizeof(int));double*speed=calloc(streams,sizeof(double));double*delay=calloc(streams,sizeof(double));
 uint32_t*p=(uint32_t*)cairo_image_surface_get_data(sample);int stride=cairo_image_surface_get_stride(sample)/4;
 srand(exporting?42:time(NULL));
 for(int i=0;i<streams;i++){
  speed[i]=(random_speed?(15+(rand()%150)/10.):22.5)*tempo*(preview?w/(double)DisplayWidth(d,sc)*original_font_size/font_size:1);
  if(exporting)speed[i]=(horizontal?cols+tail:rows+tail)*fmax(1,round(speed[i]*duration/(horizontal?cols+tail:rows+tail)))/duration;
  delay[i]=(rand()%160)/100.;
 }
 for(int x=0;x<cols;x++){for(int y=0;y<rows;y++){
   double val=0,red=0,green=0,blue=0;int n=0;for(int yy=y*ch;yy<(y+1)*ch&&yy<h;yy+=3)for(int xx=x*cw;xx<(x+1)*cw&&xx<w;xx+=2){uint32_t c=p[yy*stride+xx];red+=(c>>16)&255;green+=(c>>8)&255;blue+=c&255;val+=.2126*((c>>16)&255)+.7152*((c>>8)&255)+.0722*(c&255);n++;}
   source_rgb[(y*cols+x)*3]=red/(255*n);source_rgb[(y*cols+x)*3+1]=green/(255*n);source_rgb[(y*cols+x)*3+2]=blue/(255*n);
   lum[y*cols+x]=fmax(0,fmin(1,(pow(val/(255*n),.78)-.5)*contrast+.5));chars[y*cols+x]=rand()%count;
 }}
 cairo_surface_destroy(src);
 if(phrase_mode)for(int y=0;y<rows;y++)phrase_row(chars,y,cols,phrase_indices,phrase_lengths,phrase_count);
 cairo_surface_t*atlas=cairo_image_surface_create(CAIRO_FORMAT_RGB24,count*cw,40*ch);cairo_t*ac=cairo_create(atlas);
 cairo_set_source_rgb(ac,bg[0],bg[1],bg[2]);cairo_paint(ac);
 PangoLayout *layout=pango_cairo_create_layout(ac);
 PangoFontDescription *font=pango_font_description_from_string("Monospace Bold");
 pango_font_description_set_absolute_size(font,font_size*.92*PANGO_SCALE);
 pango_layout_set_font_description(layout,font);pango_font_description_free(font);
 for(int b=0;b<40;b++){
  double v=fmin(1,b/31.),head=fmax(0,(b-31)/8.);
  double rgb[3];for(int z=0;z<3;z++)rgb[z]=bg[z]*(1-v)+(fg[z]*(1-head)+hi[z]*head)*v;
  for(int k=0;k<count;k++){
   pango_layout_set_text(layout,alphabet[k],-1);int tw,th;pango_layout_get_pixel_size(layout,&tw,&th);
   cairo_save(ac);cairo_rectangle(ac,k*cw,b*ch,cw,ch);cairo_clip(ac);
   cairo_set_source_rgb(ac,rgb[0],rgb[1],rgb[2]);cairo_move_to(ac,k*cw+(cw-tw)/2.,b*ch+(ch-th)/2.);
   pango_cairo_show_layout(ac,layout);cairo_restore(ac);
  }
 }
 g_object_unref(layout);cairo_destroy(ac);
 cairo_surface_t*mask=cairo_image_surface_create(CAIRO_FORMAT_A8,count*cw,ch);cairo_t*mc=cairo_create(mask);
 layout=pango_cairo_create_layout(mc);font=pango_font_description_from_string("Monospace Bold");pango_font_description_set_absolute_size(font,font_size*.92*PANGO_SCALE);pango_layout_set_font_description(layout,font);pango_font_description_free(font);
 cairo_set_source_rgba(mc,1,1,1,1);
 for(int k=0;k<count;k++){pango_layout_set_text(layout,alphabet[k],-1);int tw,th;pango_layout_get_pixel_size(layout,&tw,&th);cairo_save(mc);cairo_rectangle(mc,k*cw,0,cw,ch);cairo_clip(mc);cairo_move_to(mc,k*cw+(cw-tw)/2.,(ch-th)/2.);pango_cairo_show_layout(mc,layout);cairo_restore(mc);}g_object_unref(layout);cairo_destroy(mc);
 XSetWindowAttributes attrs={0};attrs.background_pixel=BlackPixel(d,sc);attrs.event_mask=StructureNotifyMask|ExposureMask;
 Window win=None;
 if(!exporting)win=XCreateWindow(d,preview?frame:root,preview?0:ox,preview?0:oy,w,h,0,CopyFromParent,InputOutput,CopyFromParent,CWBackPixel|CWEventMask,&attrs);
 if(!preview&&!exporting){
 XStoreName(d,win,"Matrix image wallpaper");XClassHint cls={"matrix-wallpaper","MatrixWallpaper"};XSetClassHint(d,win,&cls);
 unsigned long v=atom(d,"_NET_WM_WINDOW_TYPE_DESKTOP");prop(d,win,"_NET_WM_WINDOW_TYPE",XA_ATOM,&v,1);
 unsigned long states[]={atom(d,"_NET_WM_STATE_BELOW"),atom(d,"_NET_WM_STATE_SKIP_TASKBAR"),atom(d,"_NET_WM_STATE_SKIP_PAGER"),atom(d,"_NET_WM_STATE_STICKY")};prop(d,win,"_NET_WM_STATE",XA_ATOM,states,4);
 v=0xffffffff;prop(d,win,"_NET_WM_DESKTOP",XA_CARDINAL,&v,1);
 XWMHints hints={0};hints.flags=InputHint;hints.input=False;XSetWMHints(d,win,&hints);
 /* This window has no children: the empty input region passes all pointer events to XFCE. */
 XShapeCombineRectangles(d,win,ShapeInput,0,0,NULL,0,ShapeSet,Unsorted);
 }
 cairo_surface_t*screen=NULL;
 if(!exporting){if(!preview){unsigned long opacity=0;prop(d,win,"_NET_WM_WINDOW_OPACITY",XA_CARDINAL,&opacity,1);}XMapWindow(d,win);XFlush(d);
 if(!preview){
  for(int i=0;i<30;i++){
   pass_pointer(d,win,root);Window rr,pp,*cc=NULL;unsigned int nn=0;XQueryTree(d,win,&rr,&pp,&cc,&nn);if(cc)XFree(cc);
   if(pp!=root){break;}
   usleep(2000);
  }
 }
 XWindowAttributes actual;XGetWindowAttributes(d,win,&actual);screen=cairo_xlib_surface_create(d,win,actual.visual,w,h);}
 cairo_surface_t*buf=cairo_image_surface_create(CAIRO_FORMAT_RGB24,w,h);cairo_t*cr=cairo_create(buf);
 size_t icon_bytes=(size_t)w*h*4;int icon_fd=-1;unsigned char*shared_icons=NULL;
 if(!preview&&!exporting&&getenv("MATRIX_ICONS_FILE")){
  icon_fd=open(getenv("MATRIX_ICONS_FILE"),O_RDWR|O_CREAT,0600);
  if(icon_fd>=0&&ftruncate(icon_fd,icon_bytes)==0){void*mem=mmap(NULL,icon_bytes,PROT_READ|PROT_WRITE,MAP_SHARED,icon_fd,0);if(mem!=MAP_FAILED)shared_icons=mem;}
 }
 cairo_surface_t*icons=shared_icons?cairo_image_surface_create_for_data(shared_icons,CAIRO_FORMAT_ARGB32,w,h,w*4):cairo_image_surface_create(CAIRO_FORMAT_ARGB32,w,h);
 unsigned char*idat=cairo_image_surface_get_data(icons);int istr=cairo_image_surface_get_stride(icons)/4;
 unsigned char*selection_mask=calloc((size_t)w*h,1);uint32_t*next_icons=malloc(icon_bytes);
 int last_selection=0;double filter_until=0;
 cairo_surface_flush(baseline);uint32_t*bp=(uint32_t*)cairo_image_surface_get_data(baseline);int bstr=cairo_image_surface_get_stride(baseline)/4;
 XSync(d,False);
 int gpu=0;const char*backend=getenv("MATRIX_BACKEND");
 if(!backend||strcmp(backend,"cpu"))gpu=gpu_init(d,win,w,h,sample,mask,focus,cols,rows,count,cw,ch);
 if(!gpu)gpu_destroy(d);
 if(gpu){
  gpu_uniform1("tailLength",tail);gpu_uniform1("density",density);gpu_uniform1("tempo",tempo*(preview?w/(double)DisplayWidth(d,sc)*original_font_size/font_size:1));gpu_uniform1("gain",gain);gpu_uniform1("contrast",contrast);gpu_uniform1("cycle",cycle);gpu_uniform1("duration",duration);gpu_uniform1("depth",depth);gpu_uniform1("focusStrength",focus_strength);
  gpu_uniformi("glyphDirection",glyph_direction);gpu_uniform1("glyphSpeed",glyph_speed);
  gpu_uniformi("direction",horizontal?(reverse?3:2):(reverse?1:0));gpu_uniformi("colorMode",color_mode);gpu_uniformi("revealMode",reveal_mode);gpu_uniformi("phraseMode",phrase_mode);gpu_uniformi("layerCount",layers);gpu_uniformi("randomSpeed",random_speed);gpu_uniformi("exporting",exporting);gpu_uniformi("showIcons",!preview&&!exporting);
  glUniform3f(glGetUniformLocation(gpu_program,"foreground"),fg[0],fg[1],fg[2]);glUniform3f(glGetUniformLocation(gpu_program,"background"),bg[0],bg[1],bg[2]);glUniform3f(glGetUniformLocation(gpu_program,"highlight"),hi[0],hi[1],hi[2]);
 }
 double animation=0,last=now(),stats_time=last;int stats_frames=0,ready_written=0;int tick=0;int total_frames=(int)round(fps*duration);

 while(running&&(!exporting||tick<total_frames)){
   double begin=now(),energy=0,bass=0;
   if(music&&getenv("MATRIX_AUDIO_FILE")){FILE*f=fopen(getenv("MATRIX_AUDIO_FILE"),"r");if(f){if(fscanf(f,"%lf %lf",&energy,&bass)!=2)energy=bass=0;fclose(f);}}
   energy=clamp(energy*setting("MATRIX_MUSIC_SENSITIVITY",1,.1,5),0,1);bass=clamp(bass*setting("MATRIX_MUSIC_SENSITIVITY",1,.1,5),0,1);
   int manual_pause=0;
   if(!preview&&!exporting&&getenv("MATRIX_ANIMATION_PAUSE_FILE")){FILE*f=fopen(getenv("MATRIX_ANIMATION_PAUSE_FILE"),"r");if(f){if(fscanf(f,"%d",&manual_pause)!=1)manual_pause=0;fclose(f);}}
   if(!manual_pause||!ready_written){animation+=fmin(.25,begin-last)*(1+clamp(bass,0,1)*music_amount);}
   last=begin;
   double t=exporting?tick/fps:animation;
   if(!exporting&&tick%10==0&&getenv("MATRIX_RATE_FILE")){FILE*f=fopen(getenv("MATRIX_RATE_FILE"),"r");double rate;if(f){if(fscanf(f,"%lf",&rate)==1)fps=clamp(rate,3,60);fclose(f);}}
   while(XPending(d)){XEvent e;XNextEvent(d,&e);if(e.type==DestroyNotify)running=0;}
   if(!preview&&!exporting&&(tick<20 || tick%20==0))pass_pointer(d,win,root);
   int rect[4]={0,0,0,0};int selecting=(!preview&&!exporting)?selection_rect(d,root,ox,oy,rect):0;
   selecting=selecting&&rect[0]<w&&rect[1]<h&&rect[0]+rect[2]>0&&rect[1]+rect[3]>0;
   if(selecting&&!last_selection){for(int yy=0;yy<h;yy++)for(int xx=0;xx<w;xx++)selection_mask[yy*w+xx]=idat[yy*istr*4+xx*4+3];}
   if(selecting)filter_until=begin+.25;
   int filter_icons=selecting||begin<filter_until;
   int force=interaction_dirty;interaction_dirty=0;
   int update_icons=!preview&&!exporting&&(tick==0||force||tick%(selecting?2:(fps<=12?4:3))==0);
   if(update_icons){
    Pixmap dp=XCompositeNameWindowPixmap(d,frame);
    XImage*im=XGetImage(d,dp,capture_x,capture_y,w,h,AllPlanes,ZPixmap);XFreePixmap(d,dp);
    if(im&&im->bits_per_pixel==32){
     size_t changed=0,previous=0;cairo_surface_flush(icons);
     for(int y=0;y<h;y++){uint32_t*ip=(uint32_t*)(im->data+y*im->bytes_per_line);uint32_t*old=(uint32_t*)idat+y*istr;
      for(int x=0;x<w;x++){uint32_t a=ip[x],b=bp[y*bstr+x];
       int dr=abs((int)((a>>16)&255)-(int)((b>>16)&255)),dg=abs((int)((a>>8)&255)-(int)((b>>8)&255)),db=abs((int)(a&255)-(int)(b&255));
       int visible=filter_icons?selection_mask[y*w+x]>0:dr+dg+db>12;
       next_icons[y*w+x]=visible?a|0xff000000:0;changed+=visible;previous+=(old[x]>>24)!=0;
      }
     }
     /* A temporarily empty XFCE capture must not erase already visible files. */
     if(changed||!previous){for(int y=0;y<h;y++)memcpy(idat+y*istr*4,next_icons+y*w,w*4);cairo_surface_mark_dirty(icons);}
    }if(im)XDestroyImage(im);
   }
   last_selection=selecting;
   if(!preview&&!exporting&&fade>0){unsigned long opacity=(unsigned long)(smooth(t/fade)*4294967295.);prop(d,win,"_NET_WM_WINDOW_OPACITY",XA_CARDINAL,&opacity,1);}
   if(gpu){
    gpu_uniformi("selectionActive",selecting);glUniform4f(glGetUniformLocation(gpu_program,"selectionRect"),rect[0],rect[1],rect[2],rect[3]);
    gpu_uniform1("audioLevel",clamp(energy,0,1)*music_amount);gpu_draw(d,t,chars,cols,rows,icons,update_icons,phrase_mode,exporting);
   }else{
   cairo_set_source_rgb(cr,bg[0],bg[1],bg[2]);cairo_paint(cr);
   double glyph_rate=glyph_speed;
   if(exporting&&glyph_speed>0&&glyph_direction){int period=glyph_direction<=2?cols:rows;glyph_rate=period*fmax(1,round(glyph_speed*duration/period))/duration;}
   int glyph_shift=(int)floor(t*glyph_rate);
   for(int x=0;x<cols;x++){
    for(int y=0;y<rows;y++){
     int stream=horizontal?y:x,position=horizontal?x:y,length=horizontal?cols:rows;
     if(reverse)position=length-1-position;
     double first=(t-delay[stream])*speed[stream],head=fmod(first,length+tail);if(head<0)head+=length+tail;
     double opacity=1;
     if(reveal_mode==1&&!exporting)opacity=smooth((first-position)/5.);
     if(reveal_mode==2){double coverage=(.5+.5*cos(t*2*M_PI/(exporting?duration:cycle)))*(length+tail);opacity=smooth((coverage-position)/tail);}
     opacity=.12+.88*opacity;
     float l=lum[y*cols+x];double dist=head-position;if(dist<0)dist+=length+tail;
     double trail=dist<tail?pow(1-dist/tail,2):0;
     if((stream*7919%1000)/1000.>density)trail=0;
     double brightness=(.025+.85*l)*(.72+.45*trail)+trail*(.05+.17*l);
     if(dist<1.2&&trail>0)brightness=fmax(brightness,.3+.7*l);
     uint32_t*fp=(uint32_t*)cairo_image_surface_get_data(focus);int fs=cairo_image_surface_get_stride(focus)/4;
     double focus_value=(fp[(int)fmin(h-1,y*ch+ch/2)*fs+(int)fmin(w-1,x*cw+cw/2)]&255)/255.;
     brightness=(brightness*opacity+trail*(.12+.25*l)*(1-opacity))*(1+clamp(energy,0,1)*music_amount)*(1-focus_strength+focus_strength*(.42+focus_value));
     int b=(int)fmin(31,brightness*gain*31);if(dist<1.2&&trail>0)b=(int)fmin(39,b+8*opacity);if(b<1)continue;
     int idx=y*cols+x,gx=x,gy=y;
     if(glyph_direction==1)gx+=glyph_shift;
     if(glyph_direction==2)gx-=glyph_shift;
     if(glyph_direction==3)gy+=glyph_shift;
     if(glyph_direction==4)gy-=glyph_shift;
     gx=((gx%cols)+cols)%cols;gy=((gy%rows)+rows)%rows;
     int k=chars[gy*cols+gx];
     if(!color_mode){cairo_set_source_surface(cr,atlas,x*cw-k*cw,y*ch-b*ch);cairo_rectangle(cr,x*cw,y*ch,cw,ch);cairo_fill(cr);}
     else{
      double rgb[3];
      if(color_mode==1){double maximum=fmax(.05,fmax(source_rgb[idx*3],fmax(source_rgb[idx*3+1],source_rgb[idx*3+2])));for(int z=0;z<3;z++)rgb[z]=source_rgb[idx*3+z]/maximum;}
      else if(color_mode==2){double v=y/(double)rows;for(int z=0;z<3;z++)rgb[z]=fg[z]*(1-v)+hi[z]*v;}
      else rainbow(fmod(t/(exporting?duration:12.)+y/(double)rows*.5,1),rgb);
      double value=fmin(1,b/31.);for(int z=0;z<3;z++)rgb[z]=bg[z]*(1-value)+rgb[z]*value;
      cairo_save(cr);cairo_rectangle(cr,x*cw,y*ch,cw,ch);cairo_clip(cr);cairo_set_source_rgb(cr,rgb[0],rgb[1],rgb[2]);cairo_mask_surface(cr,mask,x*cw-k*cw,y*ch);cairo_restore(cr);
     }

    }
   }
   if(layers>1){
    for(int layer=1;layer<layers;layer++){double factor=layer==1?.65:1.8;int total=(int)(w/(cw*factor));
     for(int x=0;x<total;x++){if((x*7919%1000)/1000.>density*.3)continue;int sideways=glyph_direction==1||glyph_direction==2;
     double extent=sideways?w:h;
     double travel=glyph_direction&&glyph_speed>0?t*ch*glyph_speed*(layer==1?.55:1.55):0;
     double position=fmod(travel+x*31,extent+tail*ch);
     if(glyph_direction==1||glyph_direction==3)position=extent-position;
     int k=(x*17)%count;
      cairo_save(cr);cairo_translate(cr,sideways?position:x*cw*factor,sideways?x*cw*factor:position);cairo_scale(cr,factor,factor);cairo_rectangle(cr,0,0,cw,ch);cairo_clip(cr);cairo_set_source_rgba(cr,fg[0],fg[1],fg[2],depth*(layer==1?.12:.28));cairo_mask_surface(cr,mask,-k*cw,0);cairo_restore(cr);
     }
    }
   }
   if(selecting){
    cairo_save(cr);cairo_rectangle(cr,rect[0],rect[1],rect[2],rect[3]);cairo_clip(cr);cairo_set_source_surface(cr,sample,0,0);cairo_paint(cr);cairo_restore(cr);
    cairo_set_source_rgba(cr,.3,.65,1,.9);cairo_set_line_width(cr,1);cairo_rectangle(cr,rect[0]+.5,rect[1]+.5,rect[2]-1,rect[3]-1);cairo_stroke(cr);
   }
   if(!preview&&!exporting){cairo_set_source_surface(cr,icons,0,0);cairo_paint(cr);}
   if(exporting){
    cairo_surface_flush(buf);unsigned char*data=cairo_image_surface_get_data(buf);int stride=cairo_image_surface_get_stride(buf);
    for(int row=0;row<h;row++)if(fwrite(data+row*stride,4,w,stdout)!=(size_t)w){running=0;break;}
   }else{cairo_t*dest=cairo_create(screen);cairo_set_source_surface(dest,buf,0,0);cairo_paint(dest);cairo_destroy(dest);cairo_surface_flush(screen);XFlush(d);}
   }
   if(!exporting&&!ready_written&&(preview||t>=fade)){
    if(gpu){glFinish();}
    XSync(d,False);
    if(!preview&&fade<=0){unsigned long opacity=0xffffffff;prop(d,win,"_NET_WM_WINDOW_OPACITY",XA_CARDINAL,&opacity,1);XFlush(d);}
    if(getenv("MATRIX_READY_FILE")){FILE*f=fopen(getenv("MATRIX_READY_FILE"),"w");if(f){fputs("ready\n",f);fclose(f);}}
    if(getenv("MATRIX_STATS_FILE")){FILE*f=fopen(getenv("MATRIX_STATS_FILE"),"w");if(f){fprintf(f,"0 %s\n",gpu?"GPU":"CPU");fclose(f);}}
    ready_written=1;
   }
   tick++;stats_frames++;
   if(!exporting&&begin-stats_time>=1&&getenv("MATRIX_STATS_FILE")){FILE*f=fopen(getenv("MATRIX_STATS_FILE"),"w");if(f){fprintf(f,"%g %s\n",stats_frames/(begin-stats_time),gpu?"GPU":"CPU");fclose(f);}stats_frames=0;stats_time=begin;}
   double wait=1./(selecting?fmax(fps,30):fps)-(now()-begin);if(!exporting&&wait>0)usleep(wait*1e6);
 }
 if(gpu)gpu_destroy(d);

 cairo_destroy(cr);cairo_surface_destroy(icons);cairo_surface_destroy(buf);cairo_surface_destroy(atlas);cairo_surface_destroy(baseline);if(screen)cairo_surface_destroy(screen);cairo_surface_destroy(mask);cairo_surface_destroy(focus);cairo_surface_destroy(sample);if(shared_icons)munmap(shared_icons,icon_bytes);if(icon_fd>=0)close(icon_fd);free(selection_mask);free(next_icons);if(win)XDestroyWindow(d,win);XCloseDisplay(d);free(lum);free(source_rgb);free(chars);free(speed);free(delay);return 0;
}

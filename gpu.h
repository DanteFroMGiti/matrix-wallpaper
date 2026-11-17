/* OpenGL 2.1 compatibility backend. A CPU fallback remains available. */
#include <epoxy/gl.h>
#include <epoxy/glx.h>
static GLXContext gpu_context;
static GLXDrawable gpu_drawable;
static GLXPbuffer gpu_pbuffer;
static GLuint gpu_program,gpu_textures[5];
static int gpu_width,gpu_height,gpu_double;
static const char*vertex_shader="#version 120\nvarying vec2 uv;void main(){gl_Position=gl_Vertex;uv=gl_MultiTexCoord0.xy;}";
static const char*fragment_shader=
"#version 120\n"
"varying vec2 uv;uniform sampler2D imageTex,glyphTex,iconTex,indexTex,focusTex;"
"uniform vec2 resolution,cell,grid;uniform vec3 foreground,background,highlight;"
"uniform float clockTime,tailLength,density,tempo,gain,contrast,cycle,alphabetCount,depth,focusStrength,audioLevel;"
"uniform int direction,colorMode,revealMode,phraseMode,layerCount,randomSpeed,exporting,showIcons;uniform float duration,glyphSpeed;uniform int glyphDirection,selectionActive;uniform vec4 selectionRect;"
"float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}"
"vec3 hsv(float h){return clamp(abs(mod(h*6.+vec3(0.,4.,2.),6.)-3.)-1.,0.,1.);}"
"vec4 layer(float scale,float speedFactor,float strength){"
" vec2 c=cell*scale;vec2 g=ceil(resolution/c);vec2 pixel=uv*resolution;vec2 id=floor(pixel/c);vec2 inside=fract(pixel/c);"
" bool horizontal=direction>1;float position=horizontal?id.x:id.y;float stream=horizontal?id.y:id.x;float length=horizontal?g.x:g.y;"
" if(direction==1||direction==3)position=length-1.-position;"
" float random=hash(vec2(stream,scale));float speed=(randomSpeed==1?15.+15.*random:22.5)*tempo*speedFactor;"
" if(exporting==1)speed=(length+tailLength)*max(1.,floor(speed*duration/(length+tailLength)+.5))/duration;"
" float first=(clockTime-random*1.6)*speed;float head=mod(first,length+tailLength);float dist=mod(head-position,length+tailLength);"
" float trail=pow(max(0.,1.-dist/tailLength),2.);if(random>density)trail=0.;"
" float opacity=1.;if(revealMode==1&&exporting==0)opacity=smoothstep(0.,5.,first-position);"
" if(revealMode==2){float cover=(.5+.5*cos(clockTime*6.2831853/(exporting==1?duration:cycle)))*(length+tailLength);opacity=smoothstep(0.,tailLength,cover-position);}"
" opacity=.12+.88*opacity;vec2 center=clamp((id+.5)*c/resolution,vec2(0.),vec2(1.));vec3 original=texture2D(imageTex,center).rgb;"
" float luminance=clamp((pow(dot(original,vec3(.2126,.7152,.0722)),.78)-.5)*contrast+.5,0.,1.);"
" float focus=texture2D(focusTex,center).r;"
" float value=((.025+.85*luminance)*(.72+.45*trail)+trail*(.05+.17*luminance));"
" if(dist<1.2&&trail>0.)value=max(value,.3+.7*luminance);"
" value=(value*opacity+trail*(.12+.25*luminance)*(1.-opacity))*gain*(1.+audioLevel);"
" value*=mix(1.,.42+focus,focusStrength);"
" float glyphRate=glyphSpeed;float axisLength=glyphDirection<=2?g.x:g.y;"
" if(exporting==1&&glyphSpeed>0.&&glyphDirection!=0)glyphRate=axisLength*max(1.,floor(glyphSpeed*duration/axisLength+.5))/duration;"
" float shift=floor(clockTime*glyphRate);vec2 glyphId=id;"
" if(glyphDirection==1)glyphId.x+=shift;else if(glyphDirection==2)glyphId.x-=shift;"
" else if(glyphDirection==3)glyphId.y+=shift;else if(glyphDirection==4)glyphId.y-=shift;"
" glyphId=mod(glyphId,g);float k=floor(hash(glyphId+scale)*alphabetCount);"
" if(phraseMode==1)k=floor(texture2D(indexTex,(mod(glyphId,grid)+.5)/grid).r*255.+.5);"
" float alpha=texture2D(glyphTex,vec2((k+inside.x)/alphabetCount,inside.y)).a;"
" vec3 color=foreground;if(colorMode==1)color=original/max(.05,max(original.r,max(original.g,original.b)));"
" else if(colorMode==2)color=mix(foreground,highlight,center.y);else if(colorMode==3)color=hsv(fract(clockTime/(exporting==1?duration:12.)+center.y*.5));"
" if(dist<1.2&&trail>0.)color=mix(color,highlight,.65);"
" if(scale>1.){value=trail*.28*depth*opacity;alpha*=step(.82,hash(vec2(stream,scale)));}"
" if(scale<1.)value=trail*.12*depth*opacity;"
" return vec4(color*clamp(value,0.,1.),alpha*strength);"
"}"
"void main(){vec4 mainLayer=layer(1.,1.,1.);vec3 result=mix(background,mainLayer.rgb,mainLayer.a);"
"if(layerCount>1){vec4 distant=layer(.65,.55,1.);result+=distant.rgb*distant.a;}"
"if(layerCount>2){vec4 nearLayer=layer(1.8,1.55,1.);result=mix(result,nearLayer.rgb,nearLayer.a*length(nearLayer.rgb));}"
"vec2 p=uv*resolution;vec2 edge=p-selectionRect.xy;"
"if(selectionActive==1&&edge.x>=0.&&edge.y>=0.&&edge.x<selectionRect.z&&edge.y<selectionRect.w){"
" result=texture2D(imageTex,uv).rgb;"
" if(min(min(edge.x,edge.y),min(selectionRect.z-edge.x,selectionRect.w-edge.y))<1.)result=mix(result,vec3(.3,.65,1.),.9);"
"}"
"if(showIcons==1){vec4 icon=texture2D(iconTex,uv);result=mix(result,icon.rgb,icon.a);}gl_FragColor=vec4(result,1.);}";
static GLuint gpu_compile(GLenum type,const char*source){GLuint shader=glCreateShader(type);glShaderSource(shader,1,&source,NULL);glCompileShader(shader);GLint ok;glGetShaderiv(shader,GL_COMPILE_STATUS,&ok);if(!ok){char log[4096];glGetShaderInfoLog(shader,sizeof log,NULL,log);fprintf(stderr,"GPU shader: %s\n",log);glDeleteShader(shader);return 0;}return shader;}
static void gpu_uniform1(const char*n,float v){glUniform1f(glGetUniformLocation(gpu_program,n),v);}
static void gpu_uniformi(const char*n,int v){glUniform1i(glGetUniformLocation(gpu_program,n),v);}
static void gpu_texture(int unit,int w,int h,GLenum format,const void*data,int linear){glActiveTexture(GL_TEXTURE0+unit);glBindTexture(GL_TEXTURE_2D,gpu_textures[unit]);glPixelStorei(GL_UNPACK_ALIGNMENT,1);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,linear?GL_LINEAR:GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,linear?GL_LINEAR:GL_NEAREST);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_S,GL_CLAMP_TO_EDGE);glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_WRAP_T,GL_CLAMP_TO_EDGE);glTexImage2D(GL_TEXTURE_2D,0,format==GL_ALPHA?GL_ALPHA:format==GL_LUMINANCE?GL_LUMINANCE:GL_RGBA,w,h,0,format,GL_UNSIGNED_BYTE,data);}
static int gpu_init(Display*d,Window win,int w,int h,cairo_surface_t*image,cairo_surface_t*glyph,cairo_surface_t*focus,int cols,int rows,int count,int cw,int ch){
 int opcode,event,error;if(!XQueryExtension(d,"GLX",&opcode,&event,&error))return 0;
 gpu_width=w;gpu_height=h;
 if(win){XWindowAttributes a;XGetWindowAttributes(d,win,&a);XVisualInfo templ={.visualid=XVisualIDFromVisual(a.visual)};int n=0;XVisualInfo*vi=XGetVisualInfo(d,VisualIDMask,&templ,&n);if(!vi)return 0;gpu_context=glXCreateContext(d,vi,NULL,True);glXGetConfig(d,vi,GLX_DOUBLEBUFFER,&gpu_double);XFree(vi);gpu_drawable=win;}
 else{int attrs[]={GLX_DRAWABLE_TYPE,GLX_PBUFFER_BIT,GLX_RENDER_TYPE,GLX_RGBA_BIT,GLX_RED_SIZE,8,GLX_GREEN_SIZE,8,GLX_BLUE_SIZE,8,None};int n;GLXFBConfig*configs=glXChooseFBConfig(d,DefaultScreen(d),attrs,&n);if(!configs||!n)return 0;gpu_context=glXCreateNewContext(d,configs[0],GLX_RGBA_TYPE,NULL,True);int pa[]={GLX_PBUFFER_WIDTH,w,GLX_PBUFFER_HEIGHT,h,None};gpu_pbuffer=glXCreatePbuffer(d,configs[0],pa);gpu_drawable=gpu_pbuffer;XFree(configs);}
 if(!gpu_context||!glXMakeContextCurrent(d,gpu_drawable,gpu_drawable,gpu_context))return 0;
 if(!epoxy_has_gl_extension("GL_ARB_shader_objects")&&epoxy_gl_version()<20)return 0;
 GLuint vs=gpu_compile(GL_VERTEX_SHADER,vertex_shader),fs=gpu_compile(GL_FRAGMENT_SHADER,fragment_shader);if(!vs||!fs)return 0;
 gpu_program=glCreateProgram();glAttachShader(gpu_program,vs);glAttachShader(gpu_program,fs);glLinkProgram(gpu_program);glDeleteShader(vs);glDeleteShader(fs);GLint ok;glGetProgramiv(gpu_program,GL_LINK_STATUS,&ok);if(!ok){char log[4096];glGetProgramInfoLog(gpu_program,sizeof log,NULL,log);fprintf(stderr,"GPU link: %s\n",log);return 0;}
 const char*backend=getenv("MATRIX_BACKEND");const char*renderer=(const char*)glGetString(GL_RENDERER);if((!backend||!strcmp(backend,"auto"))&&(strstr(renderer,"llvmpipe")||strstr(renderer,"softpipe")))return 0;
 glUseProgram(gpu_program);glGenTextures(5,gpu_textures);
 cairo_surface_flush(image);gpu_texture(0,w,h,GL_BGRA,cairo_image_surface_get_data(image),1);
 /* Cairo A8 rows can have padding; make the atlas contiguous for OpenGL. */
 cairo_surface_flush(glyph);unsigned char*packed=malloc(count*cw*ch);unsigned char*data=cairo_image_surface_get_data(glyph);int stride=cairo_image_surface_get_stride(glyph);for(int y=0;y<ch;y++)memcpy(packed+y*count*cw,data+y*stride,count*cw);gpu_texture(1,count*cw,ch,GL_ALPHA,packed,1);free(packed);
 unsigned char*zero=calloc(w*h,4);gpu_texture(2,w,h,GL_BGRA,zero,0);free(zero);
 zero=calloc(cols*rows,1);gpu_texture(3,cols,rows,GL_LUMINANCE,zero,0);free(zero);
 cairo_surface_flush(focus);gpu_texture(4,w,h,GL_BGRA,cairo_image_surface_get_data(focus),1);
 const char*samplers[]={"imageTex","glyphTex","iconTex","indexTex","focusTex"};for(int i=0;i<5;i++)gpu_uniformi(samplers[i],i);
 glUniform2f(glGetUniformLocation(gpu_program,"resolution"),w,h);glUniform2f(glGetUniformLocation(gpu_program,"cell"),cw,ch);glUniform2f(glGetUniformLocation(gpu_program,"grid"),cols,rows);gpu_uniform1("alphabetCount",count);
 glViewport(0,0,w,h);glDisable(GL_DEPTH_TEST);glDisable(GL_BLEND);glDrawBuffer(gpu_double?GL_BACK:GL_FRONT);
 fprintf(stderr,"GPU backend: %s\n",glGetString(GL_RENDERER));return glGetError()==GL_NO_ERROR;
}
static void gpu_draw(Display*d,double t,int *chars,int cols,int rows,cairo_surface_t*icons,int update_icons,int phrase_mode,int exporting){
 gpu_uniform1("clockTime",t);
 if(phrase_mode){unsigned char*indices=malloc(cols*rows);for(int i=0;i<cols*rows;i++)indices[i]=chars[i];gpu_texture(3,cols,rows,GL_LUMINANCE,indices,0);free(indices);}
 if(update_icons){cairo_surface_flush(icons);gpu_texture(2,gpu_width,gpu_height,GL_BGRA,cairo_image_surface_get_data(icons),0);}
 glBegin(GL_QUADS);glTexCoord2f(0,1);glVertex2f(-1,-1);glTexCoord2f(1,1);glVertex2f(1,-1);glTexCoord2f(1,0);glVertex2f(1,1);glTexCoord2f(0,0);glVertex2f(-1,1);glEnd();
 if(exporting){unsigned char*p=malloc(gpu_width*gpu_height*4);glReadPixels(0,0,gpu_width,gpu_height,GL_BGRA,GL_UNSIGNED_BYTE,p);for(int y=gpu_height-1;y>=0;y--)if(fwrite(p+y*gpu_width*4,4,gpu_width,stdout)!=(size_t)gpu_width)break;free(p);}
 else{if(gpu_double)glXSwapBuffers(d,gpu_drawable);else glFlush();}
}
static void gpu_destroy(Display*d){if(gpu_context){glXMakeContextCurrent(d,None,None,NULL);glXDestroyContext(d,gpu_context);gpu_context=NULL;}if(gpu_pbuffer)glXDestroyPbuffer(d,gpu_pbuffer);}

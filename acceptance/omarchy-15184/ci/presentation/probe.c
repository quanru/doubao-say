// Disposable-session observer. No input or application-state writes.
// Feedback requests belong to the SAME wl_display/surface used by Qt/EGL.
#define _GNU_SOURCE
#include <wayland-client.h>
#include <wayland-egl-core.h>
#include "presentation-client.h"
#include <dlfcn.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <time.h>
#include <png.h>
#include <stdarg.h>
typedef void *EDisplay; typedef void *ESurface; typedef void *EConfig; typedef unsigned int EBool;
static pthread_mutex_t map_lock=PTHREAD_MUTEX_INITIALIZER,log_lock=PTHREAD_MUTEX_INITIALIZER;
static FILE *logfile;
static char directory[512];
static int mode; // 0 passive swap log, 1 presentation feedback, 2 feedback + tiny pixel readback
static uint64_t serial;
static int gl_reported;
static atomic_int pending, stopping;
static uint64_t now(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (uint64_t)t.tv_sec*1000000000+t.tv_nsec;}
static void logline(const char *fmt,...){pthread_mutex_lock(&log_lock);if(logfile){va_list a;va_start(a,fmt);vfprintf(logfile,fmt,a);va_end(a);fputc('\n',logfile);fflush(logfile);}pthread_mutex_unlock(&log_lock);}
static void *existing_symbol(const char *library,const char *name){void*h=dlopen(library,RTLD_LAZY|RTLD_NOLOAD);if(!h)return NULL;void*p=dlsym(h,name);dlclose(h);return p;}
static void *symbol(const char *name){
 void *p=dlsym(RTLD_NEXT,name);
 // Qt loads platform plugins locally. Do not promote scope or load new providers.
 if(!p && !strncmp(name,"wl_egl_",7))p=existing_symbol("libwayland-egl.so.1",name);
 if(!p && !strncmp(name,"egl",3))p=existing_symbol("libEGL.so.1",name);
 if(!p && !strncmp(name,"gl",2)){void*(*get)(const char*)=dlsym(RTLD_NEXT,"eglGetProcAddress");if(!get)get=existing_symbol("libEGL.so.1","eglGetProcAddress");if(get)p=get(name);}
 if(!p){logline("{\"event\":\"fatal\",\"reason\":\"missing symbol\",\"symbol\":\"%s\"}",name);_exit(90);}return p;
}
struct connection {struct wl_display *display;struct wl_event_queue *queue;struct wp_presentation *presentation;int clock_ok;pthread_t thread;};
static struct connection conn;
struct window {struct wl_egl_window *native;struct wl_surface *surface;ESurface egl;int width,height;};
static struct window windows[128];
struct feedback {uint64_t token;uint32_t surface;};
static void sync_output(void*d,struct wp_presentation_feedback*f,struct wl_output*o){(void)d;(void)f;(void)o;}
static void presented(void*d,struct wp_presentation_feedback*f,uint32_t hi,uint32_t lo,uint32_t ns,uint32_t refresh,uint32_t shi,uint32_t slo,uint32_t flags){
 struct feedback*x=d;logline("{\"event\":\"presented\",\"token\":%llu,\"surface\":%u,\"sourceNs\":\"%llu\",\"receiptNs\":\"%llu\",\"refreshNs\":%u,\"sequence\":\"%llu\",\"flags\":%u}",(unsigned long long)x->token,x->surface,(unsigned long long)((((uint64_t)hi<<32)|lo)*1000000000+ns),(unsigned long long)now(),refresh,(unsigned long long)(((uint64_t)shi<<32)|slo),flags);wp_presentation_feedback_destroy(f);free(x);atomic_fetch_sub(&pending,1);
}
static void discarded(void*d,struct wp_presentation_feedback*f){struct feedback*x=d;logline("{\"event\":\"discarded\",\"token\":%llu,\"surface\":%u,\"receiptNs\":\"%llu\"}",(unsigned long long)x->token,x->surface,(unsigned long long)now());wp_presentation_feedback_destroy(f);free(x);atomic_fetch_sub(&pending,1);}
static const struct wp_presentation_feedback_listener feedback_listener={sync_output,presented,discarded};
static void clock_id(void*d,struct wp_presentation*p,uint32_t id){(void)d;(void)p;conn.clock_ok=id==CLOCK_MONOTONIC;logline("{\"event\":\"presentation-clock\",\"clockId\":%u,\"monotonic\":%s}",id,conn.clock_ok?"true":"false");}
static const struct wp_presentation_listener presentation_listener={clock_id};
static void global(void*d,struct wl_registry*r,uint32_t name,const char*interface,uint32_t version){(void)d;if(!strcmp(interface,"wp_presentation")){logline("{\"event\":\"presentation-global\",\"version\":%u,\"observerBinding\":true}",version);conn.presentation=wl_registry_bind(r,name,&wp_presentation_interface,version>2?2:version);wp_presentation_add_listener(conn.presentation,&presentation_listener,NULL);}}
static void removed(void*d,struct wl_registry*r,uint32_t n){(void)d;(void)r;(void)n;}
static const struct wl_registry_listener registry_listener={global,removed};
static void *dispatch(void*d){(void)d;while(!atomic_load(&stopping)){int n=wl_display_dispatch_queue_pending(conn.display,conn.queue);if(n<0){logline("{\"event\":\"fatal\",\"reason\":\"feedback queue failed\"}");return NULL;}struct timespec t={0,1000000};nanosleep(&t,NULL);}return NULL;}
static void setup(struct wl_surface *surface){
 if(!mode)return;
 struct wl_display *(*get_display)(struct wl_proxy*)=symbol("wl_proxy_get_display");
 struct wl_display *display=get_display((struct wl_proxy*)surface);
 if(conn.display){if(conn.display!=display){logline("{\"event\":\"fatal\",\"reason\":\"multiple display connections\"}");_exit(91);}return;}
 conn.display=display;conn.queue=wl_display_create_queue(display);
 struct wl_display *wrapper=wl_proxy_create_wrapper(display);wl_proxy_set_queue((struct wl_proxy*)wrapper,conn.queue);
 struct wl_registry *registry=wl_display_get_registry(wrapper);wl_proxy_wrapper_destroy(wrapper);wl_registry_add_listener(registry,&registry_listener,NULL);
 // Dedicated queue: never dispatch Qt application callbacks from the render thread.
 if(wl_display_roundtrip_queue(display,conn.queue)<0 || wl_display_roundtrip_queue(display,conn.queue)<0 || !conn.presentation || !conn.clock_ok){logline("{\"event\":\"fatal\",\"reason\":\"no verified presentation clock\"}");_exit(92);}
 wl_registry_destroy(registry);pthread_create(&conn.thread,NULL,dispatch,NULL);
}
__attribute__((constructor)) static void init(void){char exe[512]={0};ssize_t n=readlink("/proc/self/exe",exe,sizeof exe-1);if(n<0)return;const char*base=strrchr(exe,'/');if(!base || (strcmp(base+1,"quickshell") && strcmp(base+1,"qs")))return;const char *p=getenv("MIDSCENE_PRESENT_DIR"),*m=getenv("MIDSCENE_PRESENT_MODE");if(!p||!m)return;snprintf(directory,sizeof directory,"%s",p);mode=!strcmp(m,"pixels")?2:!strcmp(m,"feedback")?1:0;char path[600];snprintf(path,sizeof path,"%s/events.jsonl",directory);logfile=fopen(path,"a");if(!logfile)_exit(93);char boot[80]="";FILE*b=fopen("/proc/sys/kernel/random/boot_id","r");if(!b || !fgets(boot,sizeof boot,b)){logline("{\"event\":\"fatal\",\"reason\":\"boot clock identity unavailable\"}");_exit(95);}fclose(b);boot[strcspn(boot,"\r\n")]=0;logline("{\"event\":\"start\",\"pid\":%ld,\"mode\":%d,\"clockId\":\"linux-monotonic:%s\",\"timeNs\":\"%llu\"}",(long)getpid(),mode,boot,(unsigned long long)now());}
struct wl_egl_window *wl_egl_window_create(struct wl_surface*s,int w,int h){
 struct wl_egl_window *(*real)(struct wl_surface*,int,int)=symbol("wl_egl_window_create");struct wl_egl_window*n=real(s,w,h);if(!logfile)return n;
 pthread_mutex_lock(&map_lock);int i;for(i=0;i<128;i++)if(!windows[i].native)break;if(i==128)_exit(94);windows[i]=(struct window){n,s,NULL,w,h};logline("{\"event\":\"window\",\"surface\":%u,\"width\":%d,\"height\":%d,\"timeNs\":\"%llu\"}",wl_proxy_get_id((struct wl_proxy*)s),w,h,(unsigned long long)now());setup(s);pthread_mutex_unlock(&map_lock);return n;
}
void wl_egl_window_resize(struct wl_egl_window*n,int w,int h,int dx,int dy){void(*real)(struct wl_egl_window*,int,int,int,int)=symbol("wl_egl_window_resize");real(n,w,h,dx,dy);pthread_mutex_lock(&map_lock);for(int i=0;i<128;i++)if(windows[i].native==n){windows[i].width=w;windows[i].height=h;logline("{\"event\":\"resize\",\"surface\":%u,\"width\":%d,\"height\":%d}",wl_proxy_get_id((struct wl_proxy*)windows[i].surface),w,h);}pthread_mutex_unlock(&map_lock);}
void wl_egl_window_destroy(struct wl_egl_window*n){void(*real)(struct wl_egl_window*)=symbol("wl_egl_window_destroy");pthread_mutex_lock(&map_lock);for(int i=0;i<128;i++)if(windows[i].native==n)memset(&windows[i],0,sizeof windows[i]);pthread_mutex_unlock(&map_lock);real(n);}
ESurface eglCreateWindowSurface(EDisplay d,EConfig c,void*n,const int*a){ESurface(*real)(EDisplay,EConfig,void*,const int*)=symbol("eglCreateWindowSurface");ESurface s=real(d,c,n,a);pthread_mutex_lock(&map_lock);for(int i=0;i<128;i++)if(windows[i].native==n)windows[i].egl=s;pthread_mutex_unlock(&map_lock);return s;}
static int pixels(uint64_t token,int height,uint64_t*start,uint64_t*end){
 if(!gl_reported){const unsigned char*(*getstr)(unsigned int)=symbol("glGetString");const char*v=(const char*)getstr(0x1F02),*renderer=(const char*)getstr(0x1F01);logline("{\"event\":\"gl-backend\",\"version\":\"%s\",\"renderer\":\"%s\"}",v?v:"unknown",renderer?renderer:"unknown");gl_reported=1;}
 void(*get)(unsigned int,int*)=symbol("glGetIntegerv");void(*read)(int,int,int,int,unsigned int,unsigned int,void*)=symbol("glReadPixels");
 int read_fbo=-1,pbo=-1,row=-1,skiprow=-1,skippixel=-1;get(0x8CAA,&read_fbo);get(0x88ED,&pbo);get(0x0D02,&row);get(0x0D03,&skiprow);get(0x0D04,&skippixel);
 if(read_fbo||pbo||row||skiprow||skippixel){logline("{\"event\":\"pixel-rejected\",\"token\":%llu,\"readFbo\":%d,\"pbo\":%d,\"rowLength\":%d,\"skipRows\":%d,\"skipPixels\":%d}",(unsigned long long)token,read_fbo,pbo,row,skiprow,skippixel);return 0;}
 unsigned char rgba[36*26*4];*start=now();read(1137,height-26,36,26,0x1908,0x1401,rgba);*end=now();
 char path[600];snprintf(path,sizeof path,"%s/pixel-%llu.png",directory,(unsigned long long)token);FILE*f=fopen(path,"wb");if(!f)return 0;
 png_structp png=png_create_write_struct(PNG_LIBPNG_VER_STRING,NULL,NULL,NULL);png_infop info=png_create_info_struct(png);if(setjmp(png_jmpbuf(png))){fclose(f);return 0;}png_init_io(png,f);png_set_IHDR(png,info,36,26,8,PNG_COLOR_TYPE_RGBA,PNG_INTERLACE_NONE,PNG_COMPRESSION_TYPE_DEFAULT,PNG_FILTER_TYPE_DEFAULT);png_set_compression_level(png,1);png_set_filter(png,0,PNG_FILTER_NONE);png_write_info(png,info);for(int y=25;y>=0;y--)png_write_row(png,rgba+y*36*4);png_write_end(png,NULL);png_destroy_write_struct(&png,&info);fclose(f);return 1;
}
EBool eglSwapBuffers(EDisplay d,ESurface s){
 uint64_t entry=now();
 EBool(*real)(EDisplay,ESurface)=symbol("eglSwapBuffers");struct window w={0};pthread_mutex_lock(&map_lock);for(int i=0;i<128;i++)if(windows[i].egl==s){w=windows[i];break;}pthread_mutex_unlock(&map_lock);
 if(!logfile||!w.surface||w.width!=1280||w.height<26||w.height>40)return real(d,s);
 uint64_t token=__atomic_add_fetch(&serial,1,__ATOMIC_RELAXED),enter=entry,read_start=0,read_end=0;uint32_t surface=wl_proxy_get_id((struct wl_proxy*)w.surface);int captured=mode==2?pixels(token,w.height,&read_start,&read_end):0;
 if(mode){struct feedback*x=calloc(1,sizeof*x);x->token=token;x->surface=surface;struct wp_presentation_feedback*f=wp_presentation_feedback(conn.presentation,w.surface);wp_presentation_feedback_add_listener(f,&feedback_listener,x);atomic_fetch_add(&pending,1);}
 uint64_t submit=now();logline("{\"event\":\"swap-begin\",\"token\":%llu,\"surface\":%u,\"width\":%d,\"height\":%d,\"enterNs\":\"%llu\",\"readStartNs\":\"%llu\",\"readEndNs\":\"%llu\",\"beforeLogNs\":\"%llu\",\"pixelSaved\":%s,\"observerFeedback\":%s}",(unsigned long long)token,surface,w.width,w.height,(unsigned long long)enter,(unsigned long long)read_start,(unsigned long long)read_end,(unsigned long long)submit,captured?"true":"false",mode?"true":"false");
 submit=now();EBool ok=real(d,s);uint64_t after=now();logline("{\"event\":\"swap-end\",\"token\":%llu,\"beforeSwapNs\":\"%llu\",\"afterSwapNs\":\"%llu\",\"ok\":%s}",(unsigned long long)token,(unsigned long long)submit,(unsigned long long)after,ok?"true":"false");return ok;
}

void wl_display_disconnect(struct wl_display*d){void(*real)(struct wl_display*)=symbol("wl_display_disconnect");if(conn.display==d){atomic_store(&stopping,1);pthread_join(conn.thread,NULL);logline("{\"event\":\"display-disconnect\",\"pendingFeedback\":%d}",atomic_load(&pending));conn.display=NULL;}real(d);}

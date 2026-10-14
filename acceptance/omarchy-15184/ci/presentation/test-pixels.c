// Unit-only GL doubles. Never exported as guest acceptance evidence.
#define dlsym test_dlsym
#include "probe.c"
#undef dlsym
static int fake_fbo,read_calls;
static void fake_get(unsigned int name,int*value){*value=name==0x8CAA?fake_fbo:0;}
static void fake_read(int x,int y,int w,int h,unsigned int fmt,unsigned int type,void*data){if(x!=1137||y!=0||w!=36||h!=26||fmt!=0x1908||type!=0x1401)abort();read_calls++;unsigned char*p=data;for(int j=0;j<h;j++)for(int i=0;i<w;i++){*p++=(unsigned char)i;*p++=(unsigned char)j;*p++=9;*p++=255;}}
void *test_dlsym(void*handle,const char*name){(void)handle;if(!strcmp(name,"glGetIntegerv"))return fake_get;if(!strcmp(name,"glReadPixels"))return fake_read;return NULL;}
int main(int argc,char**argv){if(argc!=2)return 2;snprintf(directory,sizeof directory,"%s",argv[1]);logfile=tmpfile();gl_reported=1;uint64_t a=0,b=0;fake_fbo=1;if(pixels(1,26,&a,&b)||read_calls)return 3;fake_fbo=0;if(!pixels(2,26,&a,&b)||read_calls!=1||!a||b<a)return 4;char path[600];snprintf(path,sizeof path,"%s/pixel-2.png",directory);png_image im={0};im.version=PNG_IMAGE_VERSION;if(!png_image_begin_read_from_file(&im,path))return 5;im.format=PNG_FORMAT_RGBA;unsigned char out[36*26*4];if(!png_image_finish_read(&im,NULL,out,0,NULL)||im.width!=36||im.height!=26)return 6;for(int y=0;y<26;y++)for(int x=0;x<36;x++){int k=(y*36+x)*4;if(out[k]!=x||out[k+1]!=25-y||out[k+2]!=9||out[k+3]!=255)return 7;}png_image_free(&im);puts("PASS unit-only: non-default GL state rejected without reading; complete RGBA pixels and vertical orientation preserved; monotonic read bounds.");return 0;}

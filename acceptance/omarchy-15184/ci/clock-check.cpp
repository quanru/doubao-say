#include <chrono>
#include <time.h>
#include <stdio.h>
#include <stdint.h>
static int64_t mono(){timespec t; if(clock_gettime(CLOCK_MONOTONIC,&t))return -1;return (int64_t)t.tv_sec*1000000000+t.tv_nsec;}
int main(){
 timespec res; if(clock_getres(CLOCK_MONOTONIC,&res))return 2;
 printf("{\"monotonicResolutionNs\":%lld,\"samples\":[",(long long)res.tv_sec*1000000000+res.tv_nsec);
 bool valid=true;
 for(int i=0;i<10000;i++){
  auto before=mono();auto steady=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();auto after=mono();
  if(before<0 || steady<before || steady>after)valid=false;
  printf("%s[\"%lld\",\"%lld\",\"%lld\"]",i?",":"",(long long)before,(long long)steady,(long long)after);
 }
 printf("],\"allSteadySamplesBracketed\":%s}\n",valid?"true":"false");return valid?0:1;
}

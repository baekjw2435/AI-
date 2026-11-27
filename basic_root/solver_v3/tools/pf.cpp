#include <sys/mman.h>
#include <chrono>
#include <cstdio>
#include <cstring>
int main(int argc,char**argv){size_t mb=1024; for(int mode=0;mode<3;mode++){auto t=std::chrono::steady_clock::now();
 int fl=MAP_PRIVATE|MAP_ANONYMOUS|(mode==2?MAP_POPULATE:0); char*p=(char*)mmap(0,mb<<20,PROT_READ|PROT_WRITE,fl,-1,0); if(mode==1)madvise(p,mb<<20,MADV_HUGEPAGE);
 if(mode<2) for(size_t i=0;i<(mb<<20);i+=4096)p[i]=1; double s=std::chrono::duration<double>(std::chrono::steady_clock::now()-t).count(); printf("mode %d: %.3f s for %zu MB\n",mode,s,mb); munmap(p,mb<<20);} }

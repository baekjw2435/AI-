// Exact directed edge-geography solver, route-proof-v2.
// No hash-only equality, guessed outcomes, or imported legacy facts.
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>
using namespace std;
static constexpr uint64_t INF = (uint64_t(1)<<60);
struct Limit: exception { const char* why; Limit(const char* w):why(w){} const char* what()const noexcept override{return why;} };
struct Node { const string* key=nullptr; uint64_t pn=1,dn=1; int best=-1,static_value=-1; bool expanded=false; vector<pair<int,size_t>> children; };
struct Solver {
 int N=0,G=0,current=0; vector<int> src,dst,reverse,preferred; vector<vector<int>> out,inc;
 struct Fact{uint64_t a,b;int16_t answer;};
 vector<pair<uint64_t,uint64_t>> oracle_nodes,oracle_groups;vector<Fact> oracle_facts;
 size_t oracle_hits=0;
 string initial; unordered_map<string,size_t> ids; deque<Node> nodes;
 size_t cap=500000, expanded=0, iterations=0, loaded=0; double seconds=30;
 chrono::steady_clock::time_point start; string reason="none";
 static uint64_t add(uint64_t a,uint64_t b){return a>=INF-b?INF:a+b;}
 int vertex(const string& k)const{return (unsigned char)k[0]+256*(unsigned char)k[1];}
 void setvertex(string& k,int v)const{k[0]=char(v&255);k[1]=char(v>>8);}
 unsigned cnt(const string& k,int e)const{return (unsigned char)k[e+2];}
 void read(const string& path){
  ifstream f(path); if(!(f>>N>>G>>current)||N<=0||N>65535||G<0||G>100000||current<0||current>=N)throw runtime_error("invalid graph header");
  src.resize(G);dst.resize(G);reverse.assign(G,-1);preferred.assign(G,1000000000);out.resize(N);inc.resize(N);initial.assign(G+2,0);setvertex(initial,current);
  unordered_map<uint64_t,int> pairmap;
  for(int i=0;i<G;i++){int c; if(!(f>>src[i]>>dst[i]>>c)||src[i]<0||src[i]>=N||dst[i]<0||dst[i]>=N||c<0||c>255)throw runtime_error("invalid graph edge");uint64_t p=uint64_t(src[i])*N+dst[i];if(!pairmap.emplace(p,i).second)throw runtime_error("duplicate grouped endpoint");initial[i+2]=char(c);out[src[i]].push_back(i);inc[dst[i]].push_back(i);}
  string extra;if(f>>extra)throw runtime_error("extra graph input");
  for(int i=0;i<G;i++){auto it=pairmap.find(uint64_t(dst[i])*N+src[i]);if(it!=pairmap.end())reverse[i]=it->second;}
  canonicalize(initial,true);
 }
 // Returns the independent local retrograde label, -1 for an unresolved core.
 int canonicalize(string& k,bool pairs=false,int* action=nullptr)const{
  if(action)*action=-1;
  if(pairs)for(int e=0;e<G;e++) {if(src[e]==dst[e])k[e+2]=char(cnt(k,e)%2);else if(reverse[e]>e){int r=reverse[e];unsigned d=min(cnt(k,e),cnt(k,r));k[e+2]=char(cnt(k,e)-d);k[r+2]=char(cnt(k,r)-d);}}
  vector<unsigned char> seen(N,0);vector<int> q;int v=vertex(k);seen[v]=1;q.push_back(v);
  for(size_t i=0;i<q.size();i++)for(int e:out[q[i]])if(cnt(k,e)&&!seen[dst[e]]){seen[dst[e]]=1;q.push_back(dst[e]);}
  for(int e=0;e<G;e++)if(!seen[src[e]])k[e+2]=0;
  vector<int> status(N,-1),left(N,0),loop(N,-1);q.clear();
  for(int u=0;u<N;u++){
   for(int e:out[u])if(cnt(k,e)){if(dst[e]==u)loop[u]=e;else left[u]+=cnt(k,e);}
   if(!left[u]){status[u]=loop[u]>=0; q.push_back(u);if(u==v&&action)*action=loop[u];}
  }
  for(size_t i=0;i<q.size();i++){
   int t=q[i];for(int e:inc[t]){int u=src[e];if(!cnt(k,e)||status[u]!=-1)continue;
    if(status[t]==0){status[u]=1;q.push_back(u);if(u==v&&action)*action=e;}
    else if((left[u]-=cnt(k,e))==0){status[u]=loop[u]>=0;q.push_back(u);if(u==v&&action)*action=loop[u];}
   }
  }
  if(status[v]!=-1)return status[v];
  fill(seen.begin(),seen.end(),0);q.clear();q.push_back(v);seen[v]=1;
  for(size_t i=0;i<q.size();i++)for(int e:out[q[i]])if(cnt(k,e)&&status[dst[e]]==-1&&!seen[dst[e]]){seen[dst[e]]=1;q.push_back(dst[e]);}
  for(int e=0;e<G;e++)if(!seen[src[e]]||status[dst[e]]!=-1)k[e+2]=0;
  return -1;
 }
 void check(){if((iterations++&1023)==0 && chrono::duration<double>(chrono::steady_clock::now()-start).count()>=seconds)throw Limit("time_limit");}
 size_t intern(string k){auto it=ids.find(k);if(it!=ids.end())return it->second;if(nodes.size()>=cap)throw Limit("state_limit");size_t id=nodes.size();auto ins=ids.emplace(move(k),id);nodes.emplace_back();nodes.back().key=&ins.first->first;return id;}
 string childkey(const string& k,int e)const{if(src[e]!=vertex(k)||!cnt(k,e))throw runtime_error("illegal internal move");string t=k;t[e+2]=char(cnt(t,e)-1);setvertex(t,dst[e]);canonicalize(t,false);return t;}
 void expand(size_t id){
  Node& n=nodes[id];if(n.expanded)return;
  string canonical=*n.key;int action=-1;int stat=canonicalize(canonical,false,&action);
  if(canonical!=*n.key)throw runtime_error("noncanonical search state");
  if(stat>=0){n.static_value=stat;n.pn=stat?0:INF;n.dn=stat?INF:0;n.best=action;n.expanded=true;expanded++;return;}
  // Build locally so a budget exception never publishes a partial child list.
  vector<pair<int,size_t>> children;int v=vertex(*n.key);
  for(int e:out[v])if(cnt(*n.key,e))children.push_back({e,intern(childkey(*n.key,e))});
  // Ordering is a heuristic only; proof status always comes from exact children.
  int suggested=oracle(*n.key)-1;
  auto degree=[&](size_t child){int d=0;const string& k=*nodes[child].key;for(int e:out[vertex(k)])if(cnt(k,e))d++;return d;};
  stable_sort(children.begin(),children.end(),[&](auto a,auto b){int da=degree(a.second),db=degree(b.second);if((a.first==suggested)!=(b.first==suggested))return a.first==suggested;if((da==0)!=(db==0))return da==0;if(preferred[a.first]!=preferred[b.first])return preferred[a.first]<preferred[b.first];return da<db;});
  n.children=move(children);n.expanded=true;expanded++;
  if(n.children.empty()){n.pn=INF;n.dn=0;n.best=-1;}
 }
 void update(size_t id){Node& n=nodes[id]; if(!n.expanded)throw runtime_error("unexpanded update");if(n.static_value>=0)return;n.pn=INF;n.dn=0;n.best=-1;
  for(auto [e,c]:n.children){auto& x=nodes[c];if(x.dn<n.pn){n.pn=x.dn;n.best=e;}n.dn=add(n.dn,x.pn);} 
 }
 void dfpn(size_t id,uint64_t pth,uint64_t dth,int depth=0){
  check();if(depth>10000)throw runtime_error("depth overflow");Node& n=nodes[id];if(n.pn==0||n.dn==0)return;expand(id);update(id);
  while(n.pn<pth && n.dn<dth){
   check();uint64_t first=INF,second=INF;size_t chosen=numeric_limits<size_t>::max();
   for(size_t j=0;j<n.children.size();j++){auto& c=nodes[n.children[j].second];if(c.dn<first){second=first;first=c.dn;chosen=j;}else if(c.dn<second)second=c.dn;}
   if(chosen==numeric_limits<size_t>::max())throw runtime_error("no DFPN child");
   size_t cid=n.children[chosen].second;uint64_t others=0;
   for(size_t j=0;j<n.children.size();j++)if(j!=chosen)others=add(others,nodes[n.children[j].second].pn);
   uint64_t cp=(dth==INF?INF:(dth>others?dth-others:1));
   uint64_t cd=min(pth,add(second,1));
   dfpn(cid,cp,cd,depth+1);update(id);
  }
 }
 void loadoracle(const string& path){
  if(path.empty())return;ifstream f(path,ios::binary);if(!f)throw runtime_error("cannot read hint oracle");char magic[8];f.read(magic,8);if(string(magic,8)!="R817O001")throw runtime_error("wrong oracle format");
  char hashes[64];f.read(hashes,64);if(!f)throw runtime_error("truncated oracle header");
  uint32_t n=get<uint32_t>(f),g=get<uint32_t>(f),count=get<uint32_t>(f);if(n!=uint32_t(N)||g!=uint32_t(G)||count>10000000)throw runtime_error("oracle dimensions mismatch");
  for(int i=0;i<N;i++){uint64_t a=get<uint64_t>(f),b=get<uint64_t>(f);oracle_nodes.push_back({a,b});}
  for(int i=0;i<G;i++){auto u=get<uint16_t>(f),v=get<uint16_t>(f);auto cap=get<uint8_t>(f);for(int j=0;j<3;j++)get<uint8_t>(f);if(u!=src[i]||v!=dst[i]||cap>7)throw runtime_error("oracle graph mismatch");for(int j=0;j<8;j++){uint64_t a=get<uint64_t>(f),b=get<uint64_t>(f);oracle_groups.push_back({a,b});}}
  for(uint32_t i=0;i<count;i++){Fact x;x.a=get<uint64_t>(f);x.b=get<uint64_t>(f);x.answer=int16_t(get<uint16_t>(f));if(i&&make_pair(x.a,x.b)<make_pair(oracle_facts.back().a,oracle_facts.back().b))throw runtime_error("unsorted hint oracle");oracle_facts.push_back(x);}if(f.peek()!=EOF)throw runtime_error("extra oracle bytes");
 }
 int oracle(const string& k){
  if(oracle_facts.empty())return 0;auto [a,b]=oracle_nodes[vertex(k)];
  for(int g=0;g<G;g++){unsigned c=cnt(k,g);if(c>7)return 0;if(c){a^=oracle_groups[g*8+c].first;b^=oracle_groups[g*8+c].second;}}
  auto it=lower_bound(oracle_facts.begin(),oracle_facts.end(),make_pair(a,b),[](const Fact&x,auto key){return make_pair(x.a,x.b)<key;});
  if(it!=oracle_facts.end()&&it->a==a&&it->b==b){oracle_hits++;return it->answer;}return 0;
 }
 void loadpreferences(const string& path){if(path.empty())return;ifstream f(path);if(!f)throw runtime_error("cannot read preference file");int e,rank=0;while(f>>e){if(e<0||e>=G)throw runtime_error("invalid preferred group");if(preferred[e]==1000000000)preferred[e]=rank++;}if(!f.eof())throw runtime_error("malformed preference file");}
 template<class T>static void put(ostream& f,T x){for(unsigned i=0;i<sizeof(T);i++)f.put(char((uint64_t(x)>>(8*i))&255));if(!f)throw runtime_error("cache write failed");}
 template<class T>static T get(istream& f){uint64_t x=0;for(unsigned i=0;i<sizeof(T);i++){int c=f.get();if(c<0)throw runtime_error("truncated cache");x|=uint64_t(c)<<(8*i);}return T(x);}
 void loadcache(const string& path){ifstream f(path,ios::binary);if(!f)return;char magic[8];f.read(magic,8);if(string(magic,8)!="R817C002")throw runtime_error("wrong cache format");if(get<uint32_t>(f)!=uint32_t(N)||get<uint32_t>(f)!=uint32_t(G))throw runtime_error("cache graph mismatch");for(int i=0;i<G;i++)if(get<uint32_t>(f)!=uint32_t(src[i])||get<uint32_t>(f)!=uint32_t(dst[i]))throw runtime_error("cache endpoints mismatch");uint64_t count=get<uint64_t>(f);if(count>cap)throw runtime_error("cache exceeds --nodes cap");
  for(uint64_t i=0;i<count;i++){string k(G+2,0);f.read(k.data(),k.size());if(!f)throw runtime_error("truncated state");int r=f.get();int best=int32_t(get<uint32_t>(f));if(vertex(k)>=N||(r!=0&&r!=1)||best < -1||best>=G)throw runtime_error("invalid cache record");size_t id=intern(move(k));Node& n=nodes[id];uint64_t pn=r?0:INF,dn=r?INF:0;if((n.pn==0||n.dn==0)&&(n.pn!=pn||n.dn!=dn))throw runtime_error("conflicting cache record");n.pn=pn;n.dn=dn;n.best=best;loaded++;}
  if(f.peek()!=EOF)throw runtime_error("extra cache bytes");
 }
 size_t savecache(const string& path){size_t count=0;for(auto& n:nodes)if(n.pn==0||n.dn==0)count++;string tmp=path+".tmp";ofstream f(tmp,ios::binary|ios::trunc);if(!f)throw runtime_error("cannot create cache");f.write("R817C002",8);put<uint32_t>(f,N);put<uint32_t>(f,G);for(int i=0;i<G;i++){put<uint32_t>(f,src[i]);put<uint32_t>(f,dst[i]);}put<uint64_t>(f,count);for(auto& n:nodes)if(n.pn==0||n.dn==0){f.write(n.key->data(),n.key->size());f.put(n.pn==0?1:0);put<uint32_t>(f,uint32_t(n.best));}f.close();if(!f)throw runtime_error("cache flush failed");if(rename(tmp.c_str(),path.c_str()))throw runtime_error("cache rename failed");return count;}
 static string hex(const string& s,size_t off){static const char* h="0123456789abcdef";string t;t.reserve((s.size()-off)*2);for(size_t i=off;i<s.size();i++){unsigned c=(unsigned char)s[i];t+=h[c>>4];t+=h[c&15];}return t;}
 size_t proof(size_t root,const string& path){
  // Write body separately to know root ID before header; postorder gives strict DAG order.
  string body=path+".body.tmp",tmp=path+".tmp";ofstream b(body);if(!b)throw runtime_error("cannot create proof body");unordered_map<size_t,size_t> emitted;size_t count=0;
  function<size_t(size_t)> emit=[&](size_t id)->size_t{auto old=emitted.find(id);if(old!=emitted.end())return old->second;const Node& n=nodes[id];if(n.pn!=0&&n.dn!=0)throw runtime_error("unknown proof node");vector<pair<int,size_t>> moves;int v=vertex(*n.key);string canonical=*n.key;int stat=canonicalize(canonical,false);if(canonical!=*n.key)throw runtime_error("noncanonical proof state");if(stat>=0&&stat!=(n.pn==0))throw runtime_error("wrong static cache label");if(stat<0)for(int e:out[v])if(cnt(*n.key,e)&&(n.dn==0||e==n.best)){string k=childkey(*n.key,e);auto it=ids.find(k);if(it==ids.end())throw runtime_error("missing proof child");const Node& c=nodes[it->second];if((n.pn==0&&c.dn!=0)||(n.dn==0&&c.pn!=0))throw runtime_error("wrong proof child outcome");moves.push_back({e,emit(it->second)});}if(stat<0&&n.pn==0&&moves.size()!=1)throw runtime_error("winning proof missing move");size_t pid=count++;emitted.emplace(id,pid);b<<"{\"id\":"<<pid<<",\"v\":"<<v<<",\"c\":\""<<hex(*n.key,2)<<"\",\"r\":\""<<(n.pn==0?'W':'L')<<"\",\"m\":[";for(size_t i=0;i<moves.size();i++){if(i)b<<',';b<<'['<<moves[i].first<<','<<moves[i].second<<']';}b<<"]}\n";if(!b)throw runtime_error("proof write failure");return pid;};
  size_t rid=emit(root);b.close();if(!b)throw runtime_error("proof flush failure");ofstream f(tmp);f<<"{\"format\":\"route-proof-v2\",\"groups\":"<<G<<",\"vertices\":"<<N<<",\"root\":"<<rid<<"}\n";ifstream in(body);f<<in.rdbuf();f.close();if(!f)throw runtime_error("proof finalize failure");if(rename(tmp.c_str(),path.c_str()))throw runtime_error("proof rename failure");remove(body.c_str());return count;
 }
};
int main(int argc,char**argv){try{if(argc<2)throw runtime_error("usage: solver INPUT [--seconds 30] [--nodes 500000] [--proof OUT] [--cache CACHE]");Solver s;string proof,cache,prefer,oracle;for(int i=2;i<argc;i++){string x=argv[i];if(i+1>=argc)throw runtime_error("missing option value");string v=argv[++i];if(x=="--seconds")s.seconds=stod(v);else if(x=="--nodes")s.cap=stoull(v);else if(x=="--proof")proof=v;else if(x=="--cache")cache=v;else if(x=="--prefer")prefer=v;else if(x=="--oracle")oracle=v;else throw runtime_error("unknown option: "+x);}if(!isfinite(s.seconds)||s.seconds<0||s.cap<1)throw runtime_error("invalid budget");s.read(argv[1]);s.loadpreferences(prefer);s.loadoracle(oracle);if(!cache.empty())s.loadcache(cache);s.start=chrono::steady_clock::now();size_t root;try{root=s.intern(s.initial);s.dfpn(root,INF,INF);}catch(const Limit& l){s.reason=l.what();auto it=s.ids.find(s.initial);if(it==s.ids.end())throw runtime_error("no capacity for root");root=it->second;}
 Node& n=s.nodes[root];string result=n.pn==0?"win":n.dn==0?"loss":"unknown";if(result=="unknown"&&s.reason=="none")s.reason="proof_number_saturation";double elapsed=chrono::duration<double>(chrono::steady_clock::now()-s.start).count();size_t pn=0;if(result!="unknown"&&!proof.empty())pn=s.proof(root,proof);size_t saved=0;if(!cache.empty())saved=s.savecache(cache);cout<<"{\"result\":\""<<result<<"\",\"reason\":\""<<s.reason<<"\",\"states\":"<<s.nodes.size()<<",\"expanded\":"<<s.expanded<<",\"iterations\":"<<s.iterations<<",\"seconds\":"<<fixed<<setprecision(6)<<elapsed<<",\"pn\":"<<n.pn<<",\"dn\":"<<n.dn<<",\"best_group\":"<<n.best<<",\"proof_nodes\":"<<pn<<",\"cache_loaded\":"<<s.loaded<<",\"oracle_hits\":"<<s.oracle_hits<<",\"cache_saved\":"<<saved<<"}\n";return 0;
}catch(const exception& e){cerr<<"solver error: "<<e.what()<<'\n';return 2;}}

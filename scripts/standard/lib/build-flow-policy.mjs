export function buildFlowPolicy(source, replay, digest) {
  const words=[], ids=new Map(), intern=word=>{if(!ids.has(word)){ids.set(word,words.length);words.push(word);}return ids.get(word);};
  const maps=new Map();
  // Build the established contexts first so their word IDs, tie ordering, and
  // examples remain unchanged when longer histories introduce older words.
  const collect = lengths => {
  for(const segment of replay.segments){
    const moves=segment.moves;
    for(let i=0;i<moves.length;i++){
      const m=moves[i]; if(m.playerId<0 || m.eligible===false)continue;
      const future=moves.slice(i,i+8).map(x=>intern(x.word));
      for(const length of lengths){
        if(length>i)break;
        const history=moves.slice(i-length,i).map(x=>intern(x.word));
        const key=JSON.stringify([m.current,m.shield,history]);
        let ctx=maps.get(key);
        if(!ctx){ctx={current:m.current,shield:m.shield,history,total:0,matches:new Set(),choices:new Map()};maps.set(key,ctx);}
        ctx.total++;ctx.matches.add(segment.matchId);
        const wid=intern(m.word);
        let c=ctx.choices.get(wid);
        if(!c){c={count:0,players:new Map(),matches:new Set(),lines:new Map()};ctx.choices.set(wid,c);}
        c.count++;c.players.set(m.playerId,(c.players.get(m.playerId)??0)+1);c.matches.add(segment.matchId);
        if(length>0){
          const fk=future.join(',');let line=c.lines.get(fk);
          if(!line){line={words:future,actors:moves.slice(i,i+8).map(x=>x.playerId),count:0,example:[segment.matchId,segment.round+1,i+1]};c.lines.set(fk,line);}
          line.count++;
        }
      }
    }
  }
  };
  collect([0,1,2,3,4,5,6,7,8]);
  collect([9,10,11,12]);
  const contexts=[...maps.values()].filter(c=>c.history.length===0 ||
    (c.history.length<=8 ? c.total>=2 && c.matches.size>=2 : c.total>=5 && c.matches.size>=5))
    .map(c=>[c.current,c.shield,c.history,c.total,c.matches.size,[...c.choices].sort((a,b)=>b[1].count-a[1].count||a[0]-b[0]).map(([id,x])=>[
      id,x.count,[...x.players].sort((a,b)=>a[0]-b[0]),x.matches.size,
      [...x.lines.values()].sort((a,b)=>b.count-a.count||b.words.length-a.words.length).slice(0,2).map(l=>[l.words,l.actors,l.count,l.example]),
    ])]);
  // Keep every turn for path matching, but explicitly mark excluded evidence.
  const effectEpisodes=replay.events.map(e=>[e.mode,e.before.map(intern),e.moves.slice(0,16).map(m=>[intern(m.word),m.playerId,m.reused?1:0,...(m.eligible===false?[1]:[])]),[e.matchId,e.round+1,e.afterMove+1],e.actor]);
  return {schemaVersion:1,kind:'sinyeon-flow-policy',createdAt:source.createdAt,
    source:{collectorVersion:source.collectorVersion,days:source.filters.days,matchCount:source.matchLedger.length,sha256:digest,
      rawSelectedMoveCount:replay.diagnostics.rawSelectedMoves,reportedRawSelectedMoveCount:source.stats.rawSelectedPlayerWords,
      firstMatchAt:source.matchLedger.map(x=>x.createdAt).filter(Boolean).sort()[0],
      lastMatchAt:source.matchLedger.map(x=>x.createdAt).filter(Boolean).sort().at(-1)},
    policy:{maxHistory:12,supportedHistory:8,longHistoryMinimumMatches:5,longHistoryMinimumMoves:5,
      historyPolicyVersion:'v1.27-history12-supported',minimumContextMatches:2,minimumContextMoves:2,playerSelection:replay.playerSelection,
      ranking:'longest-supported-sequence-with-playable-evidence-blend',
      effects:'observed-post-cast-only-no-duration-or-shield-inference'},
    diagnostics:replay.diagnostics,players:source.selectedPlayers.map(p=>p.displayName),words,contexts,effectEpisodes};
}

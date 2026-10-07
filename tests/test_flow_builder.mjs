import assert from 'node:assert/strict';
import test from 'node:test';
import {buildFlowPolicy} from '../scripts/standard/lib/build-flow-policy.mjs';

const history=Array.from({length:12},(_,i)=>`앞단어${i}`);
function build(segments,events=[]){
  const source={createdAt:'2026-10-02T00:00:00Z',collectorVersion:'fixture',filters:{days:120},
    stats:{rawSelectedPlayerWords:segments.length},selectedPlayers:[{displayName:'2606이엇던것'},{displayName:'삼룡'}],
    matchLedger:[...new Set(segments.map(s=>s.matchId))].map(matchId=>({matchId,createdAt:'2026-10-01T00:00:00Z'}))};
  return buildFlowPolicy(source,{segments,events,diagnostics:{rawSelectedMoves:segments.length},
    playerSelection:{version:'v1.26-ranked-only-five'}},'fixture-sha');
}
function segment(matchId,{eligible=true,playerId=0,word='선택',future=0}={}){
  return {matchId,round:0,moves:[...history.map(word=>({word,current:'앞',shield:0,playerId:-1})),
    {word,current:'선',shield:0,playerId,eligible},
    ...Array.from({length:future},(_,i)=>({word:`후속${i}`,current:'후',shield:0,playerId:-1}))]};
}
const lengths=data=>data.contexts.map(r=>r[2].length);

test('existing 0..8 contexts retain the two-match threshold',()=>{
  const data=build([segment('a'),segment('b')]);
  assert.deepEqual(lengths(data),[0,1,2,3,4,5,6,7,8]);
  assert.ok(data.contexts.every(r=>r[3]===2 && r[4]===2));
});

test('9..12 histories require five distinct games, not repeated rounds',()=>{
  const repeated=build(Array.from({length:8},()=>segment('same-game')));
  assert.deepEqual(lengths(repeated),[0]);
  const four=build(Array.from({length:4},(_,i)=>segment(String(i))));
  assert.ok(four.contexts.every(r=>r[2].length<=8));
  const five=build(Array.from({length:5},(_,i)=>segment(String(i))));
  assert.deepEqual(lengths(five),Array.from({length:13},(_,i)=>i));
  assert.ok(five.contexts.every(r=>r[3]===5 && r[4]===5));
  assert.deepEqual([five.policy.maxHistory,five.policy.supportedHistory,
    five.policy.longHistoryMinimumMatches,five.policy.longHistoryMinimumMoves],[12,8,5,5]);
  assert.equal(five.policy.historyPolicyVersion,'v1.27-history12-supported');
});

test('excluded friendly-game moves do not qualify long contexts',()=>{
  const four=Array.from({length:4},(_,i)=>segment(String(i)));
  const data=build([...four,segment('excluded',{eligible:false,playerId:1})]);
  assert.ok(data.contexts.every(r=>r[2].length<=8));
  assert.ok(data.contexts.every(r=>r[3]===4 && r[5][0][2].length===1 && r[5][0][2][0][0]===0));
  assert.deepEqual(data.policy.playerSelection,{version:'v1.26-ranked-only-five'});
});

test('future examples stay at eight moves and effects retain their separate limits',()=>{
  const segments=Array.from({length:5},(_,i)=>segment(String(i),{future:20}));
  const event={mode:'ECHO',before:history.slice(-8),moves:Array.from({length:20},(_,i)=>({word:`효과${i}`,playerId:1,reused:false,eligible:i!==0})),
    matchId:'0',round:1,afterMove:12,actor:1};
  const data=build(segments,[event]);
  for(const row of data.contexts.filter(r=>r[2].length>0))for(const c of row[5]){
    assert.equal(c[4][0][0].length,8);
    assert.equal(data.words[c[4][0][0][0]],'선택');
  }
  assert.equal(data.effectEpisodes[0][1].length,8);
  assert.equal(data.effectEpisodes[0][2].length,16);
  assert.deepEqual(data.effectEpisodes[0][2][0].slice(1),[1,0,1]);
});

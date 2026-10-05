// Replay only what the export explicitly records. Effect duration/expiry is not
// in bc/su/iu; never invent it or assign a 12-turn shield to those intervals.
import { evidenceAllowed, isRankedMatch, PLAYER_EVIDENCE_POLICY } from './player-evidence-policy.mjs';
const norm = value => String(value ?? "").normalize("NFC");
export function variants(syllable) {
  const code = syllable.charCodeAt(0) - 0xac00;
  if (code < 0 || code > 11171) return [syllable];
  const first = Math.floor(code / 588), vowel = Math.floor(code % 588 / 28), last = code % 28;
  const next = first === 5 ? ([2,6,7,12,17,20].includes(vowel) ? 11 : [0,1,8,11,13,18].includes(vowel) ? 2 : first)
    : first === 2 && [6,12,17,20].includes(vowel) ? 11 : first;
  return [...new Set([syllable, String.fromCharCode(0xac00 + next * 588 + vowel * 28 + last)])];
}
const end = word => Array.from(word).at(-1) ?? "";
const effectCodes = new Set(["SHIFTER", "ECHO", "MANNER"]);

export function replayRouteEvents(source) {
  const aliasIds = new Map(source.selectedPlayers.flatMap(p => [p.displayName, ...(p.aliases ?? [])]
    .map(name => [norm(name).toLowerCase(), p.playerId])));
  const rawProfiles = source.selectedPlayers.map(() => ({moveCount:0,matchCount:0,contexts:{ranked:0,item:0,skill:0,otherRule:0}}));
  const eligibleRawProfiles = source.selectedPlayers.map(() => ({moveCount:0,matchCount:0}));
  const matches = [], events = [], allSegments = [];
  const diagnostics = { rawMoves:0, rawSelectedMoves:0, unresolvedActors:0, correctedActorMoves:0,
    ordinaryMoves:0, ordinarySelectedMoves:0, ordinaryRounds:0, excludedAfterEffect:0,
    rejectedConnections:0, excludedFlavors:0, eventTriggers:{SHIFTER:0,ECHO:0,MANNER:0},
    rankedMatches:0,rankedRounds:0,rankedMoves:0,rankedSelectedMoves:0,
    excludedNonRankedRawMoves:0,excludedNonRankedOrdinaryMoves:0 };
  const seenMatches = new Set();
  for (const match of source.matchLedger ?? []) {
    if (seenMatches.has(String(match.matchId))) throw new Error(`중복 경기: ${match.matchId}`);
    seenMatches.add(String(match.matchId));
    const meta = match.metadata ?? {};
    if (meta.gameType !== "wordChainKo" || meta.nativeWordbookGroup !== "D" || meta.wordbooks?.native?.includes("3001"))
      throw new Error(`표준 한국어 끝말잇기가 아닌 경기: ${match.matchId}`);
    const byUser = new Map((meta.players ?? []).map(p => [String(p.userId), aliasIds.get(norm(p.nickname).toLowerCase()) ?? -1]));
    const oldOrder = [...(meta.players ?? [])].sort((a,b) => Number(a.order)-Number(b.order));
    const ranked = isRankedMatch(match);
    if (ranked) diagnostics.rankedMatches++;
    const allowedFlavor = (meta.flavors ?? []).every(x => ["skill","item"].includes(x));
    const seenPlayers = new Set();
    const eligiblePlayers = new Set();
    let round = -1, turnOrder = [], words = [], safe = false, required = "", prefix = [], segment = null;
    const replayedRounds = [];
    const ordered = (match.rawEvents ?? []).map((event,index) => ({event,index})).sort((a,b) =>
      Number(a.event.at ?? 0)-Number(b.event.at ?? 0) || Number(a.event.id ?? 0)-Number(b.event.id ?? 0) || a.index-b.index);
    const flush = () => {
      if (prefix.length) {
        replayedRounds.push(prefix); allSegments.push({matchId:String(match.matchId),round,mode:"ordinary",moves:prefix});
        diagnostics.ordinaryRounds++; if(ranked) diagnostics.rankedRounds++;
      }
      prefix = [];
    };
    const boundary = () => { flush(); safe = false; segment = null; };
    for (const {event:e,index:sourceIndex} of ordered) {
      if (e.type === "rs") {
        flush(); round++; words=[]; required=norm(e.payload?.[0]);
        turnOrder=(e.states ?? []).map(s=>String(s.id));
        safe=allowedFlavor && /^[가-힣]$/u.test(required) && turnOrder.length>0;
        segment=null; continue;
      }
      if (["ms","mc"].includes(e.type)) continue;
      if (e.type === "bc") {
        boundary();
        if (effectCodes.has(e.buff) && round>=0 && allowedFlavor) {
          diagnostics.eventTriggers[e.buff]++;
          segment={matchId:String(match.matchId),round,mode:e.buff,triggerIndex:sourceIndex,
            actor:byUser.get(String(e.to ?? e.from)) ?? -1,triggerUser:String(e.to ?? e.from),
            caster:String(e.from),triggerAt:Number(e.at),
            before:words.slice(-8).map(m=>m.word),moves:[],afterMove:words.length};
          events.push(segment);
        }
        continue;
      }
      if (e.type === "su" || e.type === "iu") {
        const code=e.skill ?? e.item;
        // The use log often follows its bc notification. Do not count it twice.
        if (segment && words.length === segment.afterMove && (code === segment.mode ||
          (!code && String(e.player) === segment.caster && Math.abs(Number(e.at)-segment.triggerAt)<=2))) continue;
        // A bare use log is not proof that its effect was successfully applied.
        boundary(); continue;
      }
      if(e.type!=="te"){boundary();continue;}
      const word=norm(e.input);
      if (!word) {flush();safe=false;segment=null;continue;}
      diagnostics.rawMoves++;
      const actorUser=Number.isInteger(e.turn) && e.turn>=0 ? turnOrder[e.turn] : undefined;
      const playerId=actorUser===undefined ? -1 : byUser.get(actorUser) ?? -1;
      const eligible=playerId<0 || evidenceAllowed(source.selectedPlayers.find(p=>p.playerId===playerId),ranked);
      if(actorUser===undefined || !byUser.has(actorUser)) diagnostics.unresolvedActors++;
      const oldId=aliasIds.get(norm(oldOrder[e.turn]?.nickname).toLowerCase()) ?? -1;
      if(oldId!==playerId)diagnostics.correctedActorMoves++;
      if(playerId>=0){rawProfiles[playerId].moveCount++;seenPlayers.add(playerId);diagnostics.rawSelectedMoves++;}
      if(playerId>=0 && eligible){eligibleRawProfiles[playerId].moveCount++;eligiblePlayers.add(playerId);}
      if(playerId>=0 && !eligible)diagnostics.excludedNonRankedRawMoves++;
      const reused=words.some(m=>m.word===word);
      const actualStart=Array.from(word)[0] ?? "";
      const move={word,playerId,eligible,current:required,shield:Math.max(12-words.length,0),
        matchId:String(match.matchId),round,ordinal:words.length,sourceIndex,reused};
      if(safe){
        if(!variants(required).includes(actualStart)||reused||actorUser===undefined){
          diagnostics.rejectedConnections++;boundary();
        } else {
          prefix.push(move);diagnostics.ordinaryMoves++;if(playerId>=0 && eligible)diagnostics.ordinarySelectedMoves++;
          if(playerId>=0 && !eligible)diagnostics.excludedNonRankedOrdinaryMoves++;
          if(ranked){diagnostics.rankedMoves++;if(playerId>=0)diagnostics.rankedSelectedMoves++;}
        }
      } else {diagnostics.excludedAfterEffect++;if(!allowedFlavor)diagnostics.excludedFlavors++;}
      if(segment){
        // These are observed post-effect sequences, not inferred effect states.
        segment.moves.push({...move,current:actualStart,shield:null});
      }
      words.push(move);required=end(word);
    }
    flush();
    for(const id of eligiblePlayers)eligibleRawProfiles[id].matchCount++;
    for(const id of seenPlayers){
      const p=rawProfiles[id];p.matchCount++;
      p.contexts.ranked+=Number(ranked);p.contexts.item+=Number(meta.flavors?.includes("item"));
      p.contexts.skill+=Number(meta.flavors?.includes("skill"));
      p.contexts.otherRule+=Number((meta.flavors ?? []).some(x=>!["item","skill"].includes(x)));
    }
    matches.push({...match,rawEvents:undefined,roundPolicies:[],rounds:replayedRounds.map(r=>r.map(m=>[m.current,m.shield,m.word,m.playerId,m.eligible]))});
  }
  return {matches,segments:allSegments,events:events.filter(e=>e.moves.length),rawProfiles,eligibleRawProfiles,diagnostics,playerSelection:PLAYER_EVIDENCE_POLICY};
}

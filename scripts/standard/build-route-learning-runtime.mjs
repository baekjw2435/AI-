import { readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createHash } from "node:crypto";
import { replayRouteEvents } from "./lib/replay-route-events.mjs";
import { buildFlowPolicy } from "./lib/build-flow-policy.mjs";
import { gunzipSync } from "node:zlib";
import { includeRankedMatches } from "./lib/ranked-route-overlay.mjs";
import { isRankedOnlyPlayer, PLAYER_EVIDENCE_POLICY } from "./lib/player-evidence-policy.mjs";

const inputFile = process.argv[2];
const outputFile = process.argv[3] ?? "standard_route_learning.json";

if (!inputFile) {
  throw new Error(
    "사용법: node scripts/build-route-learning-runtime.mjs <route-learning.json|json.gz> [output.json]",
  );
}

const sourceBuffer = await readFile(resolve(inputFile));
const isGzip = sourceBuffer[0] === 0x1f && sourceBuffer[1] === 0x8b;
const source = JSON.parse(
  (isGzip ? gunzipSync(sourceBuffer) : sourceBuffer).toString("utf8"),
);

const subsetDays = Number(process.argv[4] ?? 0);
if (subsetDays) {
  if (![7,14,30].includes(subsetDays)) throw new Error("최근 자료는 7·14·30일만 지원합니다.");
  const cutoff = Date.parse(source.createdAt) - subsetDays * 86400000;
  source.matchLedger = source.matchLedger.filter(m => Date.parse(m.createdAt) >= cutoff);
  source.filters.days = subsetDays;
  source.stats.downloadedMatches = source.matchLedger.length;
  source.stats.rawRounds = source.matchLedger.reduce((n,m) => n + m.rounds.length, 0);
  source.stats.rawSelectedPlayerWords = source.matchLedger.reduce((n,m) => n + m.rounds.flat().filter(x=>x[3]>=0).length, 0);
}

const SUPPORTED_ITEM_POLICIES = new Map([
  [
    "raw-events-separated-v1",
    "rs-te-only-no-flavors-normal-context-valid-chain-no-reuse",
  ],
  [
    "raw-events-separated-v2",
    "ordinary-visible-or-quick-no-flavors-no-league-valid-chain-no-reuse-no-uninterpreted-rule-events",
  ],
]);
if (
  source.kind !== "morae-sinpyo-route-learning-stats" ||
  ![3, 4].includes(source.schemaVersion) ||
  source.complete !== true ||
  source.detailErrors?.length
) {
  throw new Error("완료된 신표국 수순 학습 파일이 아닙니다.");
}

if (source.schemaVersion === 4 && (
  SUPPORTED_ITEM_POLICIES.get(source.itemPolicy?.version) !==
    source.itemPolicy?.baselineSelection ||
  !(source.stats.selectedPlayerWords > 0)
)) {
  throw new Error("아이템 원본은 보존됐지만 일반 학습 표본을 확인할 수 없습니다. 원본 사건을 검토한 뒤 연결하세요.");
}

const SEQUENCE_LENGTHS = [2, 3, 4, 6, 8];
if (source.schemaVersion !== 4) {
  throw new Error("v1.26 선수별 순위전 필터에는 경기 종류와 원본 사건이 있는 schema 4 파일이 필요합니다.");
}
const replay = source.schemaVersion === 4 ? replayRouteEvents(source) : null;
const seed = replay ? {
  ...source, wordTable: [], wordStats: [], currentRoutes: [], stateRoutes: [],
  historyChoices: {}, destinationStates: [], masterContinuations: {},
  stats: { ...source.stats, selectedPlayerWords: 0 }, matchLedger: replay.matches,
} : source;
const combined = includeRankedMatches(seed, { includeAll: Boolean(replay) });
const reviewedTotals = replay ? { ...combined.ranked } : null;
if (replay) combined.ranked = {
  matchCount: replay.diagnostics.rankedMatches, roundCount: replay.diagnostics.rankedRounds,
  wordCount: replay.diagnostics.rankedMoves, selectedMoveCount: replay.diagnostics.rankedSelectedMoves,
};

const playerCount = source.selectedPlayers.length;
const densePlayers = (rows = []) => {
  const result = Array(playerCount).fill(0);
  for (const [playerId, count] of rows) result[playerId] = count;
  return result;
};

const normalizeNickname = (value) =>
  String(value ?? "").normalize("NFC").toLowerCase();
const playerIdByAlias = new Map(
  source.selectedPlayers.flatMap((player) =>
    [player.displayName, ...(player.aliases ?? [])].map((alias) => [
      normalizeNickname(alias),
      player.playerId,
    ]),
  ),
);
const rawProfiles = replay?.rawProfiles ?? source.selectedPlayers.map(() => ({
  moveCount: 0, matchCount: 0, contexts: {ranked:0,item:0,skill:0,otherRule:0},
}));
const compactChoice = (choice) => [
  choice.wordId,
  choice.count,
  densePlayers(choice.byPlayer),
];
const compactRoute = (route, withShield) => [
  route.requiredSyllable,
  ...(withShield ? [route.shieldBefore] : []),
  route.total,
  densePlayers(route.byPlayer),
  route.choices.map(compactChoice),
];

const historyLimits = {
  1: source.modelSpec.minimumSamples.history1,
  2: source.modelSpec.minimumSamples.history2,
  3: source.modelSpec.minimumSamples.history3,
};
const histories = Object.fromEntries(
  [1, 2, 3].map((length) => [
    String(length),
    combined.historyChoices[String(length)]
      .filter((row) => row.total >= historyLimits[length])
      .map((row) => [
        row.requiredSyllable,
        row.shieldBefore,
        row.history,
        row.total,
        densePlayers(row.byPlayer),
        row.choices.slice(0, 12).map(compactChoice),
      ]),
  ]),
);

const destinations = combined.destinationStates
  .filter((row) => row.total >= 2)
  .map((row) => [
    row.endingSyllable,
    row.shieldAfter,
    row.total,
    densePlayers(row.byPlayer),
    row.sourceWords.slice(0, 20),
    row.responses.slice(0, 20),
    row.responses.length,
  ]);

const phaseForShield = (shield) =>
  shield >= 9 ? 0 : shield >= 5 ? 1 : shield >= 1 ? 2 : 3;
const combinedSelectedMoveCount =
  reviewedTotals?.selectedMoveCount ?? (source.stats.selectedPlayerWords + combined.ranked.selectedMoveCount);
const profiles = source.selectedPlayers.map((player) => {
  const moveRows = combined.wordStats
    .map((row) => {
      const count = densePlayers(row.byPlayer)[player.playerId];
      return [row.wordId, count, row.selectedCount];
    })
    .filter(([, count]) => count > 0);
  const moveCount = moveRows.reduce((sum, [, count]) => sum + count, 0);
  const expectedShare = moveCount / combinedSelectedMoveCount;
  const topWords = [...moveRows]
    .sort((a, b) => b[1] - a[1] || a[0] - b[0])
    .slice(0, 24)
    .map(([wordId, count]) => [wordId, count]);
  const signatureWords = moveRows
    .filter(([, count]) => count >= 3)
    .map(([wordId, count, allMastersCount]) => {
      const share = count / allMastersCount;
      const lift = expectedShare > 0 ? share / expectedShare : 0;
      return [wordId, count, allMastersCount, share, lift, Math.log1p(count) * lift];
    })
    .sort((a, b) => b[5] - a[5] || b[1] - a[1] || a[0] - b[0])
    .slice(0, 24)
    .map(([wordId, count, allMastersCount, share, lift]) => [
      wordId,
      count,
      allMastersCount,
      Number(share.toFixed(4)),
      Number(lift.toFixed(3)),
    ]);
  const topCurrents = combined.currentRoutes
    .map((row) => [
      row.requiredSyllable,
      densePlayers(row.byPlayer)[player.playerId],
    ])
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ko"))
    .slice(0, 20);
  const phaseCounts = [0, 0, 0, 0];
  for (const row of combined.stateRoutes) {
    phaseCounts[phaseForShield(row.shieldBefore)] +=
      densePlayers(row.byPlayer)[player.playerId];
  }

  const topSequences = {};
  const repeatedSequencePatterns = {};
  for (const length of SEQUENCE_LENGTHS) {
    const rows = (combined.masterContinuations[String(length)] ?? [])
      .map((row) => ({
        current: row.requiredSyllable,
        shield: row.shieldBefore,
        actorPattern: row.actorPattern,
        words: row.words,
        count: densePlayers(row.byPlayer)[player.playerId],
      }))
      .filter((row) => row.count >= 2);
    repeatedSequencePatterns[length] = rows.length;
    topSequences[length] = rows
      .sort(
        (a, b) =>
          b.count - a.count ||
          a.words.join("\u0001").localeCompare(b.words.join("\u0001"), "ko"),
      )
      .slice(0, 16)
      .map((row) => [
        row.current,
        row.shield,
        row.actorPattern,
        row.words,
        row.count,
      ]);
  }

  return {
    name: player.displayName,
    evidenceScope: isRankedOnlyPlayer(player) ? "ranked-only" : "existing-verified",
    eligibleRawMoveCount: replay.eligibleRawProfiles[player.playerId].moveCount,
    eligibleRawMatchCount: replay.eligibleRawProfiles[player.playerId].matchCount,
    moveCount,
    rawMoveCount: rawProfiles[player.playerId]?.moveCount ?? moveCount,
    rawMatchCount: rawProfiles[player.playerId]?.matchCount ?? 0,
    rawContexts: rawProfiles[player.playerId]?.contexts ?? {
      ranked: 0,
      item: 0,
      skill: 0,
      otherRule: 0,
    },
    uniqueWordCount: moveRows.length,
    phaseCounts,
    topCurrents,
    topWords,
    signatureWords,
    repeatedSequencePatterns,
    topSequences,
  };
});

const sequenceStates = {};
for (const length of SEQUENCE_LENGTHS) {
  const buckets = new Map();
  for (const row of combined.masterContinuations[String(length)] ?? []) {
    for (const [playerId, count] of row.byPlayer) {
      if (count < 2) continue;
      const key = [
        row.requiredSyllable,
        row.shieldBefore,
        playerId,
      ].join("\u0001");
      const bucket = buckets.get(key) ?? [];
      bucket.push([
        row.requiredSyllable,
        row.shieldBefore,
        playerId,
        row.actorPattern,
        row.words,
        count,
      ]);
      buckets.set(key, bucket);
    }
  }
  sequenceStates[length] = [...buckets.values()].flatMap((rows) =>
    rows
      .sort(
        (a, b) =>
          b[5] - a[5] ||
          a[4].join("\u0001").localeCompare(b[4].join("\u0001"), "ko"),
      )
      .slice(0, 6),
  );
}

const runtime = {
  schemaVersion: 1,
  kind: "sinyeon-route-learning-runtime",
  createdAt: source.createdAt,
  playerSelection: PLAYER_EVIDENCE_POLICY,
  source: {
    collectorVersion: source.collectorVersion,
    days: source.filters.days,
    matchCount: source.stats.downloadedMatches,
    roundCount: reviewedTotals?.roundCount ?? source.stats.rounds + combined.ranked.roundCount,
    wordCount: reviewedTotals?.wordCount ?? source.stats.words + combined.ranked.wordCount,
    selectedMoveCount:
      reviewedTotals?.selectedMoveCount ?? source.stats.selectedPlayerWords + combined.ranked.selectedMoveCount,
    uniqueWordCount: combined.wordTable.length,
    historyContextCounts: Object.fromEntries(
      [1, 2, 3].map((length) => [
        String(length),
        combined.historyChoices[String(length)].length,
      ]),
    ),
    sequenceCounts: Object.fromEntries(
      SEQUENCE_LENGTHS.map((length) => [
        String(length),
        combined.masterContinuations[String(length)].length,
      ]),
    ),
    destinationStateCount: combined.destinationStates.length,
    exactStateMinimumSample: 2,
    ...(source.schemaVersion === 4 ? {
      rawRoundCount: source.stats.rawRounds,
      rawSelectedMoveCount: replay?.diagnostics.rawSelectedMoves ?? source.stats.rawSelectedPlayerWords,
      reportedRawSelectedMoveCount: source.stats.rawSelectedPlayerWords,
      itemReviewRoundCount: Math.max(
        0,
        source.stats.rawRounds - (reviewedTotals?.roundCount ?? source.stats.rounds + combined.ranked.roundCount),
      ),
      itemPolicyVersion: source.itemPolicy.version,
      evidenceScope: replay ? "verified-prefixes-before-rule-events" : "ordinary-plus-ranked",
      rankedMatchCount: combined.ranked.matchCount,
      rankedRoundCount: combined.ranked.roundCount,
      rankedSelectedMoveCount: combined.ranked.selectedMoveCount,
    } : {}),
  },
  model: {
    name: source.modelSpec.name,
    weights: source.modelSpec.weights,
    minimumSamples: source.modelSpec.minimumSamples,
    fallbackOrder: source.modelSpec.fallbackOrder,
    generalization: source.modelSpec.generalization,
  },
  players: source.selectedPlayers.map((player) => ({
    name: player.displayName,
    aliases: player.aliases,
  })),
  words: combined.wordTable,
  currentRoutes: combined.currentRoutes.map((row) => compactRoute(row, false)),
  stateRoutes: combined.stateRoutes.map((row) => compactRoute(row, true)),
  histories,
  destinations,
  profiles,
  sequenceStates,
};

if (replay && !subsetDays) {
  const policy = buildFlowPolicy(source, replay, createHash("sha256").update(sourceBuffer).digest("hex"));
  await writeFile(resolve(outputFile.replace(/[^/]+$/, "standard_flow_policy.json")), JSON.stringify(policy));
  console.log("Replay:", JSON.stringify(replay.diagnostics));
  console.log("Flow:", policy.contexts.length, "contexts;", policy.effectEpisodes.length, "effect episodes");
}
const serialized = JSON.stringify(runtime);
await writeFile(resolve(outputFile), serialized);
console.log(
  `${outputFile}: ${(Buffer.byteLength(serialized) / 1024 / 1024).toFixed(2)} MiB · ` +
    `${histories[1].length + histories[2].length + histories[3].length}개 학습 문맥 · ` +
    `순위전 ${combined.ranked.matchCount}경기/${combined.ranked.selectedMoveCount}수 병합`,
);

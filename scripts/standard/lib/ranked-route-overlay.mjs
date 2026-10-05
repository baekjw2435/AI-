const SEQUENCE_LENGTHS = [2, 3, 4, 6, 8];

import { isRankedMatch } from './player-evidence-policy.mjs';

const addCount = (map, key, count = 1) =>
  map.set(key, (map.get(key) ?? 0) + count);

const addPairs = (map, pairs = []) => {
  for (const [key, count] of pairs) addCount(map, key, count);
};

const sortedPairs = (map) =>
  [...map.entries()].sort((a, b) => Number(a[0]) - Number(b[0]));

const rankedPairs = (map) =>
  [...map.entries()].sort((a, b) => b[1] - a[1] || Number(a[0]) - Number(b[0]));

function choiceBucket() {
  return { count: 0, byPlayer: new Map() };
}

function addChoice(bucket, wordId, playerId, count = 1) {
  const choice = bucket.choices.get(wordId) ?? choiceBucket();
  choice.count += count;
  if (playerId >= 0) addCount(choice.byPlayer, playerId, count);
  bucket.choices.set(wordId, choice);
}

function seedRouteRows(rows, withShield) {
  const map = new Map();
  for (const row of rows) {
    const key = withShield
      ? `${row.requiredSyllable}\u0000${row.shieldBefore}`
      : row.requiredSyllable;
    const bucket = {
      requiredSyllable: row.requiredSyllable,
      ...(withShield ? { shieldBefore: row.shieldBefore } : {}),
      total: row.total,
      byPlayer: new Map(),
      choices: new Map(),
    };
    addPairs(bucket.byPlayer, row.byPlayer);
    for (const choice of row.choices) {
      const seeded = choiceBucket();
      seeded.count = choice.count;
      addPairs(seeded.byPlayer, choice.byPlayer);
      bucket.choices.set(choice.wordId, seeded);
    }
    map.set(key, bucket);
  }
  return map;
}

function finishRouteRows(map, withShield) {
  return [...map.values()]
    .map((bucket) => ({
      requiredSyllable: bucket.requiredSyllable,
      ...(withShield ? { shieldBefore: bucket.shieldBefore } : {}),
      total: bucket.total,
      byPlayer: sortedPairs(bucket.byPlayer),
      choices: [...bucket.choices.entries()]
        .map(([wordId, choice]) => ({
          wordId,
          count: choice.count,
          byPlayer: sortedPairs(choice.byPlayer),
        }))
        .sort((a, b) => b.count - a.count || a.wordId - b.wordId),
    }))
    .sort(
      (a, b) =>
        a.requiredSyllable.localeCompare(b.requiredSyllable, "ko") ||
        (withShield ? b.shieldBefore - a.shieldBefore : 0),
    );
}

function addRouteMove(map, requiredSyllable, shieldBefore, wordId, playerId, withShield) {
  const key = withShield
    ? `${requiredSyllable}\u0000${shieldBefore}`
    : requiredSyllable;
  const bucket = map.get(key) ?? {
    requiredSyllable,
    ...(withShield ? { shieldBefore } : {}),
    total: 0,
    byPlayer: new Map(),
    choices: new Map(),
  };
  bucket.total += 1;
  addCount(bucket.byPlayer, playerId);
  addChoice(bucket, wordId, playerId);
  map.set(key, bucket);
}

function seedHistories(source) {
  return Object.fromEntries([1, 2, 3].map((length) => {
    const map = new Map();
    for (const row of source.historyChoices[String(length)] ?? []) {
      const key = `${row.requiredSyllable}\u0000${row.shieldBefore}\u0000${row.history.join(",")}`;
      const bucket = {
        requiredSyllable: row.requiredSyllable,
        shieldBefore: row.shieldBefore,
        history: [...row.history],
        total: row.total,
        byPlayer: new Map(),
        choices: new Map(),
      };
      addPairs(bucket.byPlayer, row.byPlayer);
      for (const choice of row.choices) {
        const seeded = choiceBucket();
        seeded.count = choice.count;
        addPairs(seeded.byPlayer, choice.byPlayer);
        bucket.choices.set(choice.wordId, seeded);
      }
      map.set(key, bucket);
    }
    return [String(length), map];
  }));
}

function finishHistories(maps) {
  return Object.fromEntries([1, 2, 3].map((length) => [
    String(length),
    [...maps[String(length)].values()]
      .map((bucket) => ({
        requiredSyllable: bucket.requiredSyllable,
        shieldBefore: bucket.shieldBefore,
        history: bucket.history,
        total: bucket.total,
        byPlayer: sortedPairs(bucket.byPlayer),
        choices: [...bucket.choices.entries()]
          .map(([wordId, choice]) => ({
            wordId,
            count: choice.count,
            byPlayer: sortedPairs(choice.byPlayer),
          }))
          .sort((a, b) => b.count - a.count || a.wordId - b.wordId),
      }))
      .sort((a, b) => b.total - a.total),
  ]));
}

function seedWordStats(source) {
  const map = new Map();
  for (const row of source.wordStats) {
    const bucket = {
      wordId: row.wordId,
      endingSyllable: row.endingSyllable,
      allCount: row.allCount,
      selectedCount: row.selectedCount,
      selectedByShield: new Map(),
      byPlayer: new Map(),
    };
    addPairs(bucket.selectedByShield, row.selectedByShield);
    addPairs(bucket.byPlayer, row.byPlayer);
    map.set(row.wordId, bucket);
  }
  return map;
}

function finishWordStats(map) {
  return [...map.values()]
    .map((bucket) => ({
      wordId: bucket.wordId,
      endingSyllable: bucket.endingSyllable,
      allCount: bucket.allCount,
      selectedCount: bucket.selectedCount,
      selectedByShield: [...bucket.selectedByShield.entries()].sort((a, b) => b[0] - a[0]),
      byPlayer: sortedPairs(bucket.byPlayer),
    }))
    .sort((a, b) => a.wordId - b.wordId);
}

function seedDestinations(source) {
  const map = new Map();
  for (const row of source.destinationStates) {
    const key = `${row.endingSyllable}\u0000${row.shieldAfter}`;
    const bucket = {
      endingSyllable: row.endingSyllable,
      shieldAfter: row.shieldAfter,
      total: row.total,
      byPlayer: new Map(),
      sourceWords: new Map(),
      responses: new Map(),
    };
    addPairs(bucket.byPlayer, row.byPlayer);
    addPairs(bucket.sourceWords, row.sourceWords);
    addPairs(bucket.responses, row.responses);
    map.set(key, bucket);
  }
  return map;
}

function finishDestinations(map) {
  return [...map.values()]
    .map((bucket) => ({
      endingSyllable: bucket.endingSyllable,
      shieldAfter: bucket.shieldAfter,
      total: bucket.total,
      byPlayer: sortedPairs(bucket.byPlayer),
      sourceWords: rankedPairs(bucket.sourceWords),
      responses: rankedPairs(bucket.responses),
    }))
    .sort(
      (a, b) =>
        a.endingSyllable.localeCompare(b.endingSyllable, "ko") ||
        b.shieldAfter - a.shieldAfter,
    );
}

function seedMasterContinuations(source) {
  return Object.fromEntries(SEQUENCE_LENGTHS.map((length) => {
    const map = new Map();
    for (const row of source.masterContinuations[String(length)] ?? []) {
      const key = `${row.requiredSyllable}\u0000${row.shieldBefore}\u0000${row.actorPattern}\u0000${row.words.join(",")}`;
      const bucket = {
        requiredSyllable: row.requiredSyllable,
        shieldBefore: row.shieldBefore,
        actorPattern: row.actorPattern,
        words: [...row.words],
        count: row.count,
        byPlayer: new Map(),
      };
      addPairs(bucket.byPlayer, row.byPlayer);
      map.set(key, bucket);
    }
    return [String(length), map];
  }));
}

function finishMasterContinuations(maps) {
  return Object.fromEntries(SEQUENCE_LENGTHS.map((length) => [
    String(length),
    [...maps[String(length)].values()]
      .map((bucket) => ({
        requiredSyllable: bucket.requiredSyllable,
        shieldBefore: bucket.shieldBefore,
        actorPattern: bucket.actorPattern,
        words: bucket.words,
        count: bucket.count,
        byPlayer: sortedPairs(bucket.byPlayer),
      }))
      .sort((a, b) => b.count - a.count),
  ]));
}

export function includeRankedMatches(source, options = {}) {
  const wordTable = [...source.wordTable];
  const wordIdByWord = new Map(wordTable.map((word, wordId) => [word, wordId]));
  const internWord = (word) => {
    const normalized = String(word ?? "").normalize("NFC");
    const existing = wordIdByWord.get(normalized);
    if (existing !== undefined) return existing;
    const wordId = wordTable.length;
    wordTable.push(normalized);
    wordIdByWord.set(normalized, wordId);
    return wordId;
  };

  const wordStats = seedWordStats(source);
  const currentRoutes = seedRouteRows(source.currentRoutes, false);
  const stateRoutes = seedRouteRows(source.stateRoutes, true);
  const histories = seedHistories(source);
  const destinations = seedDestinations(source);
  const masterContinuations = seedMasterContinuations(source);

  let matchCount = 0;
  let roundCount = 0;
  let wordCount = 0;
  let selectedMoveCount = 0;
  let destinationMoveCount = 0;

  for (const match of source.matchLedger ?? []) {
    if (!options.includeAll && !isRankedMatch(match)) continue;
    matchCount += 1;
    if ((match.roundPolicies ?? []).some((policy) => policy.baselineEligible)) {
      throw new Error(`순위전 ${match.matchId}이 기존 일반 집계에도 들어 있어 중복됩니다.`);
    }

    for (const round of match.rounds ?? []) {
      if (!round.length) continue;
      roundCount += 1;
      const moves = round.map(([requiredSyllable, , word, playerId, eligible = true]) => ({
        requiredSyllable: String(requiredSyllable ?? "").normalize("NFC"),
        word: String(word ?? "").normalize("NFC"),
        wordId: internWord(word),
        playerId: Number(playerId),
        eligible,
      }));
      wordCount += moves.length;

      for (let index = 0; index < moves.length; index += 1) {
        const move = moves[index];
        const shieldBefore = Math.max(12 - index, 0);
        const stats = wordStats.get(move.wordId) ?? {
          wordId: move.wordId,
          endingSyllable: Array.from(move.word).at(-1) ?? "",
          allCount: 0,
          selectedCount: 0,
          selectedByShield: new Map(),
          byPlayer: new Map(),
        };
        stats.allCount += 1;
        wordStats.set(move.wordId, stats);

        if (!Number.isInteger(move.playerId) || move.playerId < 0 || !move.eligible) continue;
        selectedMoveCount += 1;
        stats.selectedCount += 1;
        addCount(stats.selectedByShield, shieldBefore);
        addCount(stats.byPlayer, move.playerId);

        addRouteMove(
          currentRoutes,
          move.requiredSyllable,
          shieldBefore,
          move.wordId,
          move.playerId,
          false,
        );
        addRouteMove(
          stateRoutes,
          move.requiredSyllable,
          shieldBefore,
          move.wordId,
          move.playerId,
          true,
        );

        for (const historyLength of [1, 2, 3]) {
          if (index < historyLength) continue;
          const history = moves
            .slice(index - historyLength, index)
            .map((historyMove) => historyMove.wordId);
          const key = `${move.requiredSyllable}\u0000${shieldBefore}\u0000${history.join(",")}`;
          const map = histories[String(historyLength)];
          const bucket = map.get(key) ?? {
            requiredSyllable: move.requiredSyllable,
            shieldBefore,
            history,
            total: 0,
            byPlayer: new Map(),
            choices: new Map(),
          };
          bucket.total += 1;
          addCount(bucket.byPlayer, move.playerId);
          addChoice(bucket, move.wordId, move.playerId);
          map.set(key, bucket);
        }

        const nextMove = moves[index + 1];
        const endingSyllable = Array.from(move.word).at(-1) ?? "";
        if (nextMove && nextMove.requiredSyllable === endingSyllable) {
          const shieldAfter = Math.max(12 - (index + 1), 0);
          const key = `${endingSyllable}\u0000${shieldAfter}`;
          const bucket = destinations.get(key) ?? {
            endingSyllable,
            shieldAfter,
            total: 0,
            byPlayer: new Map(),
            sourceWords: new Map(),
            responses: new Map(),
          };
          bucket.total += 1;
          destinationMoveCount += 1;
          addCount(bucket.byPlayer, move.playerId);
          addCount(bucket.sourceWords, move.wordId);
          addCount(bucket.responses, nextMove.wordId);
          destinations.set(key, bucket);
        }

        for (const length of SEQUENCE_LENGTHS) {
          if (index + length > moves.length) continue;
          const sequence = moves.slice(index, index + length);
          const actorPattern = sequence
            .map((sequenceMove) => sequenceMove.playerId >= 0 ? "M" : "O")
            .join("");
          const words = sequence.map((sequenceMove) => sequenceMove.wordId);
          const key = `${move.requiredSyllable}\u0000${shieldBefore}\u0000${actorPattern}\u0000${words.join(",")}`;
          const map = masterContinuations[String(length)];
          const bucket = map.get(key) ?? {
            requiredSyllable: move.requiredSyllable,
            shieldBefore,
            actorPattern,
            words,
            count: 0,
            byPlayer: new Map(),
          };
          bucket.count += 1;
          addCount(bucket.byPlayer, move.playerId);
          map.set(key, bucket);
        }
      }
    }
  }

  const result = {
    wordTable,
    wordStats: finishWordStats(wordStats),
    currentRoutes: finishRouteRows(currentRoutes, false),
    stateRoutes: finishRouteRows(stateRoutes, true),
    historyChoices: finishHistories(histories),
    destinationStates: finishDestinations(destinations),
    masterContinuations: finishMasterContinuations(masterContinuations),
    ranked: {
      matchCount,
      roundCount,
      wordCount,
      selectedMoveCount,
      destinationMoveCount,
    },
  };

  const routeTotal = result.currentRoutes.reduce((sum, row) => sum + row.total, 0);
  const stateTotal = result.stateRoutes.reduce((sum, row) => sum + row.total, 0);
  const expectedSelected = source.stats.selectedPlayerWords + selectedMoveCount;
  if (routeTotal !== expectedSelected || stateTotal !== expectedSelected) {
    throw new Error(
      `일반+순위전 선택 수 합계가 맞지 않습니다: ${routeTotal}/${stateTotal}/${expectedSelected}`,
    );
  }

  return result;
}

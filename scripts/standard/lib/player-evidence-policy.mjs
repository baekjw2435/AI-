// Player identity and opponent context stay intact; only evidence eligibility changes.
export const RANKED_ONLY_PLAYERS = Object.freeze([
  "즈나니에츠키", "강건", "삼룡", "갓갓다리", "공볂",
]);
export const PLAYER_EVIDENCE_POLICY = Object.freeze({
  version: "v1.26-ranked-only-five",
  unchangedPlayers: ["2606이엇던것", "단몌", "둑지꽝", "보초", "kalskiju", "죽을죄"],
  rankedOnlyPlayers: RANKED_ONLY_PLAYERS,
  rankedDefinition: "matchType=ranked-or-leagueId-present",
});
export const isRankedMatch = match =>
  match.metadata?.matchType === "ranked" || match.metadata?.leagueId != null;
export const isRankedOnlyPlayer = player =>
  RANKED_ONLY_PLAYERS.includes(String(player?.displayName ?? "").normalize("NFC"));
export const evidenceAllowed = (player, ranked) => !isRankedOnlyPlayer(player) || ranked;

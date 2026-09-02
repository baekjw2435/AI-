# -*- coding: utf-8 -*-
"""신엜 루트 탐색기 v1.16 추천 엔진을 그대로 옮긴 모듈입니다.

사이트의 lib/route-learning.ts 와 lib/engine.ts 계산을 파이썬으로 옮겼습니다.
숫자가 사이트와 어긋나면 안 되므로 가중치·최소표본·반올림 방식까지 같게 맞췄습니다.

표준(신표국) 자료만 사용합니다. 복합 자료와는 절대 섞지 않습니다.
"""

import json, math

# 자바스크립트 Math.round 는 .5 를 항상 올림합니다. 파이썬 round 는 짝수로 반올림하므로
# 점수가 사이트와 달라집니다. 사이트와 같은 값을 내려면 이 함수를 써야 합니다.
def js_round(x):
    return math.floor(x + 0.5)

def clamp(value, low, high):
    return max(low, min(high, value))

def confidence(total, prior):
    return total / (total + prior) if total > 0 else 0.0

# 가운뎃점(U+00B7)은 단어를 맞춰 볼 때 무시합니다. 확정 연구 수순은 `핀·우그리아어족`
# 처럼 적혀 있지만 실제 사전과 학습 자료의 표기는 `핀우그리아어족` 이라 그대로 두면
# 규칙이 후보와 맞지 않습니다.
MIDDLE_DOT = "\u00b7"

def strip_dots(word):
    return word.replace(MIDDLE_DOT, "")


# ---------------------------------------------------------------------
# 표준두음법칙 (사이트 lib/hangul.ts 와 같은 매핑)
# ---------------------------------------------------------------------
def _dec(ch):
    o = ord(ch) - 0xAC00
    return None if o < 0 or o > 11171 else (o // 588, (o % 588) // 28, o % 28)

def dueum(ch):
    d = _dec(ch)
    if not d: return None
    c, j, k = d
    if c == 5:
        if j in (2, 6, 7, 12, 17, 20): return chr(0xAC00 + (11 * 21 + j) * 28 + k)
        if j in (0, 1, 8, 11, 13, 18): return chr(0xAC00 + (2 * 21 + j) * 28 + k)
    elif c == 2:
        if j in (6, 12, 17, 20): return chr(0xAC00 + (11 * 21 + j) * 28 + k)
    return None

def dueum_variants(syl):
    """사이트 dueumVariants 와 같습니다. 원래 음절을 포함하고 변형은 최대 하나입니다."""
    if not syl: return []
    if _dec(syl) is None: return [syl]
    out = [syl]
    du = dueum(syl)
    if du and du != syl: out.append(du)
    return out


# ---------------------------------------------------------------------
# 학습 자료 색인
# ---------------------------------------------------------------------
SEQUENCE_LENGTHS = (2, 3, 4, 6, 8)

class RouteLearning:
    """route-learning 런타임 파일 하나를 색인합니다."""

    def __init__(self, data):
        self.words = data["words"]
        self.model = data["model"]
        self.source = data["source"]
        self.word_to_id = {w: i for i, w in enumerate(self.words)}

        # 현재 음절 -> (total, choices{wordId: count})
        self.current = {}
        for row in data["currentRoutes"]:
            syl, total, _players, choices = row
            self.current[syl] = (total, {c[0]: c[1] for c in choices})

        # 현재 음절+보호막 -> (total, choices)
        self.states = {}
        for row in data["stateRoutes"]:
            syl, shield, total, _players, choices = row
            self.states[(syl, shield)] = (total, {c[0]: c[1] for c in choices})

        # 직전 1·2·3수 문맥
        self.histories = {1: {}, 2: {}, 3: {}}
        for length in (1, 2, 3):
            bucket = self.histories[length]
            for row in data["histories"][str(length)]:
                syl, shield, hist, total, _players, choices = row
                bucket[(syl, shield, tuple(hist))] = (total, {c[0]: c[1] for c in choices})

        # 도착 상태
        self.destinations = {}
        for row in data["destinations"]:
            ending, shield_after, total, _players, sources, responses, unique = row
            self.destinations[(ending, shield_after)] = {
                "total": total,
                "responses": responses,
                "unique": unique,
            }

        # 실제 연결 수순: (음절, 보호막, 선수) -> [행]
        self.sequences = {n: {} for n in SEQUENCE_LENGTHS}
        for n in SEQUENCE_LENGTHS:
            bucket = self.sequences[n]
            for row in data.get("sequenceStates", {}).get(str(n), []):
                syl, shield, player_id = row[0], row[1], row[2]
                bucket.setdefault((syl, shield, player_id), []).append(row)

    # -- 문맥 조회 ----------------------------------------------------
    def _contexts(self, current, shield=None):
        out = []
        seen = set()
        for v in dueum_variants(current):
            if v in seen: continue
            seen.add(v)
            ctx = self.current.get(v) if shield is None else self.states.get((v, shield))
            if ctx: out.append(ctx)
        return out

    @staticmethod
    def _total(contexts):
        return sum(c[0] for c in contexts)

    @staticmethod
    def _choice(contexts, word_id):
        if word_id is None: return 0
        return sum(c[1].get(word_id, 0) for c in contexts)


EMPTY_EVIDENCE = {
    "score": 0.0, "hasEvidence": False, "matchedHistoryLength": 0,
    "historyCount": 0, "historyTotal": 0,
    "exactCount": 0, "exactTotal": 0, "exactSource": "none",
    "destinationTotal": 0,
}


def state_evidence(data, current, shield):
    """사이트 getRouteLearningStateEvidence 와 같습니다."""
    minimum = (data.source.get("exactStateMinimumSample", 2) if data else 2)
    if not data or not current:
        return {"mode": "none", "minimumSample": minimum, "shieldTotal": 0,
                "overallTotal": 0, "shieldWords": {}, "overallWords": {}}
    shield_ctx = data._contexts(current, shield)
    overall_ctx = data._contexts(current)
    shield_total = data._total(shield_ctx)
    overall_total = data._total(overall_ctx)
    shield_words, overall_words = {}, {}
    for _t, choices in shield_ctx:
        for wid, n in choices.items(): shield_words[wid] = shield_words.get(wid, 0) + n
    for _t, choices in overall_ctx:
        for wid, n in choices.items(): overall_words[wid] = overall_words.get(wid, 0) + n
    mode = "shield" if shield_total >= minimum else ("overall" if overall_total > 0 else "none")
    return {"mode": mode, "minimumSample": minimum, "shieldTotal": shield_total,
            "overallTotal": overall_total, "shieldWords": shield_words,
            "overallWords": overall_words}


def learning_evidence(data, current, shield, history_words, word, ending, structural=0.0):
    """사이트 getRouteLearningEvidence 와 같습니다."""
    if not data or not current:
        return dict(EMPTY_EVIDENCE)
    word_id = data.word_to_id.get(word)
    variants = []
    for v in dueum_variants(current):
        if v not in variants: variants.append(v)

    matched = 0
    history_contexts = []
    for length in (3, 2, 1):
        if len(history_words) < length: continue
        ids = [data.word_to_id.get(w) for w in history_words[-length:]]
        if any(i is None for i in ids): continue
        key_ids = tuple(ids)
        ctxs = [data.histories[length].get((v, shield, key_ids)) for v in variants]
        ctxs = [c for c in ctxs if c]
        if ctxs:
            matched = length
            history_contexts = ctxs
            break

    history_total = data._total(history_contexts)
    history_count = data._choice(history_contexts, word_id)

    # 정확한 보호막 표본이 최소표본 미만이면 화면 표시와 같게 전체 보호막으로 후퇴합니다.
    minimum = data.source.get("exactStateMinimumSample", 2)
    state_ctx = data._contexts(current, shield)
    overall_ctx = data._contexts(current)
    state_total = data._total(state_ctx)
    overall_total = data._total(overall_ctx)
    use_shield = state_total >= minimum
    if use_shield:
        exact_source, exact_ctx, exact_total = "shield", state_ctx, state_total
    elif overall_total > 0:
        exact_source, exact_ctx, exact_total = "overall", overall_ctx, overall_total
    else:
        exact_source, exact_ctx, exact_total = "none", [], 0
    exact_count = data._choice(exact_ctx, word_id)

    destination = data.destinations.get((ending, max(0, shield - 1)))
    if destination:
        destination_score = confidence(destination["total"], 8) * (
            0.75 + 0.25 * min(1.0, math.log1p(destination["unique"]) / math.log(21))
        )
    else:
        destination_score = 0.0

    weights = data.model["weights"]
    minimum_samples = data.model["minimumSamples"]
    numerator = 0.0
    available = 0.0
    if matched:
        w = weights["history%d" % matched]
        prior = minimum_samples["history%d" % matched]
        numerator += w * (history_count / history_total) * confidence(history_total, prior)
        available += w
    if exact_total:
        penalty = 1.0 if exact_source == "shield" else 0.82
        numerator += (weights["exactShieldWord"] * (exact_count / exact_total)
                      * confidence(exact_total, 2 if exact_source == "shield" else 5) * penalty)
        available += weights["exactShieldWord"]
    if destination:
        numerator += weights["destinationState"] * destination_score
        available += weights["destinationState"]
    numerator += weights["structuralRule"] * clamp(structural, 0.0, 1.0)
    available += weights["structuralRule"]

    maximum = (weights["history3"] + weights["exactShieldWord"]
               + weights["destinationState"] + weights["structuralRule"])
    normalized = numerator / available if available else 0.0
    coverage = min(1.0, available / maximum)

    return {
        "score": js_round(normalized * coverage * 1000) / 10,
        "hasEvidence": bool(matched or exact_total or destination),
        "matchedHistoryLength": matched,
        "historyCount": history_count,
        "historyTotal": history_total,
        "exactCount": exact_count,
        "exactTotal": exact_total,
        "exactSource": exact_source,
        "destinationTotal": destination["total"] if destination else 0,
    }


def blend_recent(baseline, recent, days, policy):
    """사이트 blendRecentRouteLearning 과 같습니다."""
    if recent and recent["matchedHistoryLength"]:
        source, total, count = "history", recent["historyTotal"], recent["historyCount"]
    elif recent:
        source, total, count = recent["exactSource"], recent["exactTotal"], recent["exactCount"]
    else:
        source, total, count = "none", 0, 0

    if not recent or total < policy["minimumContextTotal"]:
        return {"days": days, "count": count, "total": total, "source": source,
                "weight": 0.0, "scoreAdjustment": 0.0,
                "combinedScore": baseline["score"],
                "direction": "insufficient" if total > 0 else "none",
                "applied": False}

    weight = policy["maxWeight"] * (total / (total + policy["confidencePrior"]))
    if baseline["hasEvidence"]:
        unbounded = weight * (recent["score"] - baseline["score"])
    else:
        unbounded = weight * recent["score"]
    adjustment = clamp(unbounded, -policy["maxScoreAdjustment"], policy["maxScoreAdjustment"])
    combined = clamp(baseline["score"] + adjustment, 0, 100)
    difference = recent["score"] - baseline["score"]
    direction = "rising" if difference >= 3 else ("falling" if difference <= -3 else "stable")
    return {"days": days, "count": count, "total": total, "source": source,
            "weight": js_round(weight * 10000) / 10000,
            "scoreAdjustment": js_round(adjustment * 10) / 10,
            "combinedScore": js_round(combined * 10) / 10,
            "direction": direction, "applied": True}


# ---------------------------------------------------------------------
# 사람이 확정한 보호막 연구 수순 (사이트 lib/word-data.ts 와 같습니다)
# ---------------------------------------------------------------------
SHIELD_ROUTE_RULES = {
    ("벽", 5): {"words": ["벽바닥"], "avoid": {}},
    ("닥", 4): {"words": ["닥닥"], "avoid": {}},
    ("닥", 3): {"words": ["닥터스톱"], "avoid": {}},
    ("톱", 2): {"words": ["톱스핀"], "avoid": {"톱톱": "톱니무늬1 응수 때문에 전략적으로 불리"}},
    ("핀", 1): {"words": ["핀우그리아어족"], "avoid": {}},
    ("벽", 4): {"words": ["벽탑"], "avoid": {}},
    ("탑", 3): {"words": ["탑승객"], "avoid": {"탑탑": "탑삭나룻2 응수 때문에 전략적으로 불리"}},
    ("객", 2): {"words": ["객관적도덕"], "avoid": {}},
    ("덕", 1): {"words": ["덕업"], "avoid": {}},
}

# 후보와 맞출 때 쓰는 정규화본입니다. 규칙 쪽에 가운뎃점이 남아 있어도 맞습니다.
NORMALIZED_SHIELD_ROUTE_RULES = {
    key: {"words": [strip_dots(w) for w in rule["words"]],
          "avoid": {strip_dots(w): note for w, note in rule["avoid"].items()}}
    for key, rule in SHIELD_ROUTE_RULES.items()
}

RESEARCHED_SHIELD_STATES = {
    ("벽", 5): [("벽바닥", 5), ("닥닥", 4), ("닥터스톱", 3), ("톱스핀", 2), ("핀우그리아어족", 1)],
    ("벽", 4): [("벽탑", 4), ("탑승객", 3), ("객관적도덕", 2), ("덕업", 1)],
}


# ---------------------------------------------------------------------
# 후보 계산
# ---------------------------------------------------------------------
class StandardCore:
    """표준 사전 + 학습 자료 묶음입니다."""

    def __init__(self, first_words, start_count, attacks, one_shots, routes,
                 learning, recent, recent_days, recent_policy):
        self.first_words = first_words      # 첫 음절 -> [단어]
        self.start_count = start_count      # 음절 -> 시작 단어 수
        self.attacks = attacks
        self.one_shots = one_shots
        self.routes = routes                # 음절 -> [주요 루트 단어]
        self.learning = learning
        self.recent = recent
        self.recent_days = recent_days
        self.recent_policy = recent_policy

    def words_for(self, current, used):
        variants = dueum_variants(current)
        out = []
        for v in variants:
            for w in self.first_words.get(v, ()):
                if w not in used: out.append(w)
        return out

    def follow_count(self, ending, used):
        variants = dueum_variants(ending)
        total = sum(self.start_count.get(v, 0) for v in variants)
        blocked = sum(1 for w in used if w and w[0] in variants)
        return max(0, total - blocked)

    def route_rank(self, current, word):
        best = math.inf
        for v in dueum_variants(current):
            row = self.routes.get(v)
            if row and word in row:
                best = min(best, row.index(word))
        return best


def analyze_candidates(core, words, current, shield, used, shield_enabled=True, history=()):
    """사이트 analyzeCandidates 와 같습니다."""
    history_words = [h[0] for h in history]
    master_state = state_evidence(core.learning, current, shield)
    rule = NORMALIZED_SHIELD_ROUTE_RULES.get((current, shield))
    out = []
    for word in words:
        end = word[-1]
        used_after = used | {word}
        follow = core.follow_count(end, used_after)
        main_rank = core.route_rank(current, word)
        plain = strip_dots(word)
        rank = rule["words"].index(plain) if (rule and plain in rule["words"]) else -1
        note = rule["avoid"].get(plain, "") if rule else ""
        attack = word in core.attacks
        one_shot = word in core.one_shots

        if main_rank != math.inf:
            structural = max(0.55, 1 - main_rank * 0.06)
        elif one_shot:
            structural = 0.9
        elif attack:
            structural = 0.7
        else:
            structural = 0.0

        learning = learning_evidence(core.learning, current, shield,
                                     history_words, word, end, structural)
        recent = learning_evidence(core.recent, current, shield,
                                   history_words, word, end, structural)
        trend = blend_recent(learning, recent if core.recent else None,
                             core.recent_days, core.recent_policy)

        word_id = core.learning.word_to_id.get(word) if core.learning else None
        shield_count = master_state["shieldWords"].get(word_id, 0) if word_id is not None else 0
        overall_count = master_state["overallWords"].get(word_id, 0) if word_id is not None else 0
        if master_state["mode"] == "shield" and shield_count > 0:
            priority_source, priority_count, priority_tier = "shield", shield_count, 2
        elif overall_count > 0:
            priority_source, priority_count, priority_tier = "overall", overall_count, 1
        else:
            priority_source, priority_count, priority_tier = "none", 0, 0

        out.append({
            "word": word, "end": end, "followCount": follow,
            "legal": (not shield_enabled) or follow >= shield,
            "shieldRoutePick": rank >= 0,
            "shieldRouteRank": rank if rank >= 0 else math.inf,
            "shieldRouteAvoided": bool(note), "shieldRouteNote": note,
            "attack": attack, "oneShot": one_shot,
            "pickRank": main_rank,
            "masterPriorityTier": priority_tier,
            "masterPriorityCount": priority_count,
            "masterPrioritySource": priority_source,
            "masterOverallCount": overall_count,
            "masterShieldCount": shield_count,
            "learning": learning, "recentTrend": trend,
            "recommendationScore": trend["combinedScore"],
        })
    return out


_INF = float("inf")

def sort_key(c):
    """사이트 sortRecommended 와 같은 순서를 만드는 정렬 키입니다."""
    researched = c["shieldRoutePick"]
    return (
        0 if researched else 1,
        c["shieldRouteRank"] if researched else 0,
        1 if c["shieldRouteAvoided"] else 0,
        -c["recommendationScore"],
        -c["learning"]["matchedHistoryLength"],
        -c["learning"]["historyCount"],
        -c["learning"]["exactCount"],
        -c["masterPriorityTier"],
        -c["masterPriorityCount"],
        -c["masterOverallCount"],
        0 if c["shieldRoutePick"] else 1,
        c["shieldRouteRank"],
        c["pickRank"] if c["pickRank"] != _INF else _INF,
        0 if c["legal"] else 1,
        0 if c["oneShot"] else 1,
        0 if c["attack"] else 1,
        c["followCount"],
        c["word"],
    )


def build_auto_route(core, current, shield, depth=24, used=None, history=None):
    """사이트 buildAutoRoute 와 같습니다. 예상 수순을 만듭니다."""
    used = set(used or ())
    ordered = list(history or ())
    route = []
    for _ in range(depth):
        words = core.words_for(current, used)
        if not words: break
        candidates = [c for c in analyze_candidates(core, words, current, shield, used,
                                                    True, ordered) if c["legal"]]
        if not candidates: break
        best = min(candidates, key=sort_key)
        route.append((best["word"], shield))
        ordered.append((best["word"], shield, current))
        used.add(best["word"])
        current = best["end"]
        shield = max(0, shield - 1)
    return route


def state_sequences(data, current, shield, player_id, length, limit=5, merge_actor=True):
    """사이트 getRouteLearningStateSequences 와 같습니다.
    한 선수의 자료만 읽지만 결과에는 선수 이름을 담지 않습니다.

    merge_actor 가 참이면 M/O 패턴이 달라도 단어 수순이 같으면 한 줄로 합칩니다.
    패턴을 보이지 않을 때 같은 수순이 중복으로 보이지 않게 하려는 것입니다."""
    if not data or not current: return []
    merged = {}
    seen = set()
    for v in dueum_variants(current):
        if v in seen: continue
        seen.add(v)
        for row in data.sequences[length].get((v, shield, player_id), ()):
            _syl, row_shield, _pid, actor, word_ids, count = row
            words = [data.words[i] for i in word_ids]
            key = tuple(words) if merge_actor else (actor, tuple(words))
            prev = merged.get(key)
            merged[key] = {"words": words, "actor": actor, "shield": row_shield,
                           "count": (prev["count"] if prev else 0) + count}
    rows = sorted(merged.values(), key=lambda r: (-r["count"], "".join(r["words"])))
    return rows[:limit]


def load_learning(path):
    with open(path, encoding="utf-8") as fp:
        return RouteLearning(json.load(fp))

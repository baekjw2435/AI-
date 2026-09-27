"""English dictionary lookup; no match history or remote dictionary requests."""
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata


CLASSIC = "영어 끝말잇기"
KKUTU = "영어 끄투"
DEFAULT_PATH = Path(__file__).with_name("english_words.txt")
_LATIN = str.maketrans({"ø": "o", "ł": "l", "ß": "ss", "œ": "oe",
                       "æ": "ae", "ð": "d", "þ": "th"})


def normalize_word(value):
    """Fold a whole headword, never split accented words into fake entries."""
    text = value.strip().lstrip("\ufeff").lower().translate(_LATIN)
    text = "".join(c for c in unicodedata.normalize("NFKD", text)
                   if not unicodedata.combining(c))
    text = text.replace(".", "").replace("-", "").replace("·", "")
    return text if re.fullmatch(r"[a-z]{2,64}", text) else ""


def short_first(word):
    return len(word), word


def long_first(word):
    return -len(word), word


@dataclass(frozen=True)
class AttackGroups:
    kills: tuple
    attacks: tuple
    lures: tuple
    loops: tuple


class EnglishDictionary:
    def __init__(self, words):
        self.words = tuple(sorted({w for raw in words if (w := normalize_word(raw))}))
        heads, tails = defaultdict(list), defaultdict(list)
        for word in self.words:
            for length in range(1, min(3, len(word)) + 1):
                heads[word[:length]].append(word)
                tails[word[-length:]].append(word)
        self.heads = {k: tuple(v) for k, v in heads.items()}
        self.tails = {k: tuple(v) for k, v in tails.items()}
        self._position_status = self._analyze_positions()

    def _analyze_positions(self):
        """Port the original HTML's retrograde analysis and loop parity rule.

        Positions are the whole two-letter ending, or the final three letters
        (which also permit the final two). Count edges by word, not just by
        distinct destination: the HTML uses that multiplicity for loop parity.
        This is a dictionary heuristic; it does not track played words.
        """
        nodes = {word[-3:]: word[-3:] for word in self.words}
        endings = {word: nodes[word[-3:]] for word in self.words}
        destinations, remaining = {}, {}
        reverse = defaultdict(list)
        status, queue = {}, []
        for tail in nodes:
            # Canonical endings plus weighted edges avoid storing the same
            # transition once for each of the many words with that ending.
            edges = Counter(endings[word] for word in self.replies(tail))
            destinations[tail] = edges
            remaining[tail] = sum(edges.values())
            if not edges:
                status[tail] = "LOSS"
                queue.append(tail)
            for target, count in edges.items():
                reverse[target].append((tail, count))

        while queue:
            target = queue.pop()
            for tail, count in reverse.get(target, ()):
                if tail in status:
                    continue
                if status[target] == "LOSS":
                    status[tail] = "WIN"
                    queue.append(tail)
                else:
                    remaining[tail] -= count
                    if remaining[tail] == 0:
                        status[tail] = "LOSS"
                        queue.append(tail)

        changed = True
        while changed:
            changed = False
            for tail in nodes:
                if tail in status:
                    continue
                edges = destinations[tail]
                if any(status.get(target) == "LOSS" for target in edges):
                    status[tail] = "WIN"
                    changed = True
                elif edges and all(status.get(target) == "WIN" for target in edges):
                    status[tail] = "LOSS"
                    changed = True
                elif edges.get(tail, 0):
                    exits = [target for target in edges if target != tail]
                    if exits and all(status.get(target) == "WIN" for target in exits):
                        status[tail] = "WIN" if edges[tail] % 2 else "LOSS"
                        changed = True
        return status

    @classmethod
    def from_file(cls, path=DEFAULT_PATH):
        with Path(path).open(encoding="utf-8-sig") as stream:
            result = cls(stream)
        if not result.words:
            raise ValueError("영어 단어 목록이 비어 있습니다.")
        return result

    def starting(self, prefix):
        prefix = prefix.lower()
        if len(prefix) <= 3:
            return self.heads.get(prefix, ())
        return tuple(w for w in self.heads.get(prefix[:3], ()) if w.startswith(prefix))

    def ending(self, suffix):
        suffix = suffix.lower()
        if len(suffix) <= 3:
            return self.tails.get(suffix, ())
        return tuple(w for w in self.tails.get(suffix[-3:], ()) if w.endswith(suffix))

    @staticmethod
    def continuation_keys(word, mode=KKUTU):
        word = word.lower()
        if len(word) < 2:
            raise ValueError("영어 단어는 2글자 이상이어야 합니다.")
        if mode == CLASSIC:
            return (word[-1],)
        if mode != KKUTU:
            raise ValueError("알 수 없는 영어 연결 규칙입니다.")
        return (word[-2:],) if len(word) == 2 else (word[-3:], word[-2:])

    def replies(self, word, mode=KKUTU):
        # Searcher semantics: all dictionary replies, including the word itself.
        # Repeated words and earlier moves are not tracked by this lookup bot.
        keys = self.continuation_keys(word, mode)
        found = set()
        for key in keys:
            found.update(self.heads.get(key, ()))
        return tuple(sorted(found))

    def reply_count(self, word, mode=KKUTU):
        keys = self.continuation_keys(word, mode)
        if len(keys) == 1:
            return len(self.heads.get(keys[0], ()))
        three, two = keys
        n2 = len(self.heads.get(two, ()))
        # If both prefixes overlap (e.g. aaa / aa), the longer prefix's set
        # is already included in the shorter prefix's set.
        return n2 if three.startswith(two) else n2 + len(self.heads.get(three, ()))

    def loops(self, prefix):
        """Return the searched connection itself: ab...ab / abc...abc."""
        return tuple(sorted((w for w in self.starting(prefix) if w.endswith(prefix.lower())),
                            key=short_first))

    def strategy_tier(self, word):
        """Original HTML tiers; GOOD refers to the next player's LOSS state."""
        word = word.lower()
        if self.reply_count(word) == 0:
            return "KILL"
        return {"LOSS": "GOOD", "WIN": "BAD"}.get(self._position_status.get(word[-3:]), "DRAW")

    def attacks(self, prefix):
        kills, attacks, lures = [], [], []
        for word in self.starting(prefix):
            count = self.reply_count(word)
            if count == 0:
                kills.append(word)
            elif count <= 5:
                lures.append(word)
            elif self.strategy_tier(word) == "GOOD":
                attacks.append(word)
        return AttackGroups(
            kills=tuple(sorted(kills, key=short_first)),
            attacks=tuple(sorted(attacks, key=short_first)),
            lures=tuple(sorted(lures, key=lambda w: (self.reply_count(w), len(w), w))),
            loops=self.loops(prefix),
        )

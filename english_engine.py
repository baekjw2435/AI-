"""English dictionary lookup; no match history or remote dictionary requests."""
from collections import defaultdict
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

    def attacks(self, prefix):
        kills, attacks = [], []
        for word in self.starting(prefix):
            count = self.reply_count(word)
            if count == 0:
                kills.append(word)
            elif count <= 5:
                attacks.append(word)
        return AttackGroups(
            tuple(sorted(kills, key=short_first)),
            tuple(sorted(attacks, key=lambda w: (self.reply_count(w), len(w), w))),
            self.loops(prefix),
        )

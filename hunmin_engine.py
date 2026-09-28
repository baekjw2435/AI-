"""Ordered initial-consonant runs: A+B+, including A=A (length >= 2)."""
from collections import defaultdict
from pathlib import Path
import unicodedata


INITIALS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
STANDARD = "표준"
COMPLEX = "복합"
WORD_FILES = {STANDARD: "standard_words.txt", COMPLEX: "words.txt"}


def initial_pair(word):
    """Return the only A+B+ pair for an all-Hangul word, or None."""
    if len(word) < 2:
        return None
    first = second = None
    for syllable in word:
        offset = ord(syllable) - 0xAC00
        if not 0 <= offset <= 11171:
            return None
        initial = offset // 588
        if first is None:
            first = initial
        elif second is None:
            if initial != first:
                second = initial
        elif initial != second:
            # Once B starts, neither A nor a third consonant may appear.
            return None
    return INITIALS[first] + INITIALS[first if second is None else second]


def normalize_pair(pair):
    # Accept both keyboard compatibility jamo and modern leading jamo.
    normalized = "".join(
        INITIALS[ord(char) - 0x1100] if 0x1100 <= ord(char) <= 0x1112 else char
        for char in pair
    )
    if len(normalized) != 2 or any(char not in INITIALS for char in normalized):
        raise ValueError("초성 두 글자를 붙여 입력해 주세요. 예: `!ㅎㅅ`, `!ㅇㅇ`, `!ㅈㅈ`")
    return normalized


class HunminDictionary:
    def __init__(self, words):
        groups = defaultdict(set)
        self.source_rows = 0
        for raw in words:
            word = unicodedata.normalize("NFC", raw.strip().lstrip("\ufeff"))
            if not word:
                continue
            self.source_rows += 1
            pair = initial_pair(word)
            if pair is not None:
                groups[pair].add(word)
        self.groups = {
            pair: tuple(sorted(entries, key=lambda word: (-len(word), word)))
            for pair, entries in groups.items()
        }
        self.word_count = sum(map(len, self.groups.values()))

    @classmethod
    def from_file(cls, path):
        with Path(path).open(encoding="utf-8-sig") as stream:
            return cls(stream)

    def search(self, pair):
        return self.groups.get(normalize_pair(pair), ())

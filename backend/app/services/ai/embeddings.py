"""Text similarity. The local backend is a hashed bag of words and character trigrams with cosine
similarity: deterministic, private (nothing leaves the server) and good enough for ranking."""

import hashlib
import math
import re
from collections import Counter

DIM = 2048
_WORD = re.compile(r"[a-zа-яё0-9+#.]{2,}", re.IGNORECASE)

# Frequent Russian/English words that carry no signal for matching.
STOPWORDS = frozenset(
    """и в во на с со по для от до из к ко о об а но или не что как это мы вы вас нас наш ваш
    будет быть есть который которые также the and for with to of in on a an is are be you we our your
    работа работы работу компании компания команда команды опыт требования обязанности условия""".split()
)


def tokens(text: str) -> list[str]:
    return [t.lower().strip(".") for t in _WORD.findall(text or "") if t.lower() not in STOPWORDS]


def _bucket(feature: str) -> int:
    return int.from_bytes(hashlib.blake2b(feature.encode(), digest_size=4).digest(), "big") % DIM


def embed(text: str) -> dict[int, float]:
    counts: Counter[int] = Counter()
    for tok in tokens(text):
        counts[_bucket("w:" + tok)] += 2
        padded = f" {tok} "
        for i in range(len(padded) - 2):
            counts[_bucket("c:" + padded[i : i + 3])] += 1
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {k: v / norm for k, v in counts.items()}


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def similarity(text_a: str, text_b: str) -> float:
    if not text_a.strip() or not text_b.strip():
        return 0.0
    return max(0.0, min(1.0, cosine(embed(text_a), embed(text_b))))

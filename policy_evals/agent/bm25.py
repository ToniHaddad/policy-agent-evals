"""A small Okapi BM25 index, plus the tokenizer the reference agent uses."""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

STOPWORDS = set(
    """a an and are as at be before by can do does for from have how i if in
    into is it its may me my need of on or our so than that the their them then
    there this to under up was we what when where which who will with you your
    any all also after much many""".split()
)

ARABIC_INDIC = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
TOKEN = re.compile(r"[a-z0-9]+|[؀-ۿ]+")
SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "ed", "es", "s", "e", "al")


def fold(text: str) -> str:
    """Lowercase, strip accents, map Arabic-Indic digits to ASCII."""
    text = unicodedata.normalize("NFKD", text.translate(ARABIC_INDIC))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def stem(token: str) -> str:
    if not token.isascii() or len(token) <= 4:
        return token
    for suf in SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 4:
            return token[: -len(suf)]
    return token


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in TOKEN.findall(fold(text)) if t not in STOPWORDS]


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [tokenize(d) for d in docs]
        self.tf = [Counter(d) for d in self.docs]
        self.avgdl = sum(len(d) for d in self.docs) / max(len(self.docs), 1)
        df: Counter = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        q = tokenize(query)
        out = []
        for tf, doc in zip(self.tf, self.docs):
            s = 0.0
            for t in q:
                f = tf.get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * len(doc) / self.avgdl)
                s += self.idf[t] * f * (self.k1 + 1) / denom
            out.append(s)
        return out

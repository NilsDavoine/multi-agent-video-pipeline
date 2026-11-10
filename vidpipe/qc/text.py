"""Word normalisation, word error rate and script-to-transcript alignment."""
from __future__ import annotations

import difflib
import re

_UNITS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
          "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


def number_words(n: int) -> list[str]:
    if n < 20:
        return [_UNITS[n]]
    if n < 100:
        return [_TENS[n // 10]] + ([_UNITS[n % 10]] if n % 10 else [])
    if n < 1000:
        return [_UNITS[n // 100], "hundred"] + (number_words(n % 100) if n % 100 else [])
    return [str(n)]


def normalize(text: str) -> list[str]:
    """Lower case, no punctuation, digits spelled out ("2" -> "two", "4.5" -> "four point five")."""
    text = text.lower().replace("’", "'").replace("-", " ")
    out: list[str] = []
    for tok in re.findall(r"[a-z']+|\d+(?:\.\d+)?", text):
        if tok[0].isdigit():
            whole, _, frac = tok.partition(".")
            out += number_words(int(whole))
            if frac:
                out += ["point"] + [_UNITS[int(d)] for d in frac]
        else:
            tok = tok.strip("'")
            if tok:
                out.append(tok)
    return out


def wer(reference: list[str], hypothesis: list[str]) -> float:
    """Word error rate = (substitutions + deletions + insertions) / reference length."""
    if not reference:
        return 0.0 if not hypothesis else 1.0
    prev = list(range(len(hypothesis) + 1))
    for i, r in enumerate(reference, 1):
        cur = [i] + [0] * len(hypothesis)
        for j, h in enumerate(hypothesis, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(reference)


def align(reference: list[str], hypothesis: list[str]) -> list[int | None]:
    """For each reference word, the index of the matching hypothesis word (or None)."""
    sm = difflib.SequenceMatcher(a=reference, b=hypothesis, autojunk=False)
    match: list[int | None] = [None] * len(reference)
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            match[a + k] = b + k
    return match

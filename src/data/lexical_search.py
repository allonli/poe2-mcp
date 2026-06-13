"""
BM25 lexical retrieval over the canonical stat-description corpus
(issue #177, amended design — NO embedding model).

Why lexical, not vector: this MCP's architecture is MCP=data layer,
caller=intelligence layer. The consuming LLM is already the semantic
engine; embedding a model into the data layer duplicates it and breaks
the boundary. The observed failures that motivated #177 ("wither" vs
"Withered", "chaos damage" buried in Poison's body) were MORPHOLOGICAL,
not semantic — a stemmed BM25 ranker solves exactly that class with
zero new dependencies and no inference at query time.

Index is built lazily in-process from data/game/stat_descriptions/ on
first query and cached for the process (~10k short docs; build is well
under a second). Token tables stay in memory — no extraction-pipeline
coupling, no on-disk artifact to keep in sync.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Conservative suffix stripper — handles the inflection that defeats
# substring search (wither/withered/withering, slow/slows/slowed,
# ignite/ignited/igniting) without the over-stemming a full Porter
# implementation risks on game jargon. Order matters: longest first.
_SUFFIXES = ("ingly", "edly", "ing", "ed", "es", "s", "ly")


def stem(token: str) -> str:
    """Light suffix-stripping stem. Leaves short tokens untouched.

    The bare '-s' plural is the trap: it would turn 'chaos' -> 'chao'.
    Only strip '-s' when the preceding char isn't 's'/'u' and the result
    stays >=4 chars — so chaos/status survive but slows->slow works."""
    for suf in _SUFFIXES:
        if not token.endswith(suf):
            continue
        base = token[: -len(suf)]
        if len(base) < 3:
            continue
        if suf == "s":
            # Strip plural -s only after a consonant (hits->hit, slows->slow);
            # vowel-before-s words are not plurals (chaos, status, bonus).
            if len(base) < 3 or token[-2] in "aeious":
                continue
        return base
    return token


def tokenize(text: str) -> List[str]:
    """Lowercase, split on non-alphanumeric, stem. Game-text markup like
    ``[Withered|Wither]`` tokenizes cleanly to withered/wither -> wither."""
    return [stem(t) for t in _TOKEN_RE.findall(text.lower())]


class BM25Index:
    """In-memory BM25 ranker. k1/b are the standard defaults."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: List[Dict[str, Any]] = []        # {id, text, meta}
        self._doc_tokens: List[List[str]] = []
        self._doc_len: List[int] = []
        self._avg_len: float = 0.0
        self._df: Dict[str, int] = {}
        self._postings: Dict[str, Dict[int, int]] = {}  # term -> {doc_idx: tf}
        self._built = False

    def add(self, doc_id: str, text: str, meta: Optional[Dict[str, Any]] = None):
        idx = len(self._docs)
        toks = tokenize(text)
        self._docs.append({"id": doc_id, "text": text, "meta": meta or {}})
        self._doc_tokens.append(toks)
        self._doc_len.append(len(toks))
        seen = set()
        tf: Dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        for t, c in tf.items():
            self._postings.setdefault(t, {})[idx] = c
            if t not in seen:
                self._df[t] = self._df.get(t, 0) + 1
                seen.add(t)

    def finalize(self):
        n = len(self._doc_len)
        self._avg_len = (sum(self._doc_len) / n) if n else 0.0
        self._built = True

    def search(self, query: str, k: int = 8) -> List[Tuple[float, Dict[str, Any]]]:
        if not self._built:
            self.finalize()
        q_terms = tokenize(query)
        if not q_terms or not self._docs:
            return []
        N = len(self._docs)
        scores: Dict[int, float] = {}
        for term in set(q_terms):
            postings = self._postings.get(term)
            if not postings:
                continue
            df = self._df.get(term, 1)
            idf = math.log(1 + (N - df + 0.5) / (df + 0.5))
            for doc_idx, tf in postings.items():
                dl = self._doc_len[doc_idx]
                denom = tf + self.k1 * (1 - self.b + self.b * dl / (self._avg_len or 1))
                scores[doc_idx] = scores.get(doc_idx, 0.0) + idf * (tf * (self.k1 + 1)) / (denom or 1)
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:k]
        return [(score, self._docs[i]) for i, score in ranked]


_INDEX: Optional[BM25Index] = None


def _default_corpus_path() -> Path:
    return (Path(__file__).parent.parent.parent
            / "data" / "game" / "stat_descriptions" / "stat_descriptions.json")


def build_stat_description_index(path: Optional[Path] = None) -> BM25Index:
    """Build a BM25 index over the canonical stat descriptions. Each doc
    is one stat description; text = primary template + stat ids (so a
    query matches both human wording and the stat_id tokens)."""
    path = path or _default_corpus_path()
    idx = BM25Index()
    if not path.exists():
        idx.finalize()
        return idx
    data = json.loads(path.read_text(encoding="utf-8"))
    for e in (data.get("descriptions") or []):
        sid = e.get("primary_stat_id")
        if not sid:
            continue
        template = e.get("primary_template") or ""
        stat_ids = " ".join((e.get("stat_ids") or [sid]))
        # stat_ids are underscore_joined; turn them into word tokens too
        id_words = stat_ids.replace("_", " ").replace("+", " ").replace("%", " ")
        text = f"{template} {id_words}"
        idx.add(sid, text, meta={
            "stat_id": sid,
            "template": template,
            "source_csd": e.get("source_csd"),
        })
    idx.finalize()
    return idx


def get_stat_description_index() -> BM25Index:
    """Process-wide singleton (lazy build)."""
    global _INDEX
    if _INDEX is None:
        _INDEX = build_stat_description_index()
    return _INDEX


def search_stat_descriptions_ranked(query: str, k: int = 8) -> List[Dict[str, Any]]:
    """Public helper: BM25-ranked stat descriptions for a query.
    Returns [{stat_id, template, source_csd, score}] best-first."""
    hits = get_stat_description_index().search(query, k=k)
    return [
        {**h["meta"], "score": round(score, 3)}
        for score, h in hits
    ]

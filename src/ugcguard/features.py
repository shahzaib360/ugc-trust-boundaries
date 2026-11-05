"""Features for the page-section classifier.

The classifier decides, for a candidate block (div/li/article/...), whether it
holds user-generated content. It must work on sites with *no* UGC markup, so
markup attributes (itemtype, itemprop, typeof, property, rel, role=comment and
microformat classes) are never used as features: they are the labels.

Three feature groups:

* **structure** - tag, depth, size, link density, counts of images/buttons/
  form controls/<time>, how many same-shaped siblings the block has (reviews,
  comments and posts are repeated items), relative position on the page;
* **text** - first/second person pronouns, dates and "3 days ago", review/forum
  vocabulary ("helpful", "reply", "verified purchase"), prices, digits;
* **naming** - curated cue tokens from the block's and its ancestors' class/id
  (e.g. ``review``, ``comment``, ``reply``, ``author``). Optional, so the model can
  be evaluated against sites with hashed/obfuscated class names.
"""

from __future__ import annotations

import math
import re

from .dom import BLOCK_TAGS, Doc

MIN_TEXT, MAX_TEXT = 20, 12000

CUE_TOKENS = (
    "review",
    "comment",
    "reply",
    "replies",
    "post",
    "message",
    "thread",
    "answer",
    "question",
    "user",
    "author",
    "avatar",
    "rating",
    "star",
    "feedback",
    "testimonial",
    "discussion",
    "forum",
    "community",
    "member",
    "profile",
    "vote",
    "helpful",
    "opinion",
    "quote",
    "response",
    "chat",
    "topic",
    "byline",
    "username",
)
NEG_TOKENS = (
    "nav",
    "menu",
    "header",
    "footer",
    "product",
    "price",
    "cart",
    "card",
    "tile",
    "promo",
    "banner",
    "ad",
    "breadcrumb",
    "related",
    "recommend",
    "article",
    "story",
    "hero",
    "search",
    "filter",
    "result",
    "listing",
    "offer",
    "sidebar",
)
_TOKEN_SPLIT = re.compile(r"[^a-zA-Z]+|(?<=[a-z])(?=[A-Z])")
_MICROFORMAT = re.compile(r"^(h|p|u|e|dt)-")

_FIRST = re.compile(r"\b(i|i'm|i've|i'd|me|my|mine|myself|we|our|us)\b", re.I)
_SECOND = re.compile(r"\b(you|your|you're|yours)\b", re.I)
_AGO = re.compile(
    r"\b\d+\s*(?:sec|second|min|minute|hr|hour|day|week|wk|month|mo|year|yr)s?\s+ago\b"
    r"|\b(?:yesterday|just now|an? (?:hour|day|week|month|year) ago)\b",
    re.I,
)
_DATE = re.compile(
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}\b"
    r"|\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{4}\b"
    r"|\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b|\b20\d{2}-\d{2}-\d{2}\b",
    re.I,
)
_UGC_WORDS = re.compile(
    r"\b(?:review(?:ed|s|er)?|verified (?:purchase|buyer|owner)|helpful|report(?: abuse)?|"
    r"repl(?:y|ies|ied)|posted|wrote|says?|said|upvotes?|likes?|members?|joined|"
    r"out of 5|stars?|recommends?|permalink|flag|quote|edited|thread|comments?|"
    r"originally posted|thanks?|lol|imo|imho)\b",
    re.I,
)
_PRICE = re.compile(r"(?:[$€£¥₹]\s?\d|\d\s?(?:usd|eur|gbp)\b)", re.I)
_SENT = re.compile(r"[.!?]+(?:\s|$)")
_WORD = re.compile(r"[A-Za-z']+")
_EXCL = re.compile(r"!")
_EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")
_STARS = re.compile("[★☆⭐]")
# "Dana K. · Oct 14, 2026", "Rosa M. 3 days ago": a short name followed by a date.
_NAME_DATE = re.compile(
    r"^\s*(?:[A-Z][\w.'-]*\s?){1,3}[^\w]{0,4}\s*(?:on\s+)?"
    r"(?i:(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d|"
    r"\d{1,2}[/.-]\d|\d+\s*\w+\s+ago|yesterday|today)"
)
# Forum-style handles at the start of a block: "packetpusher ·", "@sam wrote".
_HANDLE = re.compile(r"^\s*@?[a-z][a-z0-9_.-]{2,24}\s*(?:[^\w\s]|\s+(?:wrote|said|posted|replied))")

TAGS = ("div", "li", "article", "section", "p", "td", "tr", "ul", "ol", "form", "blockquote")

STRUCT_FEATURES = [
    *(f"tag_{t}" for t in TAGS),
    "tag_other",
    "log_text",
    "log_desc",
    "rel_depth",
    "rel_pos",
    "link_density",
    "log_links",
    "img_per_100c",
    "buttons",
    "inputs",
    "forms",
    "times",
    "headings",
    "paragraphs",
    "list_items",
    "svgs",
    "n_children",
    "sibling_repeat",
    "sibling_repeat_log",
    "parent_repeat_frac",
    "in_nav",
    "in_header",
    "in_footer",
    "in_aside",
    "in_main_or_article",
    "text_share",
]
TEXT_FEATURES = [
    "first_person",
    "second_person",
    "ago",
    "dates",
    "ugc_words",
    "prices",
    "digit_frac",
    "upper_frac",
    "excl",
    "question",
    "emoji",
    "n_sent_log",
    "avg_sent_len",
    "avg_word_len",
    "ttr",
    "star_glyphs",
    "name_then_date",
    "handle_start",
]
NAME_FEATURES = [
    *(f"cue_{t}" for t in CUE_TOKENS),
    *(f"neg_{t}" for t in NEG_TOKENS),
    "cue_any_self",
    "cue_any_anc",
    "neg_any_self",
]
ALL_FEATURES = STRUCT_FEATURES + TEXT_FEATURES + NAME_FEATURES


def name_tokens(doc: Doc, i: int) -> set[str]:
    el = doc.nodes[i]
    raw = " ".join(x for x in (el.get("class"), el.get("id")) if x)
    out = set()
    for tok in raw.split():
        if _MICROFORMAT.match(tok):
            continue  # microformat classes are labels, not features
        for part in _TOKEN_SPLIT.split(tok):
            if len(part) >= 2:
                out.add(part.lower())
    return out


def _has_token(tokens: set[str], cue: str) -> bool:
    # Short cues must match exactly ("ad" must not fire on "address", "star" on "start").
    if len(cue) < 5:
        return cue in tokens or (cue + "s") in tokens
    return any(t.startswith(cue) for t in tokens)


def signature_key(doc: Doc, i: int) -> tuple:
    """Shape of a node, used to find repeated siblings (review lists etc.)."""
    el = doc.nodes[i]
    cls = tuple(sorted(re.sub(r"\d+", "", c) for c in (el.get("class") or "").split()))
    return (doc.tag[i], cls)


def _is_candidate(doc: Doc, i: int) -> bool:
    return (
        doc.tag[i] in BLOCK_TAGS and not doc.skipped[i] and MIN_TEXT <= doc.text_len[i] <= MAX_TEXT
    )


def candidates(doc: Doc) -> list[int]:
    """Block elements worth classifying.

    Wrapper chains (div > div > div with the same text) are collapsed to their
    outermost element, which keeps the candidate count manageable on large pages.
    """
    out = []
    for i in range(len(doc)):
        if not _is_candidate(doc, i):
            continue
        p = doc.parent[i]
        if p >= 0 and _is_candidate(doc, p) and doc.text_len[p] <= 1.05 * doc.text_len[i]:
            continue
        out.append(i)
    return out


class FeatureExtractor:
    """Computes feature vectors for candidate blocks of one document."""

    def __init__(self, doc: Doc):
        self.doc = doc
        n = len(doc)
        self._sib_repeat = [1] * n
        self._parent_repeat_frac = [0.0] * n
        for p in range(n):
            kids = doc.children[p]
            if len(kids) < 2:
                continue
            counts: dict[tuple, int] = {}
            keys = []
            for k in kids:
                key = signature_key(doc, k)
                keys.append(key)
                counts[key] = counts.get(key, 0) + 1
            top = max(counts.values())
            for k, key in zip(kids, keys, strict=True):
                self._sib_repeat[k] = counts[key]
                self._parent_repeat_frac[k] = top / len(kids)
        self._ctx = [0] * n  # bitmask: 1 nav, 2 header, 4 footer, 8 aside, 16 main/article
        bits = {"nav": 1, "header": 2, "footer": 4, "aside": 8, "main": 16, "article": 16}
        for i in range(n):
            p = doc.parent[i]
            m = self._ctx[p] if p >= 0 else 0
            role = (doc.nodes[i].get("role") or "").lower()
            m |= bits.get(doc.tag[i], 0)
            if role == "navigation":
                m |= 1
            elif role == "banner":
                m |= 2
            elif role == "contentinfo":
                m |= 4
            self._ctx[i] = m
        self._tok_cache: dict[int, set[str]] = {}
        self.page_text = max(doc.page_text_len, 1)
        self.max_depth = max(max(doc.depth, default=1), 1)

    def _tokens(self, i: int) -> set[str]:
        if i not in self._tok_cache:
            self._tok_cache[i] = name_tokens(self.doc, i)
        return self._tok_cache[i]

    def features(self, i: int, use_names: bool = True) -> list[float]:
        d = self.doc
        tl = max(d.text_len[i], 1)
        text = d.text(i, limit=1500)
        words = _WORD.findall(text)
        nw = max(len(words), 1)
        sents = max(len(_SENT.findall(text)), 1)
        tag = d.tag[i]
        f: list[float] = [1.0 if tag == t else 0.0 for t in TAGS]
        f.append(0.0 if tag in TAGS else 1.0)
        ctx = self._ctx[i]
        f += [
            math.log1p(tl),
            math.log1p(d.n_desc[i]),
            d.depth[i] / self.max_depth,
            i / max(len(d), 1),
            d.link_text_len[i] / tl,
            math.log1p(d.n_links[i]),
            100.0 * d.n_img[i] / tl,
            min(d.n_button[i], 20),
            min(d.n_input[i], 20),
            min(d.n_form[i], 5),
            min(d.n_time[i], 10),
            min(d.n_heading[i], 10),
            min(d.n_p[i], 30),
            min(d.n_li[i], 50),
            min(d.n_svg[i], 20),
            min(len(d.children[i]), 50),
            float(self._sib_repeat[i] >= 3),
            math.log1p(self._sib_repeat[i]),
            self._parent_repeat_frac[i],
            float(bool(ctx & 1)),
            float(bool(ctx & 2)),
            float(bool(ctx & 4)),
            float(bool(ctx & 8)),
            float(bool(ctx & 16)),
            tl / self.page_text,
        ]
        letters = sum(c.isalpha() for c in text) or 1
        f += [
            len(_FIRST.findall(text)) / nw,
            len(_SECOND.findall(text)) / nw,
            min(len(_AGO.findall(text)), 10),
            min(len(_DATE.findall(text)), 10),
            len(_UGC_WORDS.findall(text)) / nw,
            min(len(_PRICE.findall(text)), 20),
            sum(c.isdigit() for c in text) / max(len(text), 1),
            sum(c.isupper() for c in text) / letters,
            min(len(_EXCL.findall(text)), 20),
            min(text.count("?"), 20),
            float(bool(_EMOJI.search(text))),
            math.log1p(sents),
            nw / sents,
            sum(len(w) for w in words) / nw,
            len({w.lower() for w in words}) / nw,
            min(len(_STARS.findall(text)), 10),
            float(bool(_NAME_DATE.match(text))),
            float(bool(_HANDLE.match(text))),
        ]
        if use_names:
            own = self._tokens(i)
            anc: set[str] = set()
            p, hops = d.parent[i], 0
            while p >= 0 and hops < 3:
                anc |= self._tokens(p)
                p, hops = d.parent[p], hops + 1
            both = own | anc
            f += [float(_has_token(both, c)) for c in CUE_TOKENS]
            f += [float(_has_token(own, c)) for c in NEG_TOKENS]
            f += [
                float(any(_has_token(own, c) for c in CUE_TOKENS)),
                float(any(_has_token(anc, c) for c in CUE_TOKENS)),
                float(any(_has_token(own, c) for c in NEG_TOKENS)),
            ]
        else:
            f += [0.0] * len(NAME_FEATURES)
        return f

"""Detect user-generated regions from markup that sites already publish for SEO.

Sources, all standard and already deployed on the web:

* schema.org **microdata** (``itemscope itemtype=".../Review"``, ``itemprop="review"``)
* schema.org **RDFa** (``typeof="schema:Comment"``, ``property="reviewBody"``)
* schema.org **JSON-LD** (``<script type="application/ld+json">``). JSON-LD does not point
  at DOM nodes, so the review/comment text it carries is *anchored* back onto the page by
  text matching.
* ``rel="ugc"`` on links (Google, 2019) - marks author-controlled links only.
* WAI-ARIA 1.3 ``role="comment"``
* microformats ``h-review`` / ``hreview`` / ``p-comment``

Editorial types are deliberately *not* UGC: ``CriticReview``, ``ClaimReview`` and
``MediaReview`` are written by the publisher, and ``Question``/``Answer`` inside an
``FAQPage`` are the site's own FAQ.
"""

from __future__ import annotations

import json
import re

from .dom import Doc, normalize_ws
from .regions import Region

UGC_TYPES = {
    "review": "review",
    "userreview": "review",
    "employerreview": "review",
    "comment": "comment",
    "usercomments": "comment",
    "answer": "answer",
    "question": "question",
    "discussionforumposting": "post",
    "socialmediaposting": "post",
}
EDITORIAL_TYPES = {"criticreview", "claimreview", "mediareview", "faqpage"}
# itemprop/property names that point at a UGC item even when the type is missing.
UGC_PROPS = {
    "review": "review",
    "reviews": "review",
    "comment": "comment",
    "comments": "comment",
    "suggestedanswer": "answer",
    "acceptedanswer": "answer",
}
# Author-controlled fields inside a UGC item.
BODY_PROPS = {"reviewbody", "text", "commenttext", "description", "headline", "name"}
MICROFORMAT_CLASSES = {
    "h-review": ("review", "item"),
    "hreview": ("review", "item"),
    "p-comment": ("comment", "item"),
    "u-comment": ("comment", "item"),
}


def _type_names(value: str | None) -> list[str]:
    """'https://schema.org/Review schema:Comment' -> ['review', 'comment']."""
    if not value:
        return []
    out = []
    for tok in value.split():
        tok = tok.rstrip("/")
        tok = re.split(r"[/#:]", tok)[-1]
        if tok:
            out.append(tok.lower())
    return out


def _prop_names(value: str | None) -> list[str]:
    if not value:
        return []
    return [re.split(r"[/#:]", t.rstrip("/"))[-1].lower() for t in value.split() if t]


def _inside_faq(doc: Doc, i: int, attr: str) -> bool:
    return any("faqpage" in _type_names(doc.nodes[a].get(attr)) for a in doc.ancestors(i))


def _body_regions(doc: Doc, item: int, scope_attr: str, prop_attr: str, source: str, kind: str):
    """Author-controlled fields of a microdata/RDFa item (nearest scope == item)."""
    out = []
    for j in doc.subtree(item):
        if j == item:
            continue
        props = _prop_names(doc.nodes[j].get(prop_attr))
        if not props or not (set(props) & BODY_PROPS):
            continue
        # Nearest enclosing item must be this UGC item (skip itemReviewed/author names).
        nearest = None
        for a in doc.ancestors(j):
            if doc.nodes[a].get(scope_attr) is not None:
                nearest = a
                break
        if nearest == item and doc.nodes[j].get(scope_attr) is None:
            out.append(Region(j, source, "body", kind))
    return out


def microdata_regions(doc: Doc) -> list[Region]:
    out: list[Region] = []
    for i, el in enumerate(doc.nodes):
        if el.get("itemscope") is None and el.get("itemtype") is None:
            continue
        types = _type_names(el.get("itemtype"))
        props = _prop_names(el.get("itemprop"))
        kind = next((UGC_TYPES[t] for t in types if t in UGC_TYPES), None)
        if kind is None and not (set(types) & EDITORIAL_TYPES):
            kind = next((UGC_PROPS[p] for p in props if p in UGC_PROPS), None)
        if kind is None:
            continue
        if kind in ("question", "answer") and _inside_faq(doc, i, "itemtype"):
            continue
        out.append(Region(i, "microdata", "item", kind))
        out.extend(_body_regions(doc, i, "itemscope", "itemprop", "microdata", kind))
    return out


def rdfa_regions(doc: Doc) -> list[Region]:
    out: list[Region] = []
    for i, el in enumerate(doc.nodes):
        typeof = el.get("typeof")
        if typeof is None:
            continue
        prop = el.get("property") or el.get("rel")
        types = _type_names(typeof)
        kind = next((UGC_TYPES[t] for t in types if t in UGC_TYPES), None)
        if kind is None and not (set(types) & EDITORIAL_TYPES):
            kind = next((UGC_PROPS[p] for p in _prop_names(prop) if p in UGC_PROPS), None)
        if kind is None:
            continue
        if kind in ("question", "answer") and _inside_faq(doc, i, "typeof"):
            continue
        out.append(Region(i, "rdfa", "item", kind))
        out.extend(_body_regions(doc, i, "typeof", "property", "rdfa", kind))
    return out


# --------------------------------------------------------------------- JSON-LD
def _walk_jsonld(obj, in_faq: bool = False):
    """Yield (ugc_kind, text) for every UGC object in a JSON-LD payload."""
    if isinstance(obj, list):
        for x in obj:
            yield from _walk_jsonld(x, in_faq)
        return
    if not isinstance(obj, dict):
        return
    raw_type = obj.get("@type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    names = [t.split("/")[-1].split(":")[-1].lower() for t in types if isinstance(t, str)]
    faq_here = in_faq or "faqpage" in names
    kind = next((UGC_TYPES[t] for t in names if t in UGC_TYPES), None)
    if kind and not (kind in ("question", "answer") and faq_here):
        for key in ("reviewBody", "text", "commentText", "description"):
            val = obj.get(key)
            if isinstance(val, str) and len(val.strip()) >= 25:
                yield kind, val
                break
        else:
            yield kind, ""
    for k, v in obj.items():
        if k != "@context" and isinstance(v, (dict, list)):
            yield from _walk_jsonld(v, faq_here)


def jsonld_objects(doc: Doc) -> list[tuple[str, str]]:
    found = []
    for el in doc.nodes:
        if el.tag != "script":
            continue
        if "ld+json" not in (el.get("type") or "").lower():
            continue
        raw = (el.text or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            # Some sites concatenate objects or leave trailing commas; try a lenient fix.
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except (json.JSONDecodeError, ValueError):
                continue
        found.extend(_walk_jsonld(data))
    return found


_PUNCT = re.compile(r"[^\w]+", re.UNICODE)


def _norm(text: str) -> str:
    return _PUNCT.sub(" ", text.lower()).strip()


def anchor_text(doc: Doc, text: str, min_probe: int = 24, cache: dict | None = None) -> int | None:
    """Find the smallest element whose visible text contains ``text``'s opening.

    Used to map JSON-LD review/comment bodies back to the DOM.
    """
    norm = _norm(normalize_ws(text))
    if len(norm) < min_probe:
        return None
    probe = norm[:60]
    lo = int(len(probe) * 0.8)
    hi = len(text) * 3 + 600
    cache = {} if cache is None else cache
    best = None
    for i in range(len(doc)):
        tl = doc.text_len[i]
        if tl < lo or tl > hi or doc.skipped[i]:
            continue
        if best is not None and tl > doc.text_len[best]:  # ties: deeper node wins
            continue
        t = cache.get(i)
        if t is None:
            t = cache[i] = _norm(doc.text(i, limit=hi + 200))
        if probe in t:
            best = i
    return best


def jsonld_regions(doc: Doc) -> tuple[list[Region], int]:
    """Anchored JSON-LD regions, plus the count of UGC objects found at all."""
    objs = jsonld_objects(doc)
    out: list[Region] = []
    seen: set[int] = set()
    cache: dict = {}
    for kind, text in objs:
        if not text:
            continue
        node = anchor_text(doc, text, cache=cache)
        if node is not None and node not in seen:
            seen.add(node)
            out.append(Region(node, "json-ld", "body", kind))
    return out, len(objs)


# ----------------------------------------------------------------- rel, aria, mf
def rel_ugc_regions(doc: Doc) -> list[Region]:
    out = []
    for i, el in enumerate(doc.nodes):
        if doc.tag[i] not in ("a", "area", "link"):
            continue
        rel = (el.get("rel") or "").lower().split()
        if "ugc" in rel and doc.tag[i] != "link":
            out.append(Region(i, "rel-ugc", "link", "link"))
    return out


def aria_regions(doc: Doc) -> list[Region]:
    return [
        Region(i, "aria", "item", "comment")
        for i, el in enumerate(doc.nodes)
        if (el.get("role") or "").strip().lower() == "comment"
    ]


def microformat_regions(doc: Doc) -> list[Region]:
    out = []
    for i, el in enumerate(doc.nodes):
        cls = el.get("class")
        if not cls:
            continue
        for c in cls.split():
            hit = MICROFORMAT_CLASSES.get(c.lower())
            if hit:
                out.append(Region(i, "microformats", hit[1], hit[0]))
                break
    return out


def markup_regions(doc: Doc) -> tuple[list[Region], dict]:
    """All standard-markup regions plus page-level counters."""
    regions: list[Region] = []
    regions += microdata_regions(doc)
    regions += rdfa_regions(doc)
    jl, n_jsonld = jsonld_regions(doc)
    regions += jl
    regions += rel_ugc_regions(doc)
    regions += aria_regions(doc)
    regions += microformat_regions(doc)
    stats = {"jsonld_ugc_objects": n_jsonld, "jsonld_anchored": len(jl)}
    return regions, stats

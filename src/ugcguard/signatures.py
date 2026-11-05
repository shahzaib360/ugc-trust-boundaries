"""Signatures of widely deployed review/comment/forum software.

These are not standards. They are the class names, ids and attributes that common
UGC platforms render (comment systems, review vendors, forum engines, CMS
defaults). They catch UGC on sites that never added schema.org markup, and they
give the classifier an *independent* check: a model trained only on
markup-labelled sites can be scored against signature-labelled ones.

Rules are intentionally specific (vendor-prefixed tokens, exact ids). Generic
words such as "comment" or "review" are left to the classifier.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .dom import Doc
from .regions import Region


@dataclass(frozen=True)
class Rule:
    vendor: str
    scope: str  # item | body
    ugc_type: str
    tag: str | None = None  # restrict to tag name
    cls: str | None = None  # exact class token
    id: str | None = None  # exact id
    attr: tuple[str, str | None] | None = None  # (name, value) - value None = present
    also_cls: str | None = None  # second class token that must also be present


RULES: tuple[Rule, ...] = (
    # Comment systems
    Rule("disqus", "item", "comment", id="disqus_thread"),
    Rule("facebook-comments", "item", "comment", cls="fb-comments"),
    Rule("coral", "item", "comment", id="coral_thread"),
    Rule("coral", "item", "comment", cls="coral-comment"),
    Rule("openweb", "item", "comment", attr=("data-spotim-module", None)),
    Rule("viafoura", "item", "comment", cls="viafoura"),
    Rule("commento", "item", "comment", id="commento"),
    Rule("utterances", "item", "comment", cls="utterances"),
    Rule("giscus", "item", "comment", cls="giscus"),
    # WordPress core comment markup
    Rule("wordpress", "item", "comment", tag="li", cls="comment", also_cls="depth-1"),
    Rule("wordpress", "item", "comment", tag="ol", cls="comment-list"),
    Rule("wordpress", "item", "comment", tag="ol", cls="commentlist"),
    Rule("comment-content", "body", "comment", cls="comment-content"),
    # Review vendors
    Rule("bazaarvoice", "item", "review", cls="bv-content-item"),
    Rule("bazaarvoice", "body", "review", cls="bv-content-summary-body-text"),
    Rule("bazaarvoice", "item", "review", id="BVRRContainer"),
    Rule("bazaarvoice", "item", "review", attr=("data-bv-show", "reviews")),
    Rule("bazaarvoice", "item", "question", attr=("data-bv-show", "questions")),
    Rule("powerreviews", "item", "review", cls="pr-review"),
    Rule("powerreviews", "body", "review", cls="pr-rd-description-text"),
    Rule("powerreviews", "item", "review", id="pr-reviewdisplay"),
    Rule("yotpo", "item", "review", cls="yotpo-review"),
    Rule("yotpo", "item", "review", cls="yotpo-reviews"),
    Rule("judgeme", "item", "review", cls="jdgm-rev"),
    Rule("judgeme", "body", "review", cls="jdgm-rev__body"),
    Rule("stamped", "item", "review", cls="stamped-review"),
    Rule("trustpilot", "item", "review", cls="trustpilot-widget"),
    Rule("reviews-io", "item", "review", cls="ReviewsIoWidget"),
    Rule("turnto", "item", "review", id="tt-reviews-list"),
    # Marketplaces and social platforms
    Rule("amazon", "item", "review", attr=("data-hook", "review")),
    Rule("amazon", "body", "review", attr=("data-hook", "review-body")),
    Rule("amazon", "body", "review", attr=("data-hook", "review-title")),
    Rule("amazon", "item", "review", id="cm-cr-dp-review-list"),
    Rule("tripadvisor", "item", "review", attr=("data-automation", "reviewCard")),
    Rule("booking", "item", "review", cls="c-review-block"),
    Rule("booking", "item", "review", attr=("data-testid", "review-card")),
    Rule("etsy", "item", "review", attr=("data-review-region", None)),
    Rule("youtube", "item", "comment", tag="ytd-comment-renderer"),
    Rule("youtube", "item", "comment", tag="ytd-comment-thread-renderer"),
    Rule("reddit", "item", "comment", tag="shreddit-comment"),
    Rule("reddit", "item", "post", tag="shreddit-post"),
    Rule("reddit", "body", "comment", cls="usertext-body"),
    Rule("x", "body", "post", attr=("data-testid", "tweetText")),
    # Forum and Q&A engines
    Rule("discourse", "item", "post", cls="topic-post"),
    Rule("discourse", "body", "post", cls="cooked"),
    Rule("xenforo", "item", "post", cls="message--post"),
    Rule("xenforo", "body", "post", cls="bbWrapper"),
    Rule("vbulletin", "body", "post", cls="postcontent"),
    Rule("phpbb", "body", "post", cls="postbody"),
    Rule("stackexchange", "body", "post", cls="js-post-body"),
    Rule("stackexchange", "body", "comment", cls="comment-copy"),
    Rule("comment-body", "body", "comment", cls="comment-body"),
)

# Class/id tokens that literally say "user-generated content".
_UGC_TOKEN = re.compile(r"(?:^|[^a-z])ugc(?:$|[^a-z])", re.I)


def _match(doc: Doc, i: int, rule: Rule, classes: set[str]) -> bool:
    el = doc.nodes[i]
    if rule.tag and doc.tag[i] != rule.tag:
        return False
    if rule.cls and rule.cls not in classes:
        return False
    if rule.also_cls and rule.also_cls not in classes:
        return False
    if rule.id and el.get("id") != rule.id:
        return False
    if rule.attr:
        name, value = rule.attr
        got = el.get(name)
        if got is None or (value is not None and got != value):
            return False
    return True


# Index rules by their cheapest discriminating key so a page scan stays linear.
_BY_CLS: dict[str, list[Rule]] = {}
_BY_ID: dict[str, list[Rule]] = {}
_BY_TAG: dict[str, list[Rule]] = {}
_BY_ATTR: dict[str, list[Rule]] = {}
for _r in RULES:
    if _r.cls:
        _BY_CLS.setdefault(_r.cls, []).append(_r)
    elif _r.id:
        _BY_ID.setdefault(_r.id, []).append(_r)
    elif _r.attr:
        _BY_ATTR.setdefault(_r.attr[0], []).append(_r)
    elif _r.tag:
        _BY_TAG.setdefault(_r.tag, []).append(_r)


def signature_regions(doc: Doc, include_ugc_token: bool = True) -> list[Region]:
    out: list[Region] = []
    for i, el in enumerate(doc.nodes):
        if doc.skipped[i] and doc.tag[i] not in ("div", "section"):
            continue
        cls_attr = el.get("class") or ""
        classes = set(cls_attr.split())
        cands: list[Rule] = []
        for c in classes:
            cands.extend(_BY_CLS.get(c, ()))
        eid = el.get("id")
        if eid:
            cands.extend(_BY_ID.get(eid, ()))
        cands.extend(_BY_TAG.get(doc.tag[i], ()))
        if _BY_ATTR:
            for name in el.attrib:
                if name in _BY_ATTR:
                    cands.extend(_BY_ATTR[name])
        hit = next((r for r in cands if _match(doc, i, r, classes)), None)
        if hit:
            out.append(Region(i, f"signature:{hit.vendor}", hit.scope, hit.ugc_type))
            continue
        token = _UGC_TOKEN.search(cls_attr) or _UGC_TOKEN.search(eid or "")
        if include_ugc_token and token and doc.text_len[i] >= 20:
            out.append(Region(i, "signature:ugc-token", "item", "unknown"))
    return out

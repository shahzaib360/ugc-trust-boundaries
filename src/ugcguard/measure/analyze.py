"""Run the detectors over one page and summarize what an agent would face there."""

from __future__ import annotations

import random

import numpy as np

from ..classifier import SectionClassifier, label_candidates
from ..dom import Doc
from ..features import ALL_FEATURES, FeatureExtractor, candidates
from ..markup import markup_regions
from ..regions import RegionMap
from ..signatures import signature_regions


def _target_node(doc: Doc, target: str | None, attr: str) -> int | None:
    if not target:
        return None
    for i, el in enumerate(doc.nodes):
        if el.get(attr) == target:
            return i
    return None


def analyze_page(
    html: str,
    url: str | None,
    events: list[dict] | None = None,
    target_attr: str = "data-webtasks-id",
    classifier: SectionClassifier | None = None,
    examples: bool = False,
    max_neg: int = 40,
    max_pos: int = 150,
    seed: int = 0,
) -> dict:
    """Page-level record (+ optional training examples for the classifier)."""
    doc = Doc.from_html(html, url)
    mk, mk_stats = markup_regions(doc)
    sig = signature_regions(doc)
    rm_markup = RegionMap(doc, mk)
    rm_sig = RegionMap(doc, sig)
    rm_rules = RegionMap(doc, mk + sig)
    rec: dict = {
        "url": url,
        "html_bytes": len(html),
        "n_nodes": len(doc),
        "text_len": doc.page_text_len,
        "markup_sources": sorted(rm_markup.sources()),
        "markup_item_body": sum(1 for r in mk if r.scope in ("item", "body")),
        "rel_ugc_links": sum(1 for r in mk if r.source == "rel-ugc"),
        "jsonld_ugc_objects": mk_stats["jsonld_ugc_objects"],
        "jsonld_anchored": mk_stats["jsonld_anchored"],
        "signature_vendors": sorted({r.source.split(":", 1)[1] for r in sig}),
        "ugc_types": sorted({r.ugc_type for r in mk + sig if r.ugc_type not in ("link",)}),
        "ugc_text_markup": rm_markup.ugc_text_len(),
        "ugc_text_rules": rm_rules.ugc_text_len(),
    }
    rm_clf = None
    if classifier is not None:
        clf_regions = classifier.regions(doc)
        rm_clf = RegionMap(doc, clf_regions)
        rm_all = RegionMap(doc, mk + sig + [r for r in clf_regions if not rm_rules.is_ugc(r.node)])
        rec["clf_regions"] = len(clf_regions)
        rec["clf_max_conf"] = max((r.confidence for r in clf_regions), default=0.0)
        rec["ugc_text_clf"] = rm_clf.ugc_text_len()
        rec["ugc_text_all"] = rm_all.ugc_text_len()
    # Where did the recorded actions land?
    acts = []
    for ev in events or []:
        t = _target_node(doc, ev.get("target"), target_attr)
        a = {"intent": ev.get("intent"), "found": t is not None}
        if t is not None:
            reg = rm_rules.region_of(t)
            a["in_rules"] = reg is not None
            a["in_markup"] = rm_markup.is_ugc(t)
            a["rules_source"] = reg.source if reg else None
            a["tag"] = doc.tag[t]
            if rm_clf is not None:
                a["in_clf"] = rm_clf.is_ugc(t)
        acts.append(a)
    rec["actions"] = acts
    if not examples:
        return rec

    # Training examples: markup labels (training) and signature labels (independent check).
    cands = candidates(doc)
    y_mk = label_candidates(doc, rm_markup, cands)
    y_sig = label_candidates(doc, rm_sig, cands)
    rng = random.Random(seed)
    pos = [k for k, (a, b) in enumerate(zip(y_mk, y_sig, strict=True)) if a == 1 or b == 1]
    neg = [k for k, (a, b) in enumerate(zip(y_mk, y_sig, strict=True)) if a == 0 and b == 0]
    rng.shuffle(pos)
    rng.shuffle(neg)
    keep = sorted(pos[:max_pos] + neg[:max_neg])
    fx = FeatureExtractor(doc)
    X = np.array([fx.features(cands[k]) for k in keep], dtype=np.float32)
    if X.size == 0:
        X = np.zeros((0, len(ALL_FEATURES)), dtype=np.float32)

    def enc(v):
        return -1 if v is None else v

    rec["_X"] = X
    rec["_y_markup"] = np.array([enc(y_mk[k]) for k in keep], dtype=np.int8)
    rec["_y_sig"] = np.array([enc(y_sig[k]) for k in keep], dtype=np.int8)
    rec["_n_cands"] = len(cands)
    return rec

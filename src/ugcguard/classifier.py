"""Page-section classifier for sites without UGC markup.

Training labels come for free from sites that *do* publish markup (distant
supervision): a candidate block is positive when it lies inside a markup region,
negative when it has no overlap with any region, and ignored when it only
partly contains one. The markup attributes themselves are excluded from the
features (see :mod:`ugcguard.features`), so the model has to learn what UGC
looks like rather than what its markup looks like.
"""

from __future__ import annotations

import pickle
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .dom import Doc
from .features import ALL_FEATURES, FeatureExtractor, candidates, signature_key
from .regions import Region, RegionMap

MODEL_PATH = Path(__file__).parent / "models" / "section_classifier.pkl"


def label_candidates(doc: Doc, regions: RegionMap, cands: list[int]) -> list[int | None]:
    """1 = inside UGC, 0 = no overlap, None = mixed (contains some UGC)."""
    ugc = regions.ugc_nodes()
    roots = regions.roots()
    labels: list[int | None] = []
    for i in cands:
        if i in ugc:
            labels.append(1)
            continue
        covered = 0
        for r in roots:
            if doc.is_descendant(r, i):
                covered += doc.text_len[r]
        if covered == 0:
            labels.append(0)
        elif covered >= 0.8 * doc.text_len[i]:
            labels.append(1)
        else:
            labels.append(None)
    return labels


def page_examples(doc: Doc, regions: RegionMap | None, use_names: bool = True):
    """Feature matrix, labels and candidate ids for one page."""
    cands = candidates(doc)
    fx = FeatureExtractor(doc)
    X = np.array([fx.features(i, use_names=use_names) for i in cands], dtype=np.float32)
    if X.size == 0:
        X = np.zeros((0, len(ALL_FEATURES)), dtype=np.float32)
    y = label_candidates(doc, regions, cands) if regions is not None else [None] * len(cands)
    return X, y, cands


@dataclass
class SectionClassifier:
    model: object
    use_names: bool = True
    threshold: float = 0.5
    meta: dict = field(default_factory=dict)

    # --------------------------------------------------------------- training
    @classmethod
    def train(
        cls,
        X: np.ndarray,
        y: np.ndarray,
        use_names: bool = True,
        threshold: float = 0.5,
        seed: int = 0,
        groups: np.ndarray | None = None,
        **meta,
    ) -> SectionClassifier:
        """Fit a gradient-boosted tree model.

        With ``groups`` (the website of each block), every website gets the same
        total weight, so a few large, heavily-labelled sites cannot dominate.
        """
        from sklearn.ensemble import HistGradientBoostingClassifier

        if not use_names:
            X = mask_names(X)
        # Strong leaf-size regularization + per-site weights: chosen because it transferred
        # best to websites whose UGC no markup labels (see scripts/train_classifier.py).
        model = HistGradientBoostingClassifier(
            max_iter=150,
            learning_rate=0.08,
            max_leaf_nodes=31,
            min_samples_leaf=200,
            l2_regularization=1.0,
            class_weight="balanced",
            random_state=seed,
        )
        weights = site_weights(groups) if groups is not None else None
        model.fit(X, y, sample_weight=weights)
        return cls(model=model, use_names=use_names, threshold=threshold, meta=meta)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if len(X) == 0:
            return np.zeros(0)
        if not self.use_names:
            X = mask_names(X)
        return self.model.predict_proba(X)[:, 1]

    # -------------------------------------------------------------- inference
    def regions(self, doc: Doc, smooth: bool = True) -> list[Region]:
        X, _, cands = page_examples(doc, None, use_names=self.use_names)
        if not cands:
            return []
        p = self.predict_proba(X)
        if smooth:
            p = smooth_siblings(doc, cands, p)
        return select_regions(doc, cands, p, self.threshold)

    # ------------------------------------------------------------ persistence
    def save(self, path: Path | str = MODEL_PATH) -> None:
        import sklearn

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model": self.model,
            "use_names": self.use_names,
            "threshold": self.threshold,
            "meta": {**self.meta, "sklearn": sklearn.__version__},
            "features": ALL_FEATURES,
        }
        with open(path, "wb") as fh:
            pickle.dump(payload, fh)

    @classmethod
    def load(cls, path: Path | str = MODEL_PATH) -> SectionClassifier:
        with open(path, "rb") as fh:
            payload = pickle.load(fh)  # noqa: S301 - our own artifact
        if payload.get("features") != ALL_FEATURES:
            raise ValueError("feature set changed since this model was trained; retrain it")
        return cls(
            model=payload["model"],
            use_names=payload["use_names"],
            threshold=payload["threshold"],
            meta=payload.get("meta", {}),
        )


def site_weights(groups: np.ndarray) -> np.ndarray:
    """Weight each sample by 1 / (#samples of its site), normalized to mean 1."""
    _, inv, counts = np.unique(groups, return_inverse=True, return_counts=True)
    w = 1.0 / counts[inv]
    return w * (len(w) / w.sum())


_NAME_START = ALL_FEATURES.index("cue_" + "review")


def mask_names(X: np.ndarray) -> np.ndarray:
    """Zero the class/id cue features (content + structure only)."""
    X = np.array(X, dtype=np.float32, copy=True)
    X[:, _NAME_START:] = 0.0
    return X


def smooth_siblings(doc: Doc, cands: list[int], p: np.ndarray, weight: float = 0.5) -> np.ndarray:
    """Blend each score with the mean of its same-shaped siblings.

    Reviews and comments come in lists; one terse item ("Great!") should
    inherit evidence from the items next to it.
    """
    groups: dict[tuple, list[int]] = {}
    for k, i in enumerate(cands):
        groups.setdefault((doc.parent[i], signature_key(doc, i)), []).append(k)
    out = p.copy()
    for ks in groups.values():
        if len(ks) >= 3:
            m = float(np.mean(p[ks]))
            for k in ks:
                out[k] = (1 - weight) * p[k] + weight * m
    return out


def select_regions(
    doc: Doc, cands: list[int], p: np.ndarray, threshold: float, max_share: float = 0.6
) -> list[Region]:
    """Turn per-block scores into non-overlapping region roots."""
    page = max(doc.page_text_len, 1)
    chosen = {
        i: float(s)
        for i, s in zip(cands, p, strict=True)
        if s >= threshold and doc.text_len[i] / page <= max_share
    }
    out = []
    for i, s in chosen.items():
        if any(a in chosen for a in doc.ancestors(i)):
            continue
        out.append(Region(i, "classifier", "item", "unknown", confidence=s))
    return out


_cached: SectionClassifier | None = None


def default_classifier() -> SectionClassifier | None:
    """The bundled model, or None if it has not been trained yet."""
    global _cached
    if _cached is None and MODEL_PATH.exists():
        _cached = SectionClassifier.load(MODEL_PATH)
    return _cached

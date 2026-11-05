"""One entry point for finding user-generated regions on a page."""

from __future__ import annotations

from .classifier import SectionClassifier, default_classifier
from .dom import Doc
from .markup import markup_regions
from .regions import RegionMap
from .signatures import signature_regions

ALL_SOURCES = ("markup", "signature", "classifier")


def detect(
    doc: Doc,
    sources: tuple[str, ...] = ALL_SOURCES,
    classifier: SectionClassifier | None = None,
) -> RegionMap:
    """Return a :class:`RegionMap` built from the requested evidence sources.

    ``sources`` is any subset of ``("markup", "signature", "classifier", "oracle")``.
    ``oracle`` reads the benchmark's ground-truth attribute and exists only for
    measuring the other detectors against an upper bound.
    """
    rm = RegionMap(doc)
    if "markup" in sources:
        regions, _ = markup_regions(doc)
        rm.extend(regions)
    if "signature" in sources:
        rm.extend(signature_regions(doc))
    if "classifier" in sources:
        clf = classifier or default_classifier()
        if clf is not None:
            covered = rm.ugc_nodes()
            # The classifier only fills gaps that markup/signatures left open.
            rm.extend(r for r in clf.regions(doc) if r.node not in covered)
    if "oracle" in sources:
        from .regions import Region

        for i, el in enumerate(doc.nodes):
            if el.get("data-bench-ugc") is not None:
                rm.add(Region(i, "oracle", el.get("data-bench-ugc") or "item", "unknown"))
    return rm

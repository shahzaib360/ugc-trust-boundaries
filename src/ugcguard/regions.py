"""Region model: which parts of a page were written by someone other than the site.

A :class:`Region` is a subtree of the page (identified by its root node index)
that holds user-generated content (UGC). Regions come from different *sources*
(standard markup, vendor widget signatures, the learned classifier, or the
benchmark's ground truth) and have a *scope*:

* ``item``  - a whole review/comment/post container, including site-rendered
  controls such as "Helpful" or "Reply" buttons;
* ``body``  - only the author-controlled part (review text, post body);
* ``link``  - a single author-controlled link (``rel="ugc"``).

:class:`RegionMap` answers the question the enforcement layer needs answered:
*is this node author-controlled, and according to whom?*
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .dom import Doc

SCOPES = ("item", "body", "link")


@dataclass(frozen=True)
class Region:
    node: int
    source: str  # e.g. "microdata", "json-ld", "rel-ugc", "signature:disqus", "classifier"
    scope: str = "item"  # "item" | "body" | "link"
    ugc_type: str = "unknown"  # review | comment | answer | question | post | link | unknown
    confidence: float = 1.0

    @property
    def family(self) -> str:
        """Coarse source family: markup, signature, classifier or oracle."""
        if self.source.startswith("signature:"):
            return "signature"
        if self.source in ("classifier", "oracle"):
            return self.source
        return "markup"


MARKUP_SOURCES = frozenset({"microdata", "rdfa", "json-ld", "rel-ugc", "aria", "microformats"})


@dataclass
class RegionMap:
    """Regions of one document plus fast node -> region lookup."""

    doc: Doc
    regions: list[Region] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._owner: dict[int, Region] | None = None

    def add(self, region: Region) -> None:
        self.regions.append(region)
        self._owner = None

    def extend(self, regions) -> None:
        for r in regions:
            self.regions.append(r)
        self._owner = None

    def _index(self) -> dict[int, Region]:
        """Map every node inside a region to the innermost covering region."""
        if self._owner is not None:
            return self._owner
        owner: dict[int, Region] = {}
        # Outer regions first so inner (more specific) ones overwrite them.
        order = sorted(self.regions, key=lambda r: self.doc.depth[r.node])
        for r in order:
            for j in self.doc.subtree(r.node):
                owner[j] = r
        self._owner = owner
        return owner

    def region_of(self, node: int) -> Region | None:
        return self._index().get(node)

    def is_ugc(self, node: int) -> bool:
        return node in self._index()

    def ugc_nodes(self) -> set[int]:
        return set(self._index())

    def sources(self) -> set[str]:
        return {r.source for r in self.regions}

    def families(self) -> set[str]:
        return {r.family for r in self.regions}

    def filter(self, keep) -> RegionMap:
        return RegionMap(self.doc, [r for r in self.regions if keep(r)])

    def roots(self) -> list[int]:
        """Region roots that are not inside another region."""
        nodes = {r.node for r in self.regions}
        out = []
        for n in nodes:
            if not any(a in nodes for a in self.doc.ancestors(n)):
                out.append(n)
        return sorted(out)

    def ugc_text_len(self) -> int:
        return sum(self.doc.text_len[n] for n in self.roots())

    def summary(self) -> dict:
        by_source: dict[str, int] = {}
        for r in self.regions:
            by_source[r.source] = by_source.get(r.source, 0) + 1
        return {
            "n_regions": len(self.regions),
            "by_source": by_source,
            "ugc_text_len": self.ugc_text_len(),
        }

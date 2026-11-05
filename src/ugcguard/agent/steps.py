"""A tiny plan language shared by the scripted planners.

Benign tasks carry a gold plan; attacks carry the plan their payload asks for.
Each step resolves against the current observation the way a model would: by
visible label, link target or nearby text - never by ground-truth ids.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .observe import Element, Observation, sentences


@dataclass(frozen=True)
class Click:
    label: str | None = None  # regex on the element label
    href: str | None = None  # substring of the link target
    near: str | None = None  # text inside the same review/post as the element
    kind: str | None = None  # link | button


@dataclass(frozen=True)
class Fill:
    label: str  # regex on the field label / name
    value: str  # may use {email} {phone} {address} {name}


@dataclass(frozen=True)
class Goto:
    url: str


@dataclass(frozen=True)
class Answer:
    keywords: tuple[str, ...]  # quote sentences that mention any of these
    extra: str = ""  # text appended verbatim (used by answer-manipulation attacks)


Step = Click | Fill | Goto | Answer


def _container(obs: Observation, el: Element) -> int | None:
    reg = el.region
    if reg is not None:
        roots = obs.regions.roots()
        for r in roots:
            if r == reg.node or obs.doc.is_descendant(reg.node, r):
                return r
    return None


def find(obs: Observation, step: Click | Fill) -> Element | None:
    els = obs.elements
    if isinstance(step, Fill):
        rx = re.compile(step.label, re.I)
        for el in els:
            if el.kind in ("input", "textarea", "select") and (
                rx.search(el.label or "") or rx.search(el.name or "")
            ):
                return el
        return None
    cands = []
    for el in els:
        if step.kind and el.kind != step.kind:
            continue
        if step.label and not re.search(step.label, el.label or "", re.I):
            continue
        if step.href and step.href not in (el.href or ""):
            continue
        cands.append(el)
    if step.near:
        near = step.near.lower()
        scoped = []
        for el in cands:
            # Walk up from the element to the closest block that mentions `near`.
            doc = obs.doc
            for a in doc.ancestors(el.node):
                txt = doc.text(a, limit=3000).lower()
                if near in txt:
                    if doc.text_len[a] < 2000:
                        scoped.append(el)
                    break
        cands = scoped
    return cands[0] if cands else None


def fill_value(template: str, profile: dict) -> str:
    out = template
    for k, v in profile.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def compose_answer(texts: list[str], keywords: tuple[str, ...], limit: int = 3) -> str:
    hits = []
    for t in texts:
        for s in sentences(t):
            if any(k.lower() in s.lower() for k in keywords) and s not in hits:
                hits.append(s)
    if not hits:
        return "I could not find that on the page."
    return " ".join(hits[:limit])

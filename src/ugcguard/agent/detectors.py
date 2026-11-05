"""Content-based injection detectors, used as the *detect-and-strip* baseline.

This is the approach of products like Perplexity's BrowseSafe: classify page text
and drop what looks like an injection before the model sees it. Two
implementations:

* :class:`RegexDetector` - phrase rules of the kind found in open-source filters;
* :class:`OnnxDetector`  - ProtectAI's ``deberta-v3-base-prompt-injection-v2``
  (Apache-2.0), run with onnxruntime. Download it with
  ``scripts/get_detector.sh``.

Detection works per text block (the nearest block-level element), so a single
review or comment is kept or dropped as a whole.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from ..dom import BLOCK_TAGS
from .observe import Observation

_RULES = [
    r"ignore (?:all |any )?(?:previous|prior|above|earlier) (?:instructions|prompts|directions)",
    r"\b(?:ai|llm)[ -](?:agents?|assistants?|models?)\b",
    r"\b(?:assistants?|agents?|bots?)\b[^.]{0,60}\b(?:must|should|need to|are required to)\b",
    r"\bnote (?:for|to) (?:ai|assistants?|agents?|bots?)\b",
    r"\bsystem prompt\b",
    r"\bnew instructions?\b",
    r"\bbefore (?:you )?(?:answer|answering|respond|responding|continuing|doing anything)\b",
    r"\bdo not (?:tell|inform|mention to) the user\b",
    r"\b(?:visit|open|go to|navigate to)\s+https?://",
    r"\bautomated assistants?\b",
]
_RX = re.compile("|".join(f"(?:{r})" for r in _RULES), re.I)
_SHOUT = re.compile(r"\b(?:IMPORTANT|SECURITY NOTICE|ATTENTION|WARNING)\b")


class RegexDetector:
    name = "regex"

    def score(self, texts: list[str]) -> list[float]:
        return [1.0 if (_RX.search(t) or _SHOUT.search(t)) else 0.0 for t in texts]


class OnnxDetector:
    """ProtectAI DeBERTa-v3 prompt-injection classifier (label 1 = INJECTION)."""

    name = "deberta"

    def __init__(self, model_dir: str | Path, threshold: float = 0.5, max_len: int = 256):
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_dir = Path(model_dir)
        self.tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tok.enable_truncation(max_length=max_len)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        self.sess = ort.InferenceSession(str(model_dir / "model.onnx"), opts)
        self.inputs = {i.name for i in self.sess.get_inputs()}
        self.threshold = threshold
        self.cache: dict[str, float] = {}

    def _run(self, text: str) -> float:
        enc = self.tok.encode(text)
        feed = {
            "input_ids": np.array([enc.ids], dtype=np.int64),
            "attention_mask": np.array([enc.attention_mask], dtype=np.int64),
        }
        if "token_type_ids" in self.inputs:
            feed["token_type_ids"] = np.array([enc.type_ids], dtype=np.int64)
        logits = self.sess.run(None, feed)[0][0]
        e = np.exp(logits - logits.max())
        return float(e[1] / e.sum())

    def score(self, texts: list[str]) -> list[float]:
        out = []
        for t in texts:
            if t not in self.cache:
                self.cache[t] = self._run(t)
            out.append(self.cache[t])
        return out


def strip_flagged(obs: Observation, detector, threshold: float = 0.5) -> list[str]:
    """Hide every text block the detector flags. Returns the flagged texts."""
    doc = obs.doc
    blocks: dict[int, str] = {}
    for i in range(len(doc)):
        if doc.skipped[i] or not doc.own_text[i]:
            continue
        b = i
        while b >= 0 and doc.tag[b] not in BLOCK_TAGS:
            b = doc.parent[b]
        if b < 0:
            b = i
        if b not in blocks:
            blocks[b] = doc.text(b, limit=1500)
    ids = list(blocks)
    scores = detector.score([blocks[b] for b in ids])
    flagged = [b for b, s in zip(ids, scores, strict=True) if s >= threshold]
    hidden: set[int] = set()
    for b in flagged:
        hidden.update(doc.subtree(b))
    for j in hidden:
        doc.skipped[j] = True
    obs.elements = [el for el in obs.elements if el.node not in hidden]
    obs.segments = [s for s in obs.segments if s.node not in hidden]
    return [blocks[b] for b in flagged]

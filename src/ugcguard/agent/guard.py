"""The enforcement layer: user content may inform an answer, never trigger an action.

The guard sits between the planner (an LLM, or a scripted stand-in) and the
browser. It sees every proposed action together with the trust zones of the
current page, and returns ``allow``, ``confirm`` (ask the user) or ``block``.
It never looks at *why* the planner proposed an action - that is exactly what
an injection corrupts - only at where the action's target and arguments come
from.

Rules
-----
R1 ugc-link        Following a link that sits inside user content -> confirm.
R2 ugc-url         Navigating to a URL (or host) that only user content mentioned -> confirm.
R3 ugc-form        Typing into a field inside user content -> block; pressing a button
                   there (could be a site control such as "Helpful") -> confirm.
R4 ugc-value       Typing a value that only user content contained -> confirm.
R5 pii             Typing the user's personal data when the task did not ask to share it
                   -> confirm; sending it to another site in a URL -> block.
R6 out-of-scope    A consequential first-party action (buy, delete, post, change settings,
                   subscribe, book, vote) the task did not ask for -> confirm.
R7 unexpected-nav  A cross-origin navigation the guard did not pre-authorize
                   (e.g. triggered by page script) -> block. Enforced at the network layer.
R8 answer-link     URLs that only user content supplied are labelled as such in the answer.
OS origin-set      (optional) Cross-origin navigation outside the task's origin set -> block.
                   This models Chrome's Agent Origin Sets; it is the baseline we compare to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urldefrag, urlsplit

from ..dom import origin_of
from .observe import Element, Observation

ALLOW, CONFIRM, BLOCK = "allow", "confirm", "block"


@dataclass
class Action:
    kind: str  # click | type | goto | answer | read_ugc | back | stop
    element: str | None = None  # data-ug id
    text: str | None = None  # typed value or answer
    url: str | None = None
    # Bookkeeping for evaluation only; the guard never reads it.
    source: str = "plan"
    note: str = ""


@dataclass
class Decision:
    verdict: str
    rule: str = ""
    reason: str = ""
    answer: str | None = None  # rewritten answer (R8)
    expect_nav: set[str] = field(default_factory=set)  # pre-authorized navigation targets

    @property
    def allowed(self) -> bool:
        return self.verdict == ALLOW


@dataclass
class GuardConfig:
    ugc_rules: bool = True  # R1-R8
    origin_set: bool = False  # Agent-Origin-Set style gating (baseline / add-on)
    network: bool = True  # R7


PII_KEYS = ("email", "phone", "address", "name")

# Consequential action categories: words on the control / in the form action,
# and the task words that authorize them.
INTENTS = {
    "purchase": (
        r"place order|buy now|purchase|pay\b|checkout|/order",
        r"\b(buy|order|purchase|checkout|check out)\b",
    ),
    "cart": (r"add to cart|/cart/add", r"\b(buy|order|purchase|add .* to (my )?cart|cart)\b"),
    "delete": (
        r"delete|remove account|close account|/delete",
        r"\b(delete|remove|close) (my )?(account|profile)\b",
    ),
    "settings": (
        r"save changes|update (email|address|profile)|/settings",
        r"\b(change|update|edit|set) (my )?(email|address|phone|settings|profile|password)\b",
    ),
    "post": (
        r"post reply|post comment|submit review|publish|/reply|/comment|/review$",
        r"\b(reply|post|comment|write|leave|publish)\b",
    ),
    "subscribe": (
        r"subscribe|sign up|newsletter",
        r"\b(subscribe|sign me up|sign up|newsletter)\b",
    ),
    "book": (r"book now|reserve|/book", r"\b(book|reserve|reservation)\b"),
    "vote": (r"helpful|like\b|upvote|/like|/helpful", r"\b(helpful|like|upvote|vote)\b"),
}
PII_TASK_WORDS = {
    "email": r"\bmy (e-?mail|details|information|info|contact)\b|\bsign me up\b",
    "phone": r"\bmy (phone|number|details|information|info|contact)\b",
    "address": r"\bmy (saved )?(address|details|information|info)\b|\bship\b",
    "name": r"\bmy (name|details|information|info)\b|\bbook\b|\bbuy\b|\border\b",
}

_URL = re.compile(r"https?://[^\s\"'<>)]+", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_HOST = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:test|com|net|org|io|co|info|biz|xyz|app|dev)\b", re.I)


def norm_url(url: str) -> str:
    url = urldefrag(url.strip())[0]
    s = urlsplit(url)
    path = s.path.rstrip("/") or "/"
    q = f"?{s.query}" if s.query else ""
    return f"{s.scheme.lower()}://{(s.netloc or '').lower()}{path}{q}"


def _norm_text(t: str) -> str:
    return re.sub(r"\s+", " ", t.lower()).strip()


@dataclass
class TaskScope:
    instruction: str
    start_url: str
    origins: set[str] = field(default_factory=set)  # origin set (for the OS baseline)
    pii: dict = field(default_factory=dict)
    pii_ok: set[str] = field(default_factory=set)
    intents: set[str] = field(default_factory=set)

    @classmethod
    def infer(cls, instruction: str, start_url: str, pii: dict, extra_origins=()) -> TaskScope:
        low = instruction.lower()
        intents = {k for k, (_, task_rx) in INTENTS.items() if re.search(task_rx, low)}
        pii_ok = {k for k, rx in PII_TASK_WORDS.items() if re.search(rx, low)}
        if "book" in intents or "purchase" in intents:
            pii_ok |= {"name"}
        origins = {origin_of(start_url)} | {origin_of(u) for u in _URL.findall(instruction)}
        origins |= {o for o in extra_origins if o}
        return cls(instruction, start_url, origins, dict(pii), pii_ok, intents)


class Guard:
    """Stateful per-episode guard. Call :meth:`observe` on every new page."""

    def __init__(self, scope: TaskScope, config: GuardConfig | None = None):
        self.scope = scope
        self.cfg = config or GuardConfig()
        self.ugc_text: list[str] = []
        self.trusted_text: list[str] = [scope.instruction]
        self.ugc_hrefs: set[str] = set()
        self.trusted_hrefs: set[str] = {norm_url(u) for u in _URL.findall(scope.instruction)}
        self.log: list[dict] = []
        self.expect_nav: set[str] = set()

    # ---------------------------------------------------------------- state
    def observe(self, obs: Observation) -> None:
        self.ugc_text.extend(_norm_text(t) for t in obs.ugc_text())
        self.trusted_text.extend(_norm_text(t) for t in obs.first_party_text())
        self.ugc_hrefs |= {norm_url(h) for h in obs.ugc_hrefs()}
        self.trusted_hrefs |= {norm_url(h) for h in obs.first_party_hrefs()}
        self.trusted_hrefs.add(norm_url(obs.url))
        self._ugc_blob = None
        self._trusted_blob = None

    @property
    def ugc_blob(self) -> str:
        if getattr(self, "_ugc_blob", None) is None:
            self._ugc_blob = "\n".join(self.ugc_text)
        return self._ugc_blob

    @property
    def trusted_blob(self) -> str:
        if getattr(self, "_trusted_blob", None) is None:
            self._trusted_blob = "\n".join(self.trusted_text)
        return self._trusted_blob

    # ---------------------------------------------------------------- taint
    def url_tainted(self, url: str) -> bool:
        """Did this destination come from user content (and nowhere trusted)?"""
        u = norm_url(url)
        if u in self.trusted_hrefs:
            return False
        host = (urlsplit(u).hostname or "").lower()
        trusted_hosts = {(urlsplit(h).hostname or "") for h in self.trusted_hrefs}
        if u in self.ugc_hrefs:
            return True
        bare = u.split("://", 1)[-1]
        if bare and bare in self.ugc_blob:
            return True
        if host and host not in trusted_hosts:
            ugc_hosts = {(urlsplit(h).hostname or "") for h in self.ugc_hrefs}
            if host in ugc_hosts or re.search(rf"\b{re.escape(host)}\b", self.ugc_blob):
                return True
        return False

    def value_tainted(self, value: str) -> bool:
        """Does a typed value carry a token that only user content supplied?"""
        v = _norm_text(value)
        if not v:
            return False
        tokens = set(_EMAIL.findall(v)) | set(_URL.findall(v)) | set(_HOST.findall(v))
        for tok in tokens:
            if tok in self.ugc_blob and tok not in self.trusted_blob:
                return True
        # Long verbatim copies of user content.
        return len(v) >= 24 and v in self.ugc_blob and v not in self.trusted_blob

    def pii_in(self, text: str) -> set[str]:
        low = unquote(text or "").lower()
        hits = set()
        for key in PII_KEYS:
            val = (self.scope.pii.get(key) or "").lower()
            if not val:
                continue
            if val in low or (key == "phone" and re.sub(r"\D", "", val) in re.sub(r"\D", "", low)):
                hits.add(key)
        return hits

    # ---------------------------------------------------------------- rules
    def _intent_of(self, el: Element, obs: Observation) -> str | None:
        text = f"{el.label} {el.form_action or ''}".lower()
        if el.kind == "link" and not el.form:
            return None
        if el.kind == "button" or el.form is not None:
            for name, (ctl_rx, _) in INTENTS.items():
                if re.search(ctl_rx, text):
                    return name
        return None

    def _nav_target(self, el: Element) -> str | None:
        if el.kind == "link":
            return el.href
        if el.kind == "button" and el.form is not None:
            return el.form_action
        return None

    def _origin_ok(self, url: str, obs: Observation) -> bool:
        o = origin_of(url)
        return not o or o == obs.origin or o in self.scope.origins

    def check(self, action: Action, obs: Observation) -> Decision:
        d = self._check(action, obs)
        self.log.append(
            {"action": action.kind, "verdict": d.verdict, "rule": d.rule, "reason": d.reason}
        )
        return d

    def _check(self, a: Action, obs: Observation) -> Decision:
        cfg = self.cfg
        if a.kind in ("read_ugc", "back", "stop"):
            return Decision(ALLOW)
        if a.kind == "answer":
            return self._check_answer(a)
        if a.kind == "goto":
            url = a.url or ""
            if cfg.origin_set and not self._origin_ok(url, obs):
                return Decision(
                    BLOCK, "origin-set", f"{origin_of(url)} is outside the task's origins"
                )
            if cfg.ugc_rules:
                pii = self.pii_in(url)
                if (
                    pii
                    and origin_of(url) != obs.origin
                    and origin_of(url) not in self.scope.origins
                ):
                    return Decision(BLOCK, "pii", f"would send {sorted(pii)} to {origin_of(url)}")
                if self.url_tainted(url):
                    return Decision(CONFIRM, "ugc-url", "this address appears only in user content")
            return Decision(ALLOW, expect_nav={norm_url(url)})
        el = obs.element(a.element or "")
        if el is None:
            return Decision(BLOCK, "unknown-element", "element not on the page")
        in_ugc = obs.untrusted(el.region)
        if a.kind == "type":
            if cfg.ugc_rules:
                form_in_ugc = el.form is not None and obs.untrusted(obs.regions.region_of(el.form))
                if in_ugc or form_in_ugc:
                    return Decision(BLOCK, "ugc-form", "this field belongs to user content")
                if self.value_tainted(a.text or ""):
                    return Decision(CONFIRM, "ugc-value", "the value comes from user content")
                pii = self.pii_in(a.text or "") - self.scope.pii_ok
                if pii:
                    return Decision(CONFIRM, "pii", f"task did not ask to share {sorted(pii)}")
            return Decision(ALLOW)
        if a.kind == "click":
            target = self._nav_target(el)
            if cfg.ugc_rules:
                form_in_ugc = el.form is not None and obs.untrusted(obs.regions.region_of(el.form))
                if el.kind == "button" and (form_in_ugc or in_ugc):
                    # Could be a site control rendered inside a review ("Helpful", "Report")
                    # or a form a user smuggled in; only the user can tell which.
                    return Decision(CONFIRM, "ugc-form", "this button sits inside user content")
                if in_ugc and el.kind == "link":
                    return Decision(
                        CONFIRM,
                        "ugc-link",
                        f"link posted by a site user ({el.href})",
                        expect_nav={norm_url(el.href or "")},
                    )
                if target and el.kind == "link" and self.url_tainted(target):
                    return Decision(CONFIRM, "ugc-url", "this address appears only in user content")
                if target and origin_of(target) != obs.origin:
                    pii = self.pii_in(target)
                    if pii and origin_of(target) not in self.scope.origins:
                        return Decision(
                            BLOCK, "pii", f"would send {sorted(pii)} to {origin_of(target)}"
                        )
                intent = self._intent_of(el, obs)
                if intent and intent not in self.scope.intents:
                    return Decision(CONFIRM, "out-of-scope", f"task did not ask to {intent}")
            if cfg.origin_set and target and not self._origin_ok(target, obs):
                return Decision(
                    BLOCK, "origin-set", f"{origin_of(target)} is outside the task's origins"
                )
            expect = {norm_url(target)} if target else set()
            return Decision(ALLOW, expect_nav=expect)
        return Decision(BLOCK, "unknown-action", a.kind)

    def _check_answer(self, a: Action) -> Decision:
        text = a.text or ""
        if not self.cfg.ugc_rules:
            return Decision(ALLOW, answer=text)

        def label(m: re.Match) -> str:
            url = m.group(0)
            if self.url_tainted(url):
                return f"{url} [link from user-generated content, not verified by the site]"
            return url

        out = _URL.sub(label, text)
        return Decision(ALLOW, "answer-link" if out != text else "", answer=out)

    # ------------------------------------------------------ network layer (R7)
    def authorize(self, decision: Decision) -> None:
        self.expect_nav = set(decision.expect_nav)

    def allow_navigation(self, url: str, current_origin: str) -> bool:
        """Called for every main-frame navigation request."""
        if not (self.cfg.network and (self.cfg.ugc_rules or self.cfg.origin_set)):
            return True
        if origin_of(url) == current_origin or not current_origin:
            return True
        return norm_url(url) in self.expect_nav

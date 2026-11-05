"""A flat, index-addressed view of an HTML document.

Everything in ugcguard works on node *indexes* rather than lxml element objects:
lxml creates element proxies lazily, so identity comparisons are only reliable
while a reference is held. ``Doc`` holds every element in document order and
precomputes the per-node aggregates (text length, link text, counts of links,
images, form controls, ...) that both the markup detectors and the section
classifier need. One bottom-up pass keeps this linear in the size of the page.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from lxml import etree
from lxml import html as lhtml

# Subtrees whose text is never rendered as page text.
SKIP_TAGS = frozenset(
    {"script", "style", "noscript", "template", "head", "title", "meta", "link", "svg", "math"}
)
BLOCK_TAGS = frozenset(
    {
        "article",
        "aside",
        "blockquote",
        "dd",
        "details",
        "div",
        "dl",
        "fieldset",
        "figure",
        "footer",
        "form",
        "header",
        "li",
        "main",
        "nav",
        "ol",
        "p",
        "section",
        "table",
        "td",
        "tr",
        "ul",
    }
)
HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
INPUT_TAGS = frozenset({"input", "textarea", "select"})
_WS = re.compile(r"\s+")
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none|visibility\s*:\s*hidden", re.I)


def normalize_ws(text: str) -> str:
    return _WS.sub(" ", text).strip()


def parse_html(markup: str | bytes) -> etree._Element:
    """Parse a full document (or a fragment) into an <html> root element."""
    if isinstance(markup, bytes):
        markup = markup.decode("utf-8", errors="replace")
    markup = markup.replace("\x00", "")
    # Drop an XML declaration: lxml refuses str input that carries an encoding.
    markup = re.sub(r"^\s*<\?xml[^>]*>", "", markup)
    parser = lhtml.HTMLParser(remove_comments=True, remove_pis=True, huge_tree=True)
    if not markup.strip():
        markup = "<html><body></body></html>"
    try:
        root = lhtml.document_fromstring(markup, parser=parser)
    except (etree.ParserError, ValueError):
        root = lhtml.document_fromstring("<html><body></body></html>", parser=parser)
    return root


def _is_hidden(el: etree._Element) -> bool:
    if el.get("hidden") is not None:
        return True
    if (el.get("aria-hidden") or "").strip().lower() == "true":
        return True
    style = el.get("style")
    return bool(style and _HIDDEN_STYLE.search(style))


@dataclass
class Doc:
    """An indexed HTML document. Build it with :meth:`Doc.from_html`."""

    root: etree._Element
    url: str | None = None
    nodes: list = field(default_factory=list)
    index: dict = field(default_factory=dict)
    parent: list[int] = field(default_factory=list)
    depth: list[int] = field(default_factory=list)
    tag: list[str] = field(default_factory=list)
    skipped: list[bool] = field(default_factory=list)
    own_text: list[str] = field(default_factory=list)
    # Bottom-up aggregates (over the visible subtree, self included).
    text_len: list[int] = field(default_factory=list)
    link_text_len: list[int] = field(default_factory=list)
    n_links: list[int] = field(default_factory=list)
    n_img: list[int] = field(default_factory=list)
    n_button: list[int] = field(default_factory=list)
    n_input: list[int] = field(default_factory=list)
    n_form: list[int] = field(default_factory=list)
    n_time: list[int] = field(default_factory=list)
    n_heading: list[int] = field(default_factory=list)
    n_p: list[int] = field(default_factory=list)
    n_li: list[int] = field(default_factory=list)
    n_svg: list[int] = field(default_factory=list)
    n_desc: list[int] = field(default_factory=list)
    children: list[list[int]] = field(default_factory=list)
    _text_cache: dict = field(default_factory=dict)

    @classmethod
    def from_html(cls, markup: str | bytes, url: str | None = None) -> Doc:
        doc = cls(root=parse_html(markup), url=url)
        doc._build()
        return doc

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        nodes = [el for el in self.root.iter() if isinstance(el.tag, str)]
        self.nodes = nodes
        self.index = {el: i for i, el in enumerate(nodes)}
        n = len(nodes)
        parent = [-1] * n
        depth = [0] * n
        tags = [""] * n
        skipped = [False] * n
        own = [""] * n
        children: list[list[int]] = [[] for _ in range(n)]
        index = self.index
        for i, el in enumerate(nodes):
            tag = el.tag.lower() if isinstance(el.tag, str) else ""
            if ":" in tag:  # namespaced (e.g. svg:path) -> local name
                tag = tag.rsplit(":", 1)[-1]
            tags[i] = tag
            p = el.getparent()
            if p is not None and p in index:
                pi = index[p]
                parent[i] = pi
                depth[i] = depth[pi] + 1
                children[pi].append(i)
                skipped[i] = skipped[pi]
            if tag in SKIP_TAGS or _is_hidden(el):
                skipped[i] = True
        # Own visible text: element text plus the tails of its direct children.
        for i, el in enumerate(nodes):
            if skipped[i]:
                continue
            parts = []
            if el.text:
                parts.append(el.text)
            for c in el:
                if c.tail:
                    parts.append(c.tail)
            if parts:
                own[i] = normalize_ws(" ".join(parts))
        self.parent, self.depth, self.tag, self.skipped = parent, depth, tags, skipped
        self.own_text, self.children = own, children

        text_len = [0] * n
        link_text = [0] * n
        n_links = [0] * n
        n_img = [0] * n
        n_button = [0] * n
        n_input = [0] * n
        n_form = [0] * n
        n_time = [0] * n
        n_heading = [0] * n
        n_p = [0] * n
        n_li = [0] * n
        n_svg = [0] * n
        n_desc = [0] * n
        for i in range(n - 1, -1, -1):
            tag = tags[i]
            if tag == "svg" and not (parent[i] >= 0 and skipped[parent[i]]):
                n_svg[i] += 1  # star-rating icons are usually inline SVG
            if skipped[i]:
                pi = parent[i]
                if pi >= 0:
                    n_svg[pi] += n_svg[i]
                continue
            el = nodes[i]
            tl = len(own[i])
            text_len[i] += tl
            if tag == "a":
                # Count every anchor, href or not: some datasets (Mind2Web) strip hrefs.
                n_links[i] += 1
                link_text[i] = text_len[i]
            elif tag == "img":
                n_img[i] += 1
            elif tag == "button" or (el.get("role") or "").lower() == "button":
                n_button[i] += 1
            elif tag in INPUT_TAGS:
                typ = (el.get("type") or "").lower()
                if typ in ("submit", "button", "image", "reset"):
                    n_button[i] += 1
                elif typ != "hidden":
                    n_input[i] += 1
            elif tag == "form":
                n_form[i] += 1
            elif tag == "time":
                n_time[i] += 1
            elif tag in HEADING_TAGS:
                n_heading[i] += 1
            elif tag == "p":
                n_p[i] += 1
            elif tag == "li":
                n_li[i] += 1
            pi = parent[i]
            if pi >= 0:
                text_len[pi] += text_len[i]
                link_text[pi] += link_text[i]
                n_links[pi] += n_links[i]
                n_img[pi] += n_img[i]
                n_button[pi] += n_button[i]
                n_input[pi] += n_input[i]
                n_form[pi] += n_form[i]
                n_time[pi] += n_time[i]
                n_heading[pi] += n_heading[i]
                n_p[pi] += n_p[i]
                n_li[pi] += n_li[i]
                n_svg[pi] += n_svg[i]
                n_desc[pi] += n_desc[i] + 1
        self.text_len, self.link_text_len, self.n_links = text_len, link_text, n_links
        self.n_img, self.n_button, self.n_input, self.n_form = n_img, n_button, n_input, n_form
        self.n_time, self.n_heading, self.n_p, self.n_li = n_time, n_heading, n_p, n_li
        self.n_svg, self.n_desc = n_svg, n_desc

    # ---------------------------------------------------------------- queries
    def __len__(self) -> int:
        return len(self.nodes)

    def idx(self, el: etree._Element) -> int:
        return self.index[el]

    def text(self, i: int, limit: int | None = None) -> str:
        """Visible text of node ``i``'s subtree, in reading order, whitespace-normalized."""
        key = (i, limit)
        if key in self._text_cache:
            return self._text_cache[key]
        if self.skipped[i]:
            return ""
        parts: list[str] = []
        total = 0
        stack: list = [i]
        index = self.index
        while stack:
            item = stack.pop()
            if isinstance(item, str):
                parts.append(item)
                total += len(item)
            else:
                if self.skipped[item]:
                    continue
                el = self.nodes[item]
                if el.text:
                    parts.append(el.text)
                    total += len(el.text)
                for c in reversed(el):
                    if c.tail:
                        stack.append(c.tail)  # a child's tail belongs to this node's flow
                    ci = index.get(c)
                    if ci is not None:
                        stack.append(ci)
            if limit is not None and total >= limit:
                break
        out = normalize_ws(" ".join(parts))
        if limit is not None:
            out = out[:limit]
        self._text_cache[key] = out
        return out

    def ancestors(self, i: int):
        p = self.parent[i]
        while p >= 0:
            yield p
            p = self.parent[p]

    def is_descendant(self, i: int, anc: int) -> bool:
        return any(a == anc for a in self.ancestors(i))

    def subtree(self, i: int):
        stack = [i]
        while stack:
            j = stack.pop()
            yield j
            stack.extend(self.children[j])

    def attr(self, i: int, name: str, default: str | None = None) -> str | None:
        return self.nodes[i].get(name, default)

    def classes(self, i: int) -> list[str]:
        return (self.nodes[i].get("class") or "").split()

    def find_attr(self, name: str, value: str) -> int | None:
        """First node whose attribute ``name`` equals ``value``."""
        for i, el in enumerate(self.nodes):
            if el.get(name) == value:
                return i
        return None

    def resolve_url(self, href: str | None) -> str | None:
        if href is None:
            return None
        href = href.strip()
        if not href or href.lower().startswith(("javascript:", "mailto:", "tel:", "data:")):
            return None
        if self.url:
            try:
                return urljoin(self.url, href)
            except ValueError:
                return None
        return href

    @property
    def body(self) -> int:
        for i, t in enumerate(self.tag):
            if t == "body":
                return i
        return 0

    @property
    def page_text_len(self) -> int:
        return self.text_len[self.body] if self.nodes else 0


def site_of(url: str | None) -> str:
    """Registrable-domain approximation (eTLD+1) without a public-suffix list."""
    if not url:
        return ""
    host = (urlsplit(url).hostname or "").lower().strip(".")
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    two_level = {"co", "com", "ac", "gov", "org", "net", "edu", "ne", "or", "go"}
    if parts[-2] in two_level and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def origin_of(url: str | None) -> str:
    if not url:
        return ""
    s = urlsplit(url)
    if not s.scheme or not s.netloc:
        return ""
    return f"{s.scheme}://{s.netloc}".lower()

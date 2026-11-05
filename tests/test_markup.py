from ugcguard import Doc, detect
from ugcguard.markup import anchor_text, markup_regions
from ugcguard.signatures import signature_regions

PAGE = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Kettle",
 "review":[{"@type":"Review","reviewBody":"Boils fast and the handle stays cool, I use it daily."}]}
</script>
<script type="application/ld+json">{"@type":"FAQPage","mainEntity":[{"@type":"Question",
 "name":"Dishwasher safe?","acceptedAnswer":{"@type":"Answer","text":"No, hand wash the body only please."}}]}
</script></head><body>
<main><h1>Kettle</h1><p>Our kettle boils 1.7 litres in 3 minutes.</p>
<section>
 <div class="r">Boils fast and the handle stays cool, I use it daily.
   <a href="http://x.test" rel="nofollow ugc">my blog</a></div>
 <div itemscope itemtype="https://schema.org/Review">
   <span itemprop="author" itemscope itemtype="https://schema.org/Person"><span itemprop="name">Bob</span></span>
   <p itemprop="reviewBody">Too loud for my taste, returned it.</p><button>Helpful</button></div>
 <div typeof="schema:Comment"><p property="schema:text">An RDFa comment that is long enough.</p></div>
 <div role="comment">An ARIA 1.3 comment that is long enough</div>
 <div class="h-review">A microformat review text, long enough</div>
 <div itemscope itemtype="https://schema.org/CriticReview"><p itemprop="reviewBody">Staff pick.</p></div>
</section>
<div itemscope itemtype="https://schema.org/FAQPage"><div itemscope itemprop="mainEntity"
  itemtype="https://schema.org/Question"><h3 itemprop="name">Dishwasher safe?</h3></div></div>
</main></body></html>"""


def _by_source(doc):
    regions, stats = markup_regions(doc)
    out = {}
    for r in regions:
        out.setdefault(r.source, []).append(r)
    return out, stats


def test_all_standard_sources_found():
    doc = Doc.from_html(PAGE, "https://shop.test/p/1")
    by, stats = _by_source(doc)
    assert set(by) == {"microdata", "rdfa", "json-ld", "rel-ugc", "aria", "microformats"}
    assert stats["jsonld_ugc_objects"] == 1  # the FAQ answer is first-party


def test_microdata_body_excludes_nested_author_and_editorial_types():
    doc = Doc.from_html(PAGE)
    by, _ = _by_source(doc)
    bodies = [doc.text(r.node) for r in by["microdata"] if r.scope == "body"]
    assert bodies == ["Too loud for my taste, returned it."]
    texts = " ".join(doc.text(r.node) for r in by["microdata"])
    assert "Staff pick" not in texts  # CriticReview is editorial
    assert "Dishwasher" not in texts  # FAQPage question is the site's own


def test_jsonld_is_anchored_to_the_rendered_review():
    doc = Doc.from_html(PAGE)
    by, _ = _by_source(doc)
    (r,) = by["json-ld"]
    assert doc.text(r.node).startswith("Boils fast and the handle stays cool")
    assert doc.tag[r.node] == "div"


def test_rel_ugc_marks_only_the_link():
    doc = Doc.from_html(PAGE)
    by, _ = _by_source(doc)
    (r,) = by["rel-ugc"]
    assert r.scope == "link" and doc.tag[r.node] == "a"


def test_region_map_lookup_prefers_innermost_region():
    doc = Doc.from_html(PAGE)
    rm = detect(doc, ("markup",))
    p = next(i for i, el in enumerate(doc.nodes) if el.get("itemprop") == "reviewBody")
    assert rm.region_of(p).scope == "body"
    button = doc.tag.index("button")
    assert rm.region_of(button).scope == "item"
    h1 = doc.tag.index("h1")
    assert not rm.is_ugc(h1)


def test_anchor_text_handles_markup_inside_body():
    doc = Doc.from_html("<div><p>First <b>part</b> of a long review text body here.</p></div>")
    node = anchor_text(doc, "First part of a long review text body here.")
    assert node is not None and doc.tag[node] == "p"


def test_signatures_are_specific():
    html = """<body>
      <div id="disqus_thread"></div>
      <div class="bv-content-item">A Bazaarvoice review body text</div>
      <ol class="comment-list"><li class="comment depth-1">WordPress comment text here</li></ol>
      <div class="comment">Generic comment class is left to the classifier</div>
      <div class="user-ugc-block">Something labelled ugc by the site itself</div>
      <div class="bugcount">not a ugc token</div>
    </body>"""
    doc = Doc.from_html(html)
    vendors = sorted({r.source for r in signature_regions(doc)})
    assert vendors == [
        "signature:bazaarvoice",
        "signature:disqus",
        "signature:ugc-token",
        "signature:wordpress",
    ]


def test_hidden_and_script_text_is_not_page_text():
    doc = Doc.from_html(
        "<body><p>visible</p><p style='display:none'>hidden</p><script>var x=1</script></body>"
    )
    assert doc.text(doc.body) == "visible"

# Design

## Threat model

* **The user** gives the agent a task and is trusted.
* **The site the agent was sent to** (its origin) is trusted for its own content: prices, forms, navigation, articles.
* **Other users of that site** are not trusted. They can write reviews, comments, posts, answers, display names and links. They cannot run script (the site sanitizes their HTML), and they cannot change first-party content.
* **The attacker** is one of those other users. They plant text that the agent will read while doing an ordinary task. Their goals: send the agent to their own site, exfiltrate the user's data, make the agent change the user's account, delete it, post the user's data publicly, buy things, or lie to the user.
* **The model** may be fully compromised by what it reads. The defense must not depend on the model resisting the injection, because that is what the UW study (ICLR 2026) showed the same-origin policy currently depends on.

Out of scope: malicious first-party sites, XSS (script injection), and attacks on the browser itself.

## Pipeline

```
 page ──► tag elements (data-ug ids) ──► serialize DOM ──► Doc (flat, indexed)
                                                            │
             ┌──────────────────────────────────────────────┤ detect()
             ▼                       ▼                      ▼
   standard markup           vendor signatures      section classifier
   (microdata, RDFa,         (Disqus, Bazaarvoice,  (structure + text +
   JSON-LD anchored to DOM,  WordPress, Discourse,   naming cues; fills
   rel=ugc, role=comment,    StackExchange, ...)     gaps only)
   microformats)
             └──────────────┬────────┴──────────────────────┘
                            ▼
                  RegionMap: node ──► Region(source, scope=item|body|link)
                            │
          ┌─────────────────┴──────────────────┐
          ▼                                    ▼
   Observation for the planner          Guard (enforcement)
   UGC fenced as <untrusted>, or        checks every proposed action
   hidden behind read_ugc() (mask)      against the zones of its target
                                        and arguments: allow / confirm / block
                                                │
                                                ▼
                                  network layer (Playwright route):
                                  cross-origin navigations the guard did
                                  not pre-authorize are aborted
```

## Why enforcement looks at zones, not intentions

An injection works by changing *why* the model wants to act. A guard that asks the model (or a second model) whether an action is justified is asking the compromised party. The guard therefore ignores reasons and checks provenance only:

* **where the target is**: an element inside a UGC region;
* **where the arguments came from**: a URL, host or typed value that appears in UGC and nowhere trusted (the task, first-party text, first-party links);
* **what the task authorized**: action categories and personal-data categories inferred from the user's instruction.

This is a coarse, string-level data-flow approximation. It is cheap and model-agnostic, and it fails in known ways (see Limitations in the README).

## Granularity

* **item**: the whole review/comment container is untrusted, including site controls rendered inside it ("Helpful", "Report"). Safe default; using those controls costs a confirmation prompt.
* **body**: only author-controlled fields (body, title, display name, `rel=ugc` links) are untrusted. This needs markup or signatures that say where the body is; classifier-only regions fall back to item.

## Baselines

* **origin-set**: a *perfect* version of Chrome's Agent Origin Sets. Cross-origin navigation is allowed only to the task's start origin and the origins the gold trajectory needs; all others are blocked. No intra-site rules.
* **detector-regex / detector-deberta**: detect-and-strip, in the style of BrowseSafe. Every text block is scored, and flagged blocks are removed before the planner sees the page. `detector-deberta` uses ProtectAI's open DeBERTa-v3 prompt-injection classifier.

## The scripted planner

`ScriptedPlanner(gullible=True)` executes the task's gold plan, but the moment a payload's text appears in its observation it switches to the attacker's plan. It retries a refused link by typing the URL, then resumes the user's task. It models a model that always obeys injected text, so attack success measures what the *defense* lets through, not how persuadable a particular model is. `LLMPlanner` plugs any OpenAI-compatible model into the same loop (`scripts/run_llm.py`).

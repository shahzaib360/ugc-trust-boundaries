# Manual audit of the WebLINX detections

The prevalence numbers rest on two detectors with very different precision. Both were checked by hand on random samples. Page URLs and text snippets are not reproduced here, because WebLINX is CC BY-NC-SA 4.0. The samples can be regenerated from `data/cache/` with the seeds below.

## Markup + vendor signatures ("rules")

Random sample of 30 of the 369 rule-positive pages (seed 7). For each page, I read the largest detected region.

| verdict | pages |
|---|---|
| a real UGC section (reviews, comments, posts, tweets; some were empty "be the first to review" widgets, which attackers can still write to) | 29 |
| first-party content (a publisher's own Q&A marked up as schema.org `Question`/`Answer` outside an `FAQPage`) | 1 |

Precision ≈ 97% (29/30).

## Classifier-only detections

Random sample of 50 of the 2,623 pages flagged by the out-of-fold classifier but by no rule (seed 42). For each page, I read the top three regions.

| verdict | pages |
|---|---|
| user-generated content (reviews, diner reviews, comments sections, user posts, organizer-written event pages) | 8 |
| other third-party text that is not UGC (search-result snippets, sponsored marketplace listings, recommendation widgets) | 9 |
| first-party content (article teasers, product copy, FAQs, UI text, marketing testimonials) | 33 |

Precision for UGC ≈ 16% (8/50; a 95% Wilson interval is roughly 8–29%). Including the attacker-influenceable third-party text, it is 34%.

## What this means for the headline numbers

* Pages with UGC found by rules: 3.7% (precision ≈ 97%).
* Classifier-only pages: 26.0% of all pages × 16% precision ≈ **+4.2 points**. This estimate is wide, and the classifier's recall is unknown, so it is a lower bound.
* Estimated pages with a UGC section: **≈ 8%** (vs. 2.6% with standard markup alone). Standard markup therefore covers **at most about a third** of the UGC that agents met in WebLINX.
* The raw classifier figures in `measurement.md` (29.7% of pages, 59.5% of demonstrations) are **upper bounds inflated by false positives** and should not be quoted as prevalence.

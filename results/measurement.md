# UGC on the pages web agents work on

WebLINX: 10,073 page snapshots from 2,336 demonstrations on 175 websites; 52,473 recorded actions.

| measure | standard markup | + vendor signatures | + classifier (upper bound) |
|---|---|---|---|
| pages with a UGC section | 2.6% | 3.7% | 29.7% |
| demonstrations that touch a UGC page | 7.4% | 9.8% | 59.5% |
| actions whose target is inside UGC | | 0.2% | 2.5% |

Standard markup (schema.org / rel=ugc / ARIA / microformats) marks UGC on 2.6% of pages, against an audited estimate of about 8% of pages that hold UGC: it covers at most about a third of the UGC agents meet. (Against the raw, unaudited classifier denominator the figure would be 8.8%.)

The classifier column is an upper bound: a manual audit (results/audit.md) found that only ~16% of classifier-only detections were real UGC, which puts pages with a UGC section at roughly 8% (rules 3.7% + about 4 points from the classifier).

| category | pages | markup | markup + signatures | + classifier (upper bound) |
|---|---|---|---|---|
| search & AI tools | 2092 | 0.4% | 0.4% | 28.2% |
| shopping | 1331 | 5.9% | 9.7% | 30.9% |
| social, forums & UGC platforms | 1248 | 6.2% | 10.3% | 39.7% |
| reference & education | 1220 | 0.5% | 0.5% | 27.4% |
| food & restaurants | 1126 | 6.6% | 6.7% | 35.7% |
| travel & booking | 926 | 0.1% | 0.2% | 29.0% |
| news & magazines | 855 | 0.0% | 0.0% | 38.5% |
| productivity & chat | 747 | 0.0% | 0.0% | 12.4% |
| email | 343 | 5.0% | 5.0% | 11.1% |
| other | 185 | 0.0% | 0.5% | 16.2% |

Mind2Web (train): 7,775 action steps in 1,009 tasks on 73 websites. Its snapshots strip href, itemprop, rel, most data-* attributes and scripts (as many agent pipelines do when they simplify the DOM), so markup is invisible and only class/id signatures and the classifier apply. The classifier figures were not audited on Mind2Web; given the 16% precision measured on WebLINX they are loose upper bounds.

- steps on a page with UGC: 0.5% (signatures), up to 45.6% (+ classifier)
- tasks touching a UGC page (+ classifier): up to 75.7%
- action targets inside UGC (+ classifier): up to 3.8%

| domain | steps | signatures | + classifier (upper bound) |
|---|---|---|---|
| Entertainment | 1384 | 0.0% | 55.1% |
| Shopping | 2309 | 1.6% | 45.3% |
| Travel | 4082 | 0.1% | 42.6% |

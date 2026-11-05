# Section classifier: model card

**What it does.** Scores a block of a web page (div, li, article, ...) by how likely it is to hold user-generated content (reviews, comments, posts, answers). It is the fallback for pages that publish no UGC markup.

**Files.**
* `section_classifier.pkl`: structure + text + class/id naming cues (default)
* `section_classifier_nonames.pkl`: structure + text only, for sites with hashed class names

Both are scikit-learn `HistGradientBoostingClassifier` models with 150 iterations, minimum leaf size 200, balanced class weights and per-website sample weights. The pickles need a compatible scikit-learn version. Rebuild them with `python scripts/train_classifier.py` (after `scripts/collect_weblinx.py` and `scripts/analyze_weblinx.py`).

**Training data.** 349,197 candidate blocks from 10,073 page snapshots in WebLINX (McGill-NLP/WebLINX-full), covering 198 registrable domains. Labels are distant: a block is positive if it lies inside a region marked by schema.org microdata, RDFa, JSON-LD (anchored to the DOM), `rel="ugc"`, ARIA `role="comment"`, microformats, or a known review/comment-widget signature. It is negative if it overlaps no such region. The markup attributes themselves are never features.

**Evaluation.** Everything is grouped by website, so no site appears in both train and test (`results/classifier_eval.json`):

* trained and tested on markup labels (5-fold, by site): ROC-AUC 0.95, average precision 0.59;
* trained on markup labels, tested on 10 sites where *only* vendor signatures reveal UGC: ROC-AUC 0.86, average precision 0.03. Generalization to unseen kinds of UGC layout is the weak point.

**Known limitations.** Only 33 of 198 sites contribute positive labels, so the model has seen few UGC layouts, and two sites (StackExchange, Uniqlo) supply a large share of them. It is conservative: on the benchmark's synthetic pages it misses most review and post sections. Treat it as a measurement aid and a weak fallback, not a boundary you can rely on. The enforcement layer is only as good as the regions it is given.

**License.** The model is derived from WebLINX, which is licensed CC BY-NC-SA 4.0, so the model files are provided under the same terms (attribution, non-commercial, share-alike). The code in this repository is MIT.

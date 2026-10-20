# Publishing AI / CS research in 2026 (updated 2026-10-20)
- Novelty means a gap you can state in one sentence AND evidence you searched for it: cite the 5-10 closest works and
  say exactly what each does not do. "Nobody has combined X and Y" is not a contribution unless combining them answers
  a real question with a measurable result.
- Claims need experiments: a baseline, your method, the same data and metric, several seeds, and the variance. Small,
  honest and reproducible beats big and vague. Free compute only: CPU/MPS on the Mac, small open models, public data.
- Reproducibility checklist (NeurIPS/ICML style): code, data source, hyperparameters, seeds, compute used, limitations,
  and a statement of what was NOT tested. Negative or null results are publishable when the question is good.
- Structure: abstract (what, how, result, so what), introduction with the gap and 2-3 contributions, related work, method,
  experiments, limitations, conclusion. Keep it short: 4-8 pages of real content.
- Venues (free to submit): arXiv (cs.AI/cs.CL/cs.CV/cs.LG/cs.RO; needs an endorsement for a first-time author in a
  category), workshops at NeurIPS/ICML/ICLR/ACL (lower bar, good feedback), TMLR (rolling), and ACM/IEEE student tracks.
  Most venues now require disclosure of AI assistance; Pribin is the author and must read and own every line.
- Citations come only from references.bib built from API metadata; every number in Results comes from logged runs.
  Fabricated citations or numbers end the project. Prefer primary sources; mark preprints as preprints.
- Writing: define terms, one idea per paragraph, figures with captions that stand alone, no hype words.
Sources: NeurIPS 2025/2026 paper checklist and LLM policy, ICML 2026 call for papers, arXiv submission guidelines
(endorsement, categories), TMLR author guide. Venue rules change yearly: check the current call before submitting.

## Plagiarism
The lab's paper_check runs two more guards: overlap (8-word shingles against every paper text the lab has read) and a web quote search of the paper's most distinctive sentences. Paraphrase passes; copied passages do not, even from your own earlier drafts of other projects. Quote rarely, in quotation marks, with a citation.

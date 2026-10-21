# Open-source licensing and community (updated 2026-10-21)
- Licence before code: MIT or Apache-2.0 for libraries you want used; AGPL only when you want to force sharing.
  Apache-2.0 adds a patent grant, which companies prefer. Put LICENSE and SPDX headers in every repo (REUSE spec).
- Know what you depend on: AGPL dependencies (Ultralytics YOLO, some databases) make a shipped product AGPL unless
  you buy a licence; GPL cannot be linked into closed products; MIT, BSD, Apache and MPL are safe to combine. Run a
  licence scan (pip-licenses, ScanCode) before a release and record the result.
- Contributor basics: CONTRIBUTING.md (how to run tests, how to propose), a CODE_OF_CONDUCT, issue templates, a
  "good first issue" label, and a reply to every issue within 3 days even if the reply is "later".
- Releases: semantic versions, changelog, a GitHub release with binaries or a pip package; breaking changes only in a
  major version with a migration note.
- Docs are the funnel: README with a 60-second quick start, one tutorial, API reference generated from docstrings.
- Community health metrics: issues answered, time to first reply, external contributors, stars are vanity.
- Trademark and names: check the name is free on PyPI, GitHub and a trademark search before announcing.
- Contributor licence: a DCO sign-off (git commit -s) is enough for small projects; a CLA only if a company asks.
Sources: SPDX and REUSE specifications; Open Source Guides (GitHub); choosealicense.com; Ultralytics licensing page;
Apache Software Foundation licence FAQ.

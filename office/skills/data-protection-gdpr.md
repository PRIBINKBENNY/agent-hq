# Data protection for a UK AI business (UK GDPR, updated 2026-10-21)
- Personal data is anything about an identifiable person: names, emails, enquiry text, images of faces, voice. If
  the office stores it, the rules apply; a sole trader processing client data is a controller.
- Lawful basis: contract (replying to a client's enquiry), legitimate interests (keeping a lead's details to follow
  up, documented), consent (marketing to individuals, any special-category data). Record the basis per dataset.
- Transparency: a short privacy notice for clients and their customers (what, why, how long, their rights); the
  enquiry assistant's replies may mention that an assistant drafts and a human approves.
- Minimise and expire: keep enquiries only as long as needed; redact before using them for evaluation; never upload
  raw personal data to a model API without a basis and a processor agreement (free-tier providers may train on
  inputs: check their terms, prefer providers that do not).
- Rights: access, deletion, correction within one month; keep a simple log of requests.
- Security: encryption at rest where possible, access only to what each agent needs, secrets redaction, breach
  log; a breach likely to harm people is reported to the ICO within 72 hours.
- Register with the ICO (small fee) once personal data is processed as a business; put it in the compliance sweep.
- Automated decisions: the office never makes a decision with legal effect on a person without a human; approval
  gates are that human.
Sources: ICO guide to UK GDPR and the data protection fee; ICO AI and data protection guidance; the office's
compliance guide.

# Agentic security audit: OWASP Top 10 for Agentic Applications (updated 2026-10-20)
Published December 2025 by the OWASP GenAI Security Project. What each item means in this office:
1. Agent goal hijack: instructions hidden in email, web pages or files redirect an agent. Here: untrusted content is data, never instructions; mail_read adds a content-safety label; a flagged message is withheld.
2. Tool misuse and excessive permissions: an agent calls a tool it should not have. Here: every brief lists its tools; outward tools (send, post, trade, push) are approval-gated in code.
3. Identity and privilege abuse: acting with more rights than the task needs. Here: trading is DEMO-locked; GitHub pushes only to Pribin's own account; no agent holds a key, tool code does.
4. Supply-chain and skill poisoning: a poisoned skill or brief changes behaviour. Here: skills and briefs change only through approved proposals that are validated and rolled back on error.
5. Unexpected code execution: run_python/run_shell on attacker-supplied text. Here: builders have no web tools; shell is confined to the workspace.
6. Memory and context poisoning: a planted memory steers later runs. Here: memories carry their agent and source; lessons pass a quality filter; the brain is recall-with-provenance.
7. Insecure inter-agent communication: a delegated task carries injected text. Here: delegation depth and allowlists per brief.
8. Cascading failures: one bad output feeds many agents. Here: the fact-checker QA gate on outgoing text; approvals ranked and grouped.
9. Human-in-the-loop bypass: an agent finds a path around approval. Here: approval is checked in the tool, not the prompt; approve-and-send is the only path out.
10. Insufficient logging and monitoring: no trace of what an agent did. Here: every run, tool call and send is logged; secrets are redacted from results and answers.
Monthly audit (compliance-officer): check each item against the current briefs and tools, write workspace/ops/security-audit-<month>.md, open a task for the COO per gap.

Sources: OWASP GenAI Security Project, Top 10 for Agentic Applications (Dec 2025); 2026 defence-in-depth guides (Maxim, StartupDefense) summarising it.

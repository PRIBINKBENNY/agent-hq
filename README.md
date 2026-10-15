# Agent HQ

An office of 28 AI agents with one shared brain, built for zero cost, running on a 2020 MacBook.

![Agent HQ live dashboard](docs/dashboard.png)

![Agents at work](docs/demo.gif)


- **Brain** (`brain/`): shared memory. Local SQLite + keyword + semantic search. Free.
- **Office** (`office/`): the agents. Run on Groq's free tier, fall back to local Ollama. Free.
- **Workspace** (`workspace/`): what the agents produce (CVs, cover letters, prep packs).

## Quick start

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # paste your free key from https://console.groq.com/keys
.venv/bin/python office/run.py --list
.venv/bin/python office/run.py "find 5 junior ML engineer jobs in London and tailor my CV for the best one"
.venv/bin/python office/run.py --approvals      # what is waiting for your OK
```

## Live dashboard

```bash
.venv/bin/python office/dashboard.py        # then open http://localhost:8787
```

An isometric office floating in space, one coloured room per office, drawn live on a
canvas (no art assets). Each agent sits at a desk; the monitor lights up while it thinks,
a speech bubble shows what it is doing, it walks to THE BRAIN in the centre when it
recalls or remembers, and walks to another room when it delegates. Floating cards show
"N agents · M running" per room. Drag to pan, scroll to zoom. Beside it: the live event
feed, approvals with Approve / Reject, the brain's latest memories, and a command box
that starts runs, plus a 🎤 button for voice commands (Chrome/Edge, free, in-browser), the task board, and run
history with full answers. New offices and agents appear automatically from `office/agents/`.

Talk to the **Chief of Staff** by default. It delegates to the right agents, logs what
happened in the brain, and parks anything that needs your decision in approvals.
Run a single agent with `--agent job-scout "..."`. Force local with `--engine ollama`.

## The roster (7 offices, 28 agents)

| Office      | Agents |
| ----------- | ------ |
| front-desk  | chief-of-staff: your single contact; splits commands, delegates, keeps the board, guards approvals |
| job-hunt    | job-scout (LinkedIn search + fit score), application-tailor (CV + cover letter, truth-checked), interview-coach (prep packs, mocks) |
| studio      | studio-lead, agent-builder, web-builder, app-developer, code-builder, tester (never fixes), debugger (never weakens tests), reviewer (never writes) |
| brand-sales | linkedin-writer, content-writer (reels/shorts scripts), lead-finder (buyers for the productised offer), proposal-writer (pitches + quotes), networker (warm paths into target companies) |
| trading     | market-researcher (live quotes), strategy-analyst (backtests, signals), risk-officer (sizes and approves, can veto), trader (executes on the Capital.com **demo** account), portfolio-tracker. **Virtual money; the live endpoint is locked in code.** |
| ops         | tracker (job + client pipelines), mail-assistant (email drafts to `workspace/outbox/`, .ics calendar files), fact-checker (QA gate: every outgoing text is verified against the brain before approval) |
| pm          | project-manager (team leader: roadmap, daily sprint), release-manager (commits, changelog, pushes to Pribin's own GitHub), docs-writer, ml-researcher (weekly trends + project proposals) |

## Task board and "nobody stops"

Every run can be queued as a task; the scheduler runs queued tasks one at a time (Groq's free
tier dislikes parallel runs) and marks them done or failed with the result. Recurring jobs live in
`office/schedule.yaml` (daily job scan 08:00, morning digest 08:30, evening pipeline update).
The dashboard runs the scheduler while it is open; for a laptop that stays on without the
browser, run `.venv/bin/python office/scheduler.py` instead.

Approving an item on the dashboard creates a follow-up task for the Chief of Staff (log it as
applied, draft the follow-up email), so your decision feeds back into the office.

## Project management team and GitHub

`workspace/roadmap.md` lists AI projects with small milestones. Every weekday at 10:00 the
project-manager runs a sprint: pick one milestone, get it built (studio), tested, reviewed, then
the release-manager commits with a conventional message, updates the changelog and pushes to
Pribin's own GitHub (private repos by default; `git_push` refuses any other account). That is how
the GitHub graph fills up with real, tested work rather than noise. Check the repos and today's
commit count with the `github_status` tool or `gh repo list`.

## Always on

```bash
./office/launchd/install.sh        # start at login, restart on crash (macOS launch agent)
./office/launchd/install.sh off    # remove
```

Desktop notifications fire when an approval is waiting or a task finishes. Approvals on the
dashboard have a **view** button that opens the file behind them; `export_pdf` turns a tailored CV
into an A4 PDF ready to upload. The engine tile shows each provider's remaining tokens per minute.

## Strategy layer

- `workspace/plan-90-days.md`: the goal, phases, and weekly targets. The `scorecard` tool reads the
  targets and counts what actually happened (applications, contacts, proposals, posts, mock
  interviews, commits, fabrications caught). The dashboard shows it; the Chief of Staff reviews it
  every Monday and names one change for the week.
- `workspace/offer.md`: the productised freelance offer (AI back-office for a small business, three
  packages with prices). The lead-finder hunts for that buyer; the proposal-writer quotes from it.
- `workspace/roadmap.md`: AI projects with milestones, fed by the ml-researcher and shipped by the PM office.
- Daily interview drill at 07:30; weekly networking pass on Tuesdays.

## Reliability and safety layer

- **Continuations**: a run that hits its turn limit reports DONE/REMAINING and queues a follow-up task
  for the rest, so long work never dies at a limit.
- **Reflection**: after each real run the agent writes one lesson into the brain (expires after 60 days).
- **Fact-check gate**: any approval that points at a CV, letter, post or proposal automatically gets a
  fact-checker task; the approval card shows QA: PASS / EDITS / FAIL.
- **Claim guard** and **CV truth check** catch fabricated actions and skills.
- **Prompt-injection defence**: all web content is marked untrusted and instruction-like lines are
  removed; agents that browse the web never hold execution tools.
- **Eval harness** (`office/eval/`): ten tasks with known-correct behaviour, run per provider; reports
  pass rate and fabrication rate. Runs weekly; results feed the Ops panel.
- **Ops panel**: runs, tokens, time and failures per agent, provider share, last eval.

## Phone app (iOS / Android)

The office has a mobile command centre at `/m`: approvals (approve, reject, "I applied", view the
file), today's digest, the task board, the scorecard, a live feed, voice commands, and push
notifications for approvals and finished tasks. It installs as a Home Screen app (Safari: Share →
Add to Home Screen), no App Store, no Apple developer account, free.

Reach it from outside the Mac through a free tunnel; every remote request needs the
`DASHBOARD_TOKEN` from `.env` (entered once, kept as a cookie):

```bash
./office/launchd/install.sh tunnel     # Cloudflare quick tunnel as a launch agent (URL changes on restart)
./office/launchd/install.sh url        # print the current phone URL
```

For a permanent private URL use Tailscale, or a named Cloudflare tunnel on your own domain.
See `DEPLOY.md`, which also covers running the office on a free cloud VM so it keeps working
when the Mac is off. While it runs on the Mac, the dashboard keeps the machine awake on mains power.

## Trading desk (Capital.com demo)

The trading office runs on a free Capital.com demo account: real markets, real prices, virtual money.
Keys go in `.env` (`CAPITAL_API_KEY`, `CAPITAL_IDENTIFIER`, `CAPITAL_PASSWORD`). The demo endpoint is
the default and the only one used unless `CAPITAL_LIVE=I_UNDERSTAND_REAL_MONEY` is set deliberately.

During London hours on weekdays the desk runs by itself: an hourly market pulse (researcher), a signal
scan when something moves (strategy-analyst), a risk review for every signal (risk-officer: max 10% of
balance per position, max 6 positions, stop mandatory, sector limits), execution of APPROVED decisions
only (trader, which refuses anything not backed by a risk-officer approval memory), hourly stop
management, and a 17:30 summary. The same limits are enforced in code in `office/capital.py`, so no
agent can exceed them whatever it is told.

Nothing here is financial advice; the point is a measurable, auditable paper record.

## Operating it

```bash
.venv/bin/python office/run.py --doctor      # health check: providers, budget left, launch agent, brain, approvals, GitHub
.venv/bin/python office/run.py --providers   # ping each free-tier provider
./office/publish.sh                          # refresh the public portfolio repo from this one (also runs Fridays)
```

- **Budget pacing**: the runtime reads each provider's rate-limit headers (per minute and per day) and
  steps a provider aside before it hits the wall, so work flows to the next free tier instead of failing.
- **Learning loop**: every real run ends with a one-line lesson; an agent's last three lessons are injected
  into its next prompt. Click any agent on the floor to see its brief, recent runs and lessons.
- **Backups**: the brain is backed up daily to `brain/data/backups/` (7 kept). Task logs and handoff notes
  are rotated automatically.
- **Eval baseline** (10 tasks, 2026-10-15): Groq 100% pass, Cerebras 90%, local Ollama 3B 60%.

## Tests

```bash
.venv/bin/python -m pytest -q tests
```

Covers the brain (recall, dedupe, namespaces, TTL, task board), the runtime (argument
sanitising, cooldown model picking, a full fake-engine tool loop, every brief's tools and
delegates), events, and the schedule logic.

## Adding an agent

Create `office/agents/<name>.md`:

```markdown
---
name: my-agent
office: studio
tier: worker            # lead = bigger model first, worker = fast model first
tools: [brain_recall, brain_remember, web_search, web_fetch, read_file, write_file]
delegates: []           # names of agents this one may hand tasks to
---
What this agent is, how it works, what it must never do.
```

Add it to a lead's `delegates:` list and it's hired.

## Models and limits: a pool of free tiers

The office does not depend on one provider. Every provider below is free, OpenAI-compatible,
and needs only a key in `.env`. The runtime tries them in order, keeps a cooldown per model,
hops to the next on a rate limit, and lands on local Ollama only when everything remote is
cooling down. On first use it asks each provider which models it actually serves, so a retired
model name can never stall a run.

| Order | Provider | Key | Free allowance (approx.) | Notes |
| ----- | -------- | --- | ------------------------ | ----- |
| 1 | Cerebras | `CEREBRAS_API_KEY` | ~60K tokens/min, 1M/day | fastest, GPT-OSS 120B + Qwen 3.8 27B |
| 2 | Groq | `GROQ_API_KEY` | ~8K tokens/min per model | GPT-OSS 120B/20B, Qwen 3.8 27B |
| 3 | Mistral | `MISTRAL_API_KEY` | ~1B tokens/month | prompts may be used for training |
| 4 | Gemini | `GEMINI_API_KEY` | ~15 req/min on Flash | good for long inputs |
| 5 | Ollama | none | unlimited, slow | `llama3.2:3b` on the Mac |

Check the pool any time:

```bash
.venv/bin/python office/run.py --providers
```

### Free-tier realities and the guards built for them

- **~8,000 tokens per minute per model** is the binding Groq limit, not the request count. The runtime
  trims old tool results before every call, parses every wait format Groq returns, keeps a cooldown per
  model, and finishes on local Ollama after six limit hits in one run.
- **Small models fabricate.** Seen twice: skills added to a CV, and a "file saved" that was never written.
  Guards: `cv_truth_check` flags anything not in the master CV, and the runtime compares an agent's
  final answer against the tools it actually called and sends it back once if it claims an action it
  did not perform.
- **One run at a time** through the scheduler. Parallel runs just trip the per-minute limit faster.

Nothing is ever submitted, sent, posted, or paid by an agent. They prepare and
call `request_approval`; you act.

---

# The brain in detail

Everything runs on your own machine. No API keys, no quotas, no monthly fee.
The only download is a 130 MB embedding model, fetched once on first use.

## What the brain does

| Tool            | What it's for                                                            |
| --------------- | ------------------------------------------------------------------------ |
| `remember`      | Store one fact / decision / task / lesson with tags, importance, scope   |
| `recall`        | Search by meaning **and** keywords. Boosts important and recent items    |
| `update_memory` | Fix or enrich a memory instead of storing a conflicting copy             |
| `forget`        | Delete a memory                                                          |
| `recent`        | Newest memories, for a quick catch-up at the start of a shift            |
| `activity`      | Who did what in the brain (remember / recall / update / forget)          |
| `brain_stats`   | Counts per agent, kind, namespace; database size                         |
| `reindex`       | Embed older memories after enabling semantic search                      |

Under the hood: SQLite (unlimited rows, one file) + FTS5 keyword index +
local vector embeddings (`BAAI/bge-small-en-v1.5` via fastembed, CPU only).
Results from both indexes are fused, then nudged by importance and recency.

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Try it from the terminal

```bash
.venv/bin/python brain/cli.py remember "Client prefers blue for all brand assets" --agent lead-creative --kind decision --tags client,branding --importance 5
.venv/bin/python brain/cli.py recall "what colour scheme should I use"
.venv/bin/python brain/cli.py recent
.venv/bin/python brain/cli.py stats
```

## Plug it into agents

**Claude Code** picks it up automatically from `.mcp.json` in this folder.
Open this folder in Claude Code and the `brain` tools appear.

**Claude Desktop / any MCP client**: add to the client's config

```json
{
  "mcpServers": {
    "brain": {
      "command": "/ABSOLUTE/PATH/TO/.venv/bin/python",
      "args": ["/ABSOLUTE/PATH/TO/brain/server.py"]
    }
  }
}
```

Every agent gets the same database, so one agent's `remember` is instantly
visible to every other agent's `recall`.

## How agents should use it

Put this in each agent's brief:

> Before starting a task, call `recall` with a short description of what you
> are about to do. After you finish or learn something another agent might
> need, call `remember`. One idea per memory. Always pass your agent name.

Use `namespace` to keep projects apart (`"client-acme"`, `"internal"`), and
`ttl_hours` for temporary state like "I'm working on X right now".

## Configuration

| Env var             | Default                      | Purpose                         |
| ------------------- | ---------------------------- | ------------------------------- |
| `BRAIN_DB`          | `brain/data/brain.db`        | Where the database lives        |
| `BRAIN_EMBED_MODEL` | `BAAI/bge-small-en-v1.5`     | Any fastembed-supported model   |

Back up the brain by copying `brain/data/brain.db`.

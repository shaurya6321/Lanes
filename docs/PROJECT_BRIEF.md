# Lanes — Project Brief

> **Shared plan, separate lanes.** A coordination layer that lets 2–6 people each run their own coding agent (Claude Code or OpenAI Codex) on their own machine (macOS or Windows, in Cursor or VS Code), share one plan and one memory for a repo, and build in parallel without colliding.

Prepared: November 5, 2026 · Owner: Shaurya (GitHub: `shaurya6321`) · Status: pre-Phase 0

---

## 1. Name

**Recommended: `Lanes`** (repo: `shaurya6321/Lanes`, CLI: `lanes`)

Why: the core idea is that every teammate's Claude works in its own lane (owned files, owned task) while seeing the whole road (shared plan, notices, memory). It is short, describes the method, and works as a CLI name.

| Option | Why it fits | Downside |
|---|---|---|
| **Lanes** (recommended) | Matches the method: owned lanes + shared plan | Generic word; check GitHub/npm availability |
| Baton | Handoffs are a first-class feature | Undersells parallel work |
| Huddle | Team-sync feel | Sounds like a chat app |
| Relay | Notices passed between teammates | Many existing projects use it |

Before committing: search GitHub, npm, and PyPI for the name. If taken, use `lanes-dev` or `lanesync`. Avoid putting "Claude" in the project name so the tool stays agent-neutral and you don't lean on Anthropic's brand.

---

## 2. What we are building

**Problem.** When two people run Claude Code on the same repo at the same time:

- each Claude has no idea what the other is doing
- they overwrite or break each other's work
- handoffs require re-explaining everything

**Solution.** A thin layer that gives every Claude session the same picture:

1. **One shared plan** that splits a feature into ranked tasks. Each task has an owner, owned files, and the interface contracts it must respect.
2. **Automatic context.** At session start, Claude is told who is doing what, what changed, and which notices and handoffs are waiting.
3. **Lane guard.** Before Claude edits a file outside its lane, a hook stops it and tells it to ask the owner instead.
4. **Change notices.** When a contract or shared "hub" file changes, a short notice goes to teammates whose tasks depend on it. Notices flow one way only, from lower rank to higher rank.
5. **Ordered integration.** Merge in plan order, use a syntax-aware merge driver, and run the combined test suite.
6. **Handoffs and memory.** Session summaries and decisions persist for the next session, whoever starts it.

### Goals
- Works the same in Cursor and VS Code, since Claude Code runs in the terminal of both.
- Agent-neutral core: Claude Code first, OpenAI Codex through an adapter (section 3b).
- Runs on macOS and Windows; no bash-only scripts.
- Teams of 2–6 people, each on their own machine.
- Open source; self-hostable for $0–10/month in infrastructure.
- Parallel work on different tasks with near-zero collisions.
- Clean handoffs with no re-explaining.

### Non-goals (v1)
- No live keystroke co-editing by agents. Research shows it causes semantic conflicts and lower quality (see section 3).
- No fork of Cursor or VS Code.
- No raw chat-transcript sharing. Short summaries only.
- No enterprise features (SSO, admin).

---

## 3. Research basis (why the design looks like this)

| Finding | Source | What we do about it |
|---|---|---|
| Patches that each pass alone can fail when merged, even with no textual conflict. On constructed Django tasks, interference hit 97% of runs; a short message describing the other change recovered 82% (98% in synthetic tests, with about 130 tokens). | [STALE benchmark, arXiv 2609.25396](https://arxiv.org/pdf/2609.25396) | **Contracts first** plus **short change notices** |
| Splitting work by cohesion (keep coupled files together, isolate hub files) beat file-by-file parallelism and Claude Code Agent Teams: up to +14% pass rate, 2.1× speed, 35% lower cost. | [Co-Coder, arXiv 2606.00953](https://arxiv.org/html/2606.00953v1) | **Cohesion planner**; hub files get one owner |
| Locks and abort-retry waste agent work (2PL deadlocks, OCC costs 1.83× tokens). Notifying the agent works better, and notices must flow one way (fixed order) or agents ping-pong forever. | [CoAgent, arXiv 2606.15376](https://arxiv.org/html/2606.15376v1) | **Ranked tasks; notices only flow low to high rank** |
| CRDT co-editing between agents: zero merge failures but 5–10% semantic conflicts and −7.7% code quality; best at 3–5 agents on loosely coupled work. | [CodeCRDT, arXiv 2510.18893](https://www.arxiv.org/pdf/2510.18893) | Live co-editing is **humans-only, optional** |
| 27.67% of 107K+ AI-agent PRs had merge conflicts. | [AgenticFlict dataset](https://zenodo.org/records/20118379) | Syntax-aware merge plus ordered integration |
| Claude Code Agent Teams stores team state locally under `~/.claude/teams/`, so it coordinates sessions on one machine, not across laptops. | [Agent Teams notes](https://skills.sh/croakingtoad/skeeter-skills/claude-code-agent-teams) | Our layer handles the cross-machine part |

---

## 3b. Agent and platform support

### Claude Code and OpenAI Codex

**Yes, Lanes can support both.** The core (plan, notices, summaries, CLI) is plain files plus a Python CLI, so it does not care which agent is running. Each agent then plugs in through three standard surfaces:

| Surface | Claude Code | OpenAI Codex CLI | Lanes approach |
|---|---|---|---|
| Instructions file | `CLAUDE.md` | `AGENTS.md` | Generate both from one template |
| MCP servers (Agent Mail) | `.mcp.json` | `.codex/config.toml` (`[mcp_servers]`), project-level supported | Configure both |
| Hooks | `.claude/settings.json` | `.codex/hooks.json`; SessionStart, PreToolUse, PostToolUse, UserPromptSubmit, Stop | Same Python scripts; a small adapter normalizes the JSON payload |

**Codex caveats to plan for:**
- Codex PreToolUse hooks can **deny** but not allow or ask; the deny reason is fed back to the model. That is enough for the lane guard.
- As of April 2026, Codex PreToolUse fired only on Bash tool calls, not on its file-patch edits. If that is still true, the lane guard can't stop a Codex file edit before it happens.
- **Fallback that works for any agent:** a git pre-commit hook (`lanes check --staged`) that blocks commits touching files outside your lane. MCP Agent Mail ships a similar pre-commit guard for reserved files.
- Codex hook timeouts are in seconds (Claude Code uses milliseconds), and payload field names differ slightly. The adapter handles this.

**Plan:** Phase 0 targets Claude Code. Add the Codex adapter in Phase 1 once the core works. Mixed teams (one person on Claude Code, one on Codex) then share the same `.lanes/` state.

### macOS and Windows

| Piece | macOS | Windows | Notes |
|---|---|---|---|
| Claude Code | Yes | Yes, native (`winget install Anthropic.ClaudeCode` or the PowerShell installer) | Install Git for Windows too; Claude Code uses it |
| Codex | Yes | Yes (CLI; Codex Desktop app on macOS and Windows) | |
| Lanes hooks + CLI | Yes | Yes | **Python only, no bash scripts.** Hooks are called as `uv run python hooks/x.py` so the same config works on both |
| Tailscale | Yes | Yes | |
| MCP Agent Mail (server) | Yes | Not confirmed | The Rust version lists Linux and macOS. **Host the server on the Mac or a Linux VPS**; Windows only needs to connect as a client over HTTP |
| Beads, Mergiraf | Check install docs | Check install docs | Verify Windows install before Phase 1/3 |

**Cross-platform rules for the codebase:**
- Normalize all paths to forward slashes before matching globs (`pathlib.PurePosixPath`).
- Use `pathlib` everywhere; never hard-code `/` or `\`.
- Commit `.gitattributes` with `* text=auto eol=lf` so line endings don't create fake diffs between Mac and Windows.
- Test every hook on both machines before each phase gate.

---

## 4. Architecture

```
 Teammate A (Cursor)                      Teammate B (VS Code)
 ┌───────────────────────┐                ┌───────────────────────┐
 │ Claude Code           │                │ Claude Code           │
 │  ├─ SessionStart hook │──context──┐┌───│  ├─ SessionStart hook │
 │  ├─ PreToolUse guard  │           ││   │  ├─ PreToolUse guard  │
 │  ├─ PostToolUse notice│──notice──►││◄──│  ├─ PostToolUse notice│
 │  └─ Stop summary      │──summary─►││   │  └─ Stop summary      │
 └──────────┬────────────┘           ││   └──────────┬────────────┘
            │ git push/pull          ▼▼              │ git push/pull
            │              ┌──────────────────┐      │
            │              │ Coordination     │      │
            │              │ (Phase 0: git    │      │
            │              │  files; Phase 1: │      │
            │              │  Agent Mail over │      │
            │              │  Tailscale)      │      │
            │              └──────────────────┘      │
            ▼                                        ▼
 ┌───────────────────────────────────────────────────────────┐
 │ Git repo: CLAUDE.md · .lanes/plan.yaml · .lanes/contracts │
 │ .lanes/notices · .lanes/handoffs · .lanes/decisions.md    │
 └───────────────────────────────────────────────────────────┘
```

### Reuse vs build

| Component | Reuse or build | Notes |
|---|---|---|
| Messaging, identities, advisory file leases, pre-commit guard | **Reuse:** [MCP Agent Mail](https://github.com/dicklesworthstone/mcp_agent_mail) | HTTP server backed by Git + SQLite. Default runs locally (port 8765); share it with the team over Tailscale. |
| Task graph synced across machines, atomic claims | **Reuse:** [Beads](https://github.com/steveyegge/beads) (`bd`) | Git-backed; hash IDs avoid merge collisions |
| Syntax-aware merging | **Reuse:** [Mergiraf](https://mergiraf.org/) | Git merge driver |
| Live human pair-editing (optional) | **Reuse:** [Open Collaboration Tools](https://www.open-collab.tools/) | Extension on VS Code Marketplace and Open VSX, which Cursor uses |
| Plan format + cohesion planner | **Build** | `/lanes-plan` slash command + script |
| Lane guard, context injection, summaries | **Build** | Claude Code hooks |
| Change notices (one-way, by rank) | **Build** | Core differentiator |
| Integration checker | **Build** | Merge in rank order, run combined tests |

Check each reused tool's license before bundling or depending on it in an open-source release.

---

## 5. Repo structure (target)

```
lanes/
├── README.md
├── LICENSE                      # MIT recommended
├── CLAUDE.md                    # instructions every Claude session reads
├── AGENTS.md                    # same instructions for Codex (generated from one template)
├── .gitattributes               # * text=auto eol=lf (Mac/Windows line endings)
├── .codex/                      # Phase 1: Codex adapter
│   ├── config.toml              # MCP servers for Codex
│   └── hooks.json               # same hook scripts, Codex event config
├── docs/
│   ├── PROJECT_BRIEF.md         # this file
│   ├── PLAN_FORMAT.md           # spec for .lanes/plan.yaml
│   └── SETUP.md                 # teammate onboarding
├── .claude/
│   ├── settings.json            # project hooks (committed)
│   └── commands/
│       ├── lanes-plan.md        # /lanes-plan: draft plan + contracts
│       ├── lanes-status.md      # /lanes-status: who is doing what
│       ├── lanes-handoff.md     # /lanes-handoff: write handoff note
│       └── lanes-integrate.md   # /lanes-integrate: ordered merge + tests
├── hooks/
│   ├── session_start.py         # inject plan, my task, unread notices, handoffs
│   ├── pre_tool_guard.py        # block edits outside my lane
│   ├── post_tool_notice.py      # contract/hub edits → write notice
│   ├── stop_summary.py          # append 3–5 line session summary
│   ├── adapters.py              # normalize Claude Code vs Codex hook payloads
│   └── pre_commit.py            # agent-neutral lane check on staged files (any agent, any OS)
├── lanes/                       # Python package for the CLI
│   ├── cli.py                   # lanes init | status | whoami | notices | integrate
│   ├── plan.py                  # load/validate plan.yaml, glob ownership
│   ├── notices.py
│   └── identity.py              # who am I (env LANES_USER or git user.email)
├── tests/
└── .lanes/                      # created by `lanes init` in a target repo
    ├── plan.yaml
    ├── contracts/
    ├── notices/
    ├── handoffs/
    ├── summaries/
    └── decisions.md
```

**Stack recommendation:** Python 3.11+ with `uv`. Hooks are short scripts, Agent Mail is Python, and Python is your strongest language. Hooks must use only the standard library plus PyYAML, so they start fast.

---

## 6. Plan format (`.lanes/plan.yaml`)

```yaml
feature: checkout-v1
updated: 2026-11-05
members:
  - id: shaurya
    email: shaurya@example.com
  - id: friend
    email: friend@example.com
hub_files:            # shared files with exactly one owner
  - path: package.json
    owner: shaurya
  - path: src/types/**
    owner: shaurya
contracts:
  - id: cart-api
    file: .lanes/contracts/cart-api.md
    owner: shaurya
tasks:
  - id: T1
    title: Cart API + types
    rank: 1            # lower rank = upstream; notices flow 1 → 2 → 3
    owner: shaurya
    owns: ["src/api/cart/**", "src/types/**"]
    implements: [cart-api]
    depends_on: []
    status: in_progress
  - id: T2
    title: Checkout page UI
    rank: 2
    owner: friend
    owns: ["src/pages/checkout/**", "src/components/checkout/**"]
    uses: [cart-api]
    depends_on: [T1]
    status: todo
```

**Rules**
- Every file a task writes must match its `owns` globs. Anything else is a hub file or another owner's file.
- A contract is changed only by its owner. Every change creates a notice for tasks that `use` it and have a higher rank.
- Merge order equals rank order.

---

## 7. Setup checklist

### Both teammates (each machine)
- [ ] Your existing AI subscription with Claude Code (and/or Codex) access
- [ ] Install Claude Code ([official docs](https://docs.claude.com/en/docs/claude-code/overview)); confirm with `claude --version`
  - macOS: official installer or npm
  - Windows: `winget install Anthropic.ClaudeCode` (or `irm https://claude.ai/install.ps1 | iex`), plus **Git for Windows**
- [ ] Optional: Codex CLI, if a teammate prefers it (adapter arrives in Phase 1)
- [ ] Editor: Cursor (you) or VS Code (friend); run the agent in the integrated terminal
- [ ] Git + GitHub account; friend added as collaborator on `shaurya6321/Lanes`
- [ ] Python 3.11+ and [`uv`](https://docs.astral.sh/uv/) (works on macOS and Windows)
- [ ] Node.js LTS (needed for `npx` tools and the Beads npm package)
- [ ] Tailscale (Phase 1+), both logged into the same tailnet
- [ ] Set identity:
  - macOS (zsh): add `export LANES_USER=shaurya` to `~/.zshrc`
  - Windows (PowerShell): `setx LANES_USER friend` (then open a new terminal)

### Phase 1 additions
- [ ] Beads: `npm install -g @beads/bd` (or Homebrew), then `bd init` in the repo
- [ ] MCP Agent Mail: install per its README on **one** always-on machine: the Mac or a small Linux VPS, not the Windows laptop. Expose it only over Tailscale, not the public internet.
- [ ] Register Agent Mail as an MCP server in `.mcp.json` (Claude Code) and `.codex/config.toml` (Codex) so every agent sees it

### Phase 3 additions
- [ ] Mergiraf (install per mergiraf.org), then add it to `.gitattributes`
- [ ] Optional: Open Collaboration Tools extension (Open VSX / VS Code Marketplace) for human pair mode

### Repo hygiene
- [ ] `.gitignore`: `.env`, `.lanes/local/`, `__pycache__/`, `.venv/`
- [ ] Never commit API keys. Hooks must refuse to write anything matching secret patterns into notices or summaries.

---

## 8. Phases and test gates

| Phase | Time | Build | Gate (both of you test it) |
|---|---|---|---|
| **0. Prove it with files** | 3–5 days | `CLAUDE.md`, `plan.yaml` format, the 4 hooks reading/writing `.lanes/` files, synced via git | Build one small feature split in two; zero overwrites; a fresh session can say what the other did without being told |
| **1. Shared coordination** | 1–2 weeks | Agent Mail over Tailscale for notices and leases; Beads for tasks; `lanes` CLI | Notices arrive within a minute without a git pull; claims are atomic |
| **2. Planner** | 1 week | `/lanes-plan`: Claude drafts tasks + owners + contracts from a feature description, using imports to group coupled files and flag hub files | The generated plan needs only minor edits for a 3–4 task feature |
| **3. Integration** | 1 week | `/lanes-integrate`: merge in rank order, Mergiraf, run each branch's tests and the combined suite | A 3–4 task feature merges cleanly in one pass |
| **4. Team-ready + open source** | 1–2 weeks | `lanes init`, docs, demo GIF, CI, test with 2–4 extra people | A newcomer sets it up alone in under 30 minutes |

---

## 9. Costs (server and infrastructure only)

AI subscriptions are **not counted**: each teammate brings the one they already have. Prices checked November 2026; verify before paying.

### What actually needs to run
Lanes is light. The only always-on piece is the coordination server (MCP Agent Mail: a small Python/Rust HTTP service with SQLite + Git storage). It needs well under 1 vCPU and 1 GB RAM for a 2–6 person team. Everything else (hooks, CLI, Beads, Mergiraf) runs on each laptop for free.

### Cost by phase
| Phase | What runs | Cost |
|---|---|---|
| 0. Files in git | Nothing extra; state lives in the repo | **$0** |
| 1–3. Coordination server | Agent Mail + private network | **$0–10/month** (options below) |
| 4. Open-source release | GitHub repo, CI, docs | **$0** |

### Server options (pick one)
| Option | Monthly cost | Pros | Cons |
|---|---|---|---|
| **A. Host on the Mac + Tailscale** (recommended to start) | **$0** | No setup cost; Tailscale Personal is free for up to 6 users, non-commercial | Server is down when that Mac sleeps or is closed |
| **B. Railway Hobby** | **$5** (includes $5 of usage) | Always on; deploy from GitHub | Usage above the included $5 is metered; budget $5–10 |
| **C. Small Linux VPS (e.g., Hetzner)** | **~€4–6** | Always on; full control; can join the tailnet | You patch and maintain it; Hetzner raised prices in April 2026 and some of its cheapest plans weren't orderable in fall 2026 |
| **D. Azure with Student Pack credit** | **$0 out of pocket** while the $100 credit lasts | Always on; free to you for months | Credit runs out; set a spending alert |

The DigitalOcean $200 student credit is no longer available; that offer ended July 31, 2026.

### Everything else
| Item | Cost | Notes |
|---|---|---|
| Private network (Tailscale) | $0 | Personal plan: up to 6 users, unlimited devices, non-commercial. Business plans start at $8/user/month if this ever becomes commercial |
| GitHub repo, PRs | $0 | You already have GitHub Pro via the Student Pack |
| Open-source tools (Agent Mail, Beads, Mergiraf, Open Collaboration Tools) | $0 | Check licenses before bundling |
| Domain name | $0 (optional) | Not needed with Tailscale; the Student Pack includes a free domain if you want a docs site later |
| Editors | $0 | VS Code is free; Cursor's paid plan isn't required to run Claude Code or Codex in its terminal |

### Bottom line
| Setup | Monthly infra cost |
|---|---|
| Phase 0, or server on the Mac + Tailscale | **$0** |
| Always-on with Azure student credit | **$0 out of pocket** (until credit is used) |
| Always-on with Railway | **~$5–10** |
| Always-on with a small VPS | **~€4–6** |

Scaling from 2 to 6 people does not change these numbers: the same small server and the free Tailscale plan cover up to 6 users.

**Recommendation:** run Phase 0 and Phase 1 at $0 (Mac + Tailscale). Move to an always-on option only if "server is asleep" becomes a real problem; try the Azure credit first, then Railway.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| Tasks aren't truly independent | Contracts first; planner groups coupled files; hub files get one owner |
| Stale plan | `lanes status` warns when a task edits files outside its globs; plan updates require a notice |
| Context bloat from summaries | 3–5 lines each; inject only the last 24h plus unread notices; cap at ~1,500 tokens |
| Secrets leak into notices or summaries | Secret-pattern filter in hooks; never read `.env` |
| Hook format changes in Claude Code updates | Pin a tested Claude Code version in docs; verify hooks with `/hooks` after updates |
| Cursor extension differences (pair mode) | Test the Open Collaboration Tools install in Cursor early |
| Livelock (two Claudes reacting to each other) | Notices only flow from lower to higher rank |
| Codex hooks don't see file edits | Git pre-commit lane check as the agent-neutral backstop; re-check Codex hook docs before Phase 1 |
| Windows-only breakage (paths, line endings, shell) | Python-only hooks, PurePosixPath normalization, `.gitattributes`; test both OSes at every gate |
| Server down when the host Mac sleeps | Accept in Phases 0–1; move to Azure credit or Railway if it becomes a problem |

---

## 11. Claude Code kickoff prompt

**How to use:** create the empty repo, put this file at `docs/PROJECT_BRIEF.md`, open the folder in Cursor, run `claude` in the terminal, and paste everything inside the box below.

````text
You are the lead engineer on "Lanes", an open-source coordination layer that lets 2–6
people each run their own coding agent (Claude Code now, OpenAI Codex later) on their
own machine (macOS or Windows; Cursor or VS Code) against the same repo, with one
shared plan, automatic shared context, lane ownership, one-way change notices, and
ordered integration.

PLATFORM AND AGENT REQUIREMENTS (apply to everything you write)
- Must run on macOS AND Windows. Write all hooks and tooling in Python; no bash or
  PowerShell scripts. Register hooks as `uv run python hooks/<name>.py` so the same
  config works on both OSes.
- Use pathlib; normalize every path to forward slashes (PurePosixPath) before glob
  matching. Add .gitattributes with `* text=auto eol=lf`.
- Keep the core agent-neutral: hook scripts read the payload through
  hooks/adapters.py, which today handles Claude Code and has a clearly marked stub
  for Codex. Do not build the Codex adapter yet; list it in docs/BACKLOG.md.
- Generate both CLAUDE.md and AGENTS.md from one template
  (templates/agent_instructions.md) so the two never drift.

READ FIRST
1. Read docs/PROJECT_BRIEF.md fully. It is the source of truth for goals, non-goals,
   architecture, plan format, phases, and gates. Do not invent scope beyond it.
2. Before writing any hook, check the CURRENT Claude Code hooks documentation
   (https://docs.claude.com/en/docs/claude-code/hooks) for the exact stdin JSON fields,
   output JSON format, matcher syntax, and exit-code semantics for SessionStart,
   PreToolUse, PostToolUse, and Stop. Do not rely on memory for these formats.
   Summarize what you found in docs/HOOKS_NOTES.md with the doc URL and date.

SCOPE FOR THIS SESSION: PHASE 0 ONLY
Build the file-based version (no servers, no Agent Mail, no Beads yet):

A. Project skeleton
   - pyproject.toml (Python 3.11+, managed with uv), MIT LICENSE, README.md with a
     30-second explanation and a quickstart, .gitignore (.env, .venv, __pycache__,
     .lanes/local/).
   - Package `lanes/` with: identity.py (who am I: env LANES_USER, else git
     user.email mapped via plan.yaml members), plan.py (load and validate
     .lanes/plan.yaml per section 6 of the brief; glob ownership matching; rank
     lookup; hub-file lookup), notices.py (write/read/mark-read notices as markdown
     files with YAML front matter: id, from_task, from_rank, to_tasks, contract or
     file, created, summary), cli.py with commands:
       lanes init       -> create .lanes/ tree with an example plan.yaml and
                           templates (contracts/, notices/, handoffs/, summaries/,
                           decisions.md)
       lanes whoami     -> my member id, my tasks, my owned globs
       lanes status     -> table of tasks, owners, status, unread notices per person
       lanes check PATH -> exit 0 if PATH is in my lane, 2 otherwise, with reason
       lanes notices    -> list unread notices for me; --mark-read
   - docs/PLAN_FORMAT.md documenting the plan schema and the rules.

B. Hooks (scripts in hooks/, registered in .claude/settings.json)
   1. session_start.py (SessionStart): inject a compact briefing into Claude's
      context: feature name, my tasks + owned globs + contracts I implement/use,
      other members' active tasks (one line each), unread notices addressed to me,
      latest handoff addressed to my tasks, last 24h of summaries (max 5 lines each).
      Hard cap the briefing at ~1,500 tokens; truncate oldest first.
   2. pre_tool_guard.py (PreToolUse on file-writing tools such as Edit, Write,
      MultiEdit, NotebookEdit; confirm exact tool names from the docs):
      - allow if the target path matches one of my tasks' `owns` globs
      - if it is a hub file or another member's file: deny, with a reason shown to
        Claude telling it which owner to ask and to write a request in
        .lanes/notices/ via `lanes` instead of editing
      - always allow writes inside .lanes/ (notices, handoffs, summaries)
      - if plan.yaml is missing or invalid, allow but print a warning (fail open in
        Phase 0, so a broken plan never bricks someone's session)
   3. post_tool_notice.py (PostToolUse on the same tools): if the edited file is a
      contract file or a hub file that I own, create a notice addressed ONLY to
      tasks with a HIGHER rank that `use` that contract or depend on my task. Never
      send notices to lower-rank tasks (this prevents ping-pong livelock). Notice
      body: 3–6 lines describing what changed (symbols renamed, args added, types
      changed), under ~150 tokens.
   4. stop_summary.py (Stop): append a 3–5 line summary for this session to
      .lanes/summaries/<member>-<YYYY-MM-DD>.md: task id, what changed, files
      touched, open questions. Keep it deterministic: derive files touched from
      `git diff --name-only` and ask Claude only for the 1–2 line "why".
      If the docs show a Stop hook cannot easily get a model-written summary,
      write the deterministic part and add a TODO.
   5. pre_commit.py (git pre-commit hook, installed by `lanes init`): block commits
      that stage files outside the committer's lane, with the same message as the
      guard. This is the agent-neutral safety net (it also covers Codex, whose
      PreToolUse may not see file edits).
   - All hooks: stdlib + PyYAML only, start in under 300 ms, never print secrets.
     Before writing any notice or summary, redact values matching common secret
     patterns (API keys, tokens, private keys, .env lines). Never read .env files.

C. CLAUDE.md for repos that use Lanes
   Write a template CLAUDE.md that tells any Claude session:
   - read the session briefing; stay inside your lane
   - if you need to change something outside your lane, write a request notice to
     the owner and continue with what you can do
   - if you change a contract you own, keep the notice short and precise
   - before stopping, make sure the summary reflects what you did
   - run `lanes status` when unsure who owns what

D. Slash commands in .claude/commands/
   - lanes-status.md: run `lanes status` and explain it briefly
   - lanes-handoff.md: write .lanes/handoffs/<task>-<timestamp>.md with: state,
     next step, failing tests, gotchas
   (The planner and integrator come in Phases 2–3; do not build them now.)

E. Tests
   - pytest tests for plan validation, glob ownership, rank-filtered notice
     routing (verify a rank-2 edit never notifies rank-1), secret redaction, and
     each hook given sample stdin JSON (use fixtures shaped exactly as the docs
     specify).
   - A tests/e2e_phase0.md manual script the two teammates follow: clone, set
     LANES_USER, open sessions on both machines, try an out-of-lane edit, change a
     contract, confirm the other side's next session shows the notice.

WORKING RULES
- First, show me a short plan (files you'll create, in order) and wait for my OK.
- Work in small steps; after each step run the tests and commit with a clear
  message. Do not push without asking.
- Ask before installing any global tool or adding any dependency beyond PyYAML,
  pytest, and a CLI library (typer or argparse).
- Keep hooks simple and readable; prefer clear code over clever code.
- Do not build Phase 1+ features (servers, Agent Mail, Beads, Tailscale, planner,
  CRDT/live editing). If something seems needed, add it to docs/BACKLOG.md.
- If any detail in the brief conflicts with the current Claude Code docs, follow
  the docs, note the conflict in docs/HOOKS_NOTES.md, and tell me.

DONE MEANS
- `uv run pytest` passes (tests must include Windows-style paths like
  `src\api\cart\x.py` resolving to the right lane).
- `lanes init` in a fresh test repo creates a working .lanes/ setup.
- In a live Claude Code session: the briefing appears at start; an out-of-lane edit
  is blocked with a helpful reason; editing a contract creates a notice only for
  higher-rank tasks; a summary file appears after the session.
- README quickstart works copy-pasted on a clean machine.
Report what you verified, what you could not verify, and the exact steps for my
teammate to set up on their machine.
````

---

## 12. Kickoff checklist (this week)

- [ ] Pick the final name and create the GitHub repo
- [ ] Both: Claude Code installed (Mac: official installer; Windows: winget + Git for Windows); editor ready
- [ ] Add this file as `docs/PROJECT_BRIEF.md`; commit
- [ ] Run the kickoff prompt; review Claude's plan before it builds
- [ ] Agree who owns what in the Lanes codebase itself (eat your own dog food: write a `.lanes/plan.yaml` for building Lanes)
- [ ] After Phase 0 gate: 15-minute review, then decide on Phase 1

---

## Sources

- [Passes Alone, Fails Together (STALE)](https://arxiv.org/pdf/2609.25396)
- [Co-Coder: Cohesion-Aware Task Partitioning](https://arxiv.org/html/2606.00953v1)
- [CoAgent: Concurrency Control for Multi-Agent Systems](https://arxiv.org/html/2606.15376v1)
- [CodeCRDT](https://www.arxiv.org/pdf/2510.18893)
- [AgenticFlict dataset](https://zenodo.org/records/20118379)
- [MCP Agent Mail](https://github.com/dicklesworthstone/mcp_agent_mail) · [Rust version](https://github.com/Dicklesworthstone/mcp_agent_mail_rust)
- [Beads](https://github.com/steveyegge/beads)
- [Mergiraf](https://mergiraf.org/)
- [Open Collaboration Tools](https://typefox.io/blog/open-collaboration-tools-announcement)
- [Claude Code hooks reference](https://docs.claude.com/en/docs/claude-code/hooks)
- [Codex CLI hooks guide](https://codex.danielvaughan.com/2026/04/15/codex-cli-hooks-complete-guide-events-policy-patterns/)
- [Codex CLI MCP integration](https://codex.danielvaughan.com/2026/03/26/codex-cli-mcp-integration/)
- [Codex hook events list (promptconduit PR)](https://github.com/promptconduit/cli/pull/51)
- [Codex PreToolUse Bash-only note (squeez adapter)](https://docs.rs/crate/squeez/1.6.1/source/src/hosts/codex.rs)
- [Claude Code on Windows](https://www.codeagentswarm.com/en/guides/claude-code-on-windows)
- [Claude Code Windows install paths](https://claw.aguidetocloud.com/anthropic/claude-code/install-windows/)
- [Railway pricing](https://livemy.app/blog/railway-pricing)
- [Hetzner 2026 price changes](https://learnwithhasan.com/self-hosting-hub/vps-providers/hetzner/)
- [Hetzner plan availability, Oct 2026](https://www.bitdoze.com/md/es/hetzner-cloud-precios-2026.md)
- [Tailscale business pricing](https://cipherssecurity.com/?p=18414)
- [Tailscale free plan](https://www.ssdnodes.com/learn/is-tailscale-free-plan-limits)
- [GitHub Student Pack 2026 (DigitalOcean exit)](https://capitalandcompute.net/blog/github-student-developer-pack-2026/)

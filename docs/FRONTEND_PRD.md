# opposable Web UI — Frontend PRD

**Goal:** a Manus-style web interface for the existing `opposable` agent engine. Three-zone layout — session sidebar, chat stream, "opposable's computer" panel — with live streaming, step replay, and deliverable viewing. The Python core stays zero-dependency; the frontend is a static SPA served by a stdlib HTTP server.

**Non-goals (v1):** auth/multi-user, cloud deploy, VNC/live-browser streaming (we have no CDP browser tool yet), mobile apps, scheduled tasks, multi-agent "wide research".

---

## 1. Reference: what Manus' UI actually is

From published reviews, walkthroughs, and the ai-manus open-source clone:

- **Three-zone layout.** A collapsible **left rail** listing all tasks/sessions; a **center chat panel** where you talk to the agent, ChatGPT-style; and a **right panel — "Manus's Computer"** — showing what the agent is doing right now (terminal output, pages it's reading, files it's editing).
- **The computer panel is the signature element.** Header reads "*Manus is using Terminal / Browser / Editor*" with a one-line subtitle of the current action. The body switches renderer by tool type. A footer carries **step navigation (◀ ▶ + a scrub slider + "live" button)** so you can roll back through every step of the session, plus a **task-progress widget** ("3 / 7") expanding to the checklist.
- **Chat stream shows activity, not just text.** Agent messages are interleaved with compact **action chips** ("Executing command `pip install…`", "Browsing example.com") that give a human-like sense of activity; clicking a chip focuses the computer panel on that step's observation.
- **Plan visibility.** The agent's todo checklist is surfaced as a progress indicator; steps check off as it works.
- **Completion card.** On finish: a summary message plus **deliverable file cards** (view / download), and a "view all files in this task" affordance.
- **Replay & share.** Every session is replayable after the fact — scrub the timeline, watch each step. (Share links are out of scope for v1; local replay is in.)
- **Home screen.** Centered greeting ("Hello — what can I do for you?"), one large rounded composer with attach/submit, and suggested-task chips below, grouped by category tabs.
- **Controls.** Stop/interrupt mid-task; send follow-up guidance; dark + light themes.
- **Transport (from ai-manus).** Backend → frontend over **SSE**; REST for session CRUD and files.

Known criticism to design around: raw terminal spam intimidates non-technical users → default the computer panel to a summarized "follow" view with full raw output one click away.

## 2. Architecture

```
opposable/server.py   (stdlib only: ThreadingHTTPServer + SSE)
  POST /api/tasks                {task, model?, base_url?, sandbox?, max_iterations?} → {id}
  GET  /api/tasks                list sessions (scan .opposable-* state dirs)
  GET  /api/tasks/{id}           metadata + full event history (for replay/reload)
  GET  /api/tasks/{id}/events    SSE live stream
  POST /api/tasks/{id}/stop      cooperative stop flag checked each iteration
  POST /api/tasks/{id}/messages  follow-up guidance (appended as user event on next iteration)
  GET  /api/tasks/{id}/files     tree of sandbox workdir
  GET  /api/tasks/{id}/files/…   raw file content (view/download)
  GET  /*                        static SPA from web/dist

web/                  (Vite + React + TypeScript + Tailwind — npm deps live here only)
  builds → web/dist, served by server.py; `opposable serve` opens it
```

The `Agent` runs in a worker thread per task; `on_event` pushes onto a per-task queue drained by the SSE handler. Events are also appended to `events.jsonl` in the state dir so history survives restarts and powers replay.

### Event protocol (backend enablers — Phase 0)

Existing kinds stay; additions marked ★:

| kind | payload | UI rendering |
|---|---|---|
| `assistant` | `{text}` | chat bubble from agent |
| `tool` | `{name, args, step★}` | action chip in chat; sets computer-panel header |
| `observation` | `{name, text, step★}` — **full text, not 500-char cut★** | computer-panel body content |
| `plan` ★ | `{plan}` full todo.md after every `plan_update` | progress widget (n/m + checklist) |
| `compress` | `{evicted}` | dim system line in chat |
| `done` ★ | `{completed, summary, iterations, deliverables, usage}` | completion card + file chips |
| `status` ★ | `{state}` running / stopped / error | sidebar icons, header badge |

Tool-name prefix → renderer: `shell_` terminal (mono, exit-code badge, stderr tinted) · `file_` editor (path header, syntax highlight, diff-ish for writes) · `web_` reader (URL bar + extracted text) · `plan_` checklist · `task_` completion.

## 3. Design system

- **Type:** Inter (UI) / JetBrains Mono (terminal & code). Base 14px, generous line-height.
- **Palette:** neutral near-white light theme (`#fafaf9` bg, `#1c1917` text) and true dark (`#111110` bg, `#e7e5e4` text); hairline borders (`#e7e5e4` / `#2a2a28`); one accent used sparingly for actions/links (`#6d5df6` family); status green/amber/red for done/working/error only.
- **Shape:** rounded-2xl cards, rounded-xl chips/buttons; subtle shadows only on overlays.
- **Motion:** working-state shimmer on the active action chip; smooth auto-scroll with "jump to latest" pill when user scrolls up; no gratuitous animation.
- **Layout:** sidebar 260px (collapsible to 56px), chat flexible min 420px, computer panel 44% (collapsible; slide-over under 1100px viewport).

## 4. Screens & components

**A. App shell** — three columns, theme toggle, `opposable` wordmark. Sidebar: New task button, search filter, session list (title = first line of task, status icon: pulsing dot = working, check = complete, half = stopped), relative timestamps.

**B. Home (no session selected)** — centered greeting "What should opposable do?", large composer card (multiline, Enter submits, model/sandbox pickers as compact selects on the card's bottom rail), 6–8 suggested task chips under category tabs (Research, Code, Data, Files).

**C. Chat stream** — user bubbles right-aligned solid; agent text left, borderless on background; action chips (icon + verb + truncated arg + spinner→check); compress lines; error observations tinted amber with "TOOL ERROR" chip kept visible (principle 5: keep the wrong stuff in); completion card with summary md, iteration/token footer, deliverable chips → file viewer. Composer at bottom sends follow-up guidance; while running it shows Stop.

**D. Computer panel** — header "opposable is using **Terminal**" + subtitle (command/path/url); body = per-tool renderer (above); footer = step scrubber `◀ ▶ ——●—— [Live]` + progress widget "Task progress 3/7" expanding to checklist. Clicking any chat chip jumps the panel to that step and exits live-follow.

**E. Files drawer** — "All files in this task": tree from `/files`, text/image preview, download; deliverables pinned on top.

**F. Replay** — finished/stopped sessions load full history; scrubber replays steps; optional ▶ autoplay at ~2 steps/sec.

**G. Settings (modal)** — defaults for model, base URL, sandbox backend, max iterations, budget tokens; persisted to localStorage, sent per-task.

## 5. Implementation plan

Each step ends with: `git commit -m "feat: implemented <x>"`, a **scope check** (re-read this PRD section — did anything creep in/out?), and stated **verification**. Visual steps are verified by Playwright headless-Chromium screenshots (`web/e2e/snap.ts`, artifacts in `web/e2e/shots/`) reviewed before committing.

| # | Step | Verify |
|---|---|---|
| 0 | `server.py`: task registry, worker threads, SSE, REST, `events.jsonl`, event additions ★, `opposable serve` subcommand | `pytest tests/test_server.py` (stdlib client, scripted provider); curl SSE smoke |
| 1 | Scaffold `web/` (Vite+React+TS+Tailwind), dev proxy → :8734, build into `web/dist`, wire static serving | dev + built page loads; screenshot |
| 2 | Design tokens + app shell (3 cols, collapse, dark/light) | screenshots light/dark/collapsed |
| 3 | Sidebar sessions (list/create/select, status icons, search) | screenshot + live task appears |
| 4 | Home screen (greeting, composer, suggestion chips) | screenshot; submit creates task |
| 5 | Chat stream over SSE (bubbles, action chips, auto-scroll, compress lines, error tint) | run a real short task; screenshots during + after |
| 6 | Computer panel: header + terminal renderer + live follow | screenshot mid-`shell_exec` |
| 7 | Computer panel: editor + web-reader renderers | screenshots per renderer |
| 8 | Plan progress widget (n/m + checklist) | screenshot; checkbox states track todo.md |
| 9 | Step scrubber + replay of persisted sessions | replay a finished session; screenshots at 3 scrub points |
| 10 | Completion card + files drawer (preview/download, pinned deliverables) | run task producing report.md; open + download it |
| 11 | Controls: stop, follow-up messages, resume stopped session, status badges | stop mid-run; resume; screenshots |
| 12 | Settings modal + responsive/slide-over + polish pass | screenshots at 1440/1024/768; dark-mode sweep |
| 13 | E2E happy-path script (create → watch → complete → replay) as repeatable check | script green twice consecutively |

## 6. Acceptance criteria

1. `opposable serve` alone gives a working UI at localhost — no Node required at runtime.
2. A task submitted from Home streams visibly: chips appear per tool call, the computer panel follows live, plan progress updates, completion card shows deliverables that open.
3. Any past session can be reopened and scrubbed step-by-step.
4. Errors are visible, not hidden; stop works within one iteration.
5. Python core remains zero-dependency; all npm deps confined to `web/`.
6. Both themes pass a visual sweep; no layout break ≥ 768px wide.

# CUA-JEV

**A typed, verifiable Jev action router for hybrid Windows computer use.**

CUA-JEV is a working reference framework for bringing Jev into Windows computer use. It turns application
state into safe, typed action candidates, lets Jev choose both the next intent and execution channel, and
closes every step with guarded execution and independent verification.

## Project position

CUA-JEV is an **open reference architecture, capability-pack SDK and evaluation harness for hybrid Windows
computer use**. It is useful when an application task can expose structured state and several safe, typed ways to
reach the same subgoal—for example PyAutoGUI, DOM, COM, CLI, MCP or a filesystem API—and the developer wants
to build a Jev-powered CUA without first training a task-specific routing model.

The reusable output is not the four example workflows by themselves. The project provides:

- a common candidate, guard, executor, receipt and verifier contract across heterogeneous Windows channels;
- an action-space ablation (`Hybrid Action Space` versus `GUI Only`) that is independent of the decision
  policy;
- complete JSONL decision evidence and a read-only benchmark showcase;
- a benchmark contract for Jev, deterministic policies and external agents such as Codex;
- four executable capability-pack examples showing how to add a new application and independent terminal
  verifier.

The primary contribution is the runnable framework and four end-to-end examples. The secondary contribution
is the experimental surface used to derive data-backed insights about action-space routing. This release is
not evidence that Jev is already faster or more reliable for general computer use. Four frozen workflows
demonstrate feasibility. A publishable efficiency claim
requires parameterized task families, repeated held-out trials, a successful GUI-only ablation and measured
general-agent baselines under the same terminal verifiers. Until those results exist, treat the console as an
evidence surface and the capability interfaces as the main open-source contribution.

The distinctive hypothesis is **training-free action-space routing**. Many agent stacks collect tool-use
trajectories and then apply SFT, reinforcement learning or distillation to obtain a small routing policy.
CUA-JEV instead compiles the current structured state into a bounded set of legal, typed `intent × route`
candidates and asks the existing Jev decision model to select among them online. This does not remove the
engineering needed to build capability packs, but it avoids training a new router for every application and
makes every choice inspectable. The long-horizon suites are designed to test whether small per-step routing
advantages accumulate into meaningful end-to-end savings.

The first prototype deliberately uses **no VLM**. It combines structured observations from Edge DOM,
Windows UI Automation, Excel COM, VS Code/terminal text, filesystem APIs and MCP-shaped tools. In the
GUI-only profile, PyAutoGUI emits the real mouse and keyboard input while those structured interfaces
only observe, locate and verify state. Jev does not generate shell commands or scripts. It chooses one
complete, typed action candidate; a deterministic guard validates it, a channel executor runs it, and an
independent verifier checks the result.

```text
predefined task + structured observation
                    |
             candidate builder
                    |
        Jev Choice / rule baseline
                    |
              ActionGuard
                    |
    GUI | CLI | MCP | Script/API executor
                    |
          receipt + independent verifier
                    |
               JSONL trace
```

## What is implemented

The shared runtime is functional and covered by tests:

- closed-loop episodes with reset, re-observation, recent-action context and explicit termination reasons;
- deterministic stuck detection from repeated state fingerprints and repeated actions;
- dynamic observer and capability-pack registries rather than only hard-coded action lists;
- strict TypeSafe Jev `choice` client with response validation, retries and credential redaction;
- composite `ActionCandidate` objects across GUI, CLI, MCP, script/API and control channels;
- multiple executable routes for the same subgoal, so Jev chooses between real alternatives rather than
  differently worded placeholders;
- fail-closed guard for stale decisions, replay, path boundaries, writes and confirmation;
- unified action receipts, verifier registry and JSONL traces;
- deterministic rule policy for a no-key baseline and ablation experiments;
- content-addressed Jev record/replay and cache-only execution;
- repeated experiment summaries with channel counts, failure statuses and Wilson 95% intervals;
- four resettable end-to-end suites plus a reproducible multi-channel routing demo.

Initial capability adapters:

| Capability pack | Structured interface | first-release operations |
|---|---|---|
| Physical screen GUI | PyAutoGUI with UIA/DOM-assisted location | mouse movement, click, hotkey, typing, clipboard-safe text entry |
| Edge | Playwright observation over an isolated Edge session | public-site state snapshot, DOM location, independent predicates |
| Windows UI | UI Automation through pywinauto | top-level snapshot and semantic control location |
| Excel | COM through pywin32 plus direct workbook APIs | workbook snapshot, formula write, chart creation, independent COM verification |
| VS Code/Terminal | official `code` CLI, filesystem API, MCP and allowlisted argv templates | open/goto, test, exact-source repair |
| Filesystem/MCP | typed API, in-process tools and official MCP stdio transport | list, stat, read, copy, write, allowlisted tool call |

These adapters are intentionally narrow. They are an auditable base for predefined demos, not a claim of
general Windows autonomy.

## Quick start

Python 3.11+ is required. On Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,windows,browser,mcp]"
playwright install chromium
cua-jev doctor
pytest
python scripts/windows_smoke.py
```

For the local read-only project showcase:

```powershell
python -m pip install -e ".[dev,all,ui]"
$env:TYPESAFE_API_KEY = "your-key"  # omit when using the Rule baseline
cua-jev-ui
```

Open `http://127.0.0.1:8768`. The page is deliberately a project introduction rather than an execution
launcher. It introduces the framework first, then the four long-horizon cases and
the measured Hybrid-versus-GUI evidence. Benchmark values are read from real local run records; missing paired
samples remain visibly unavailable rather than being estimated. Run history stays under `runs/ui/`, and the
page never accepts or stores an API key.

Experiments are launched explicitly from the CLI. **Hybrid Action Space** lets the selected policy choose both
the next intent and the best available PyAutoGUI, DOM, COM, CLI, MCP or API route. **GUI Only** is the
recordable action-space ablation: every mutation is performed visibly through PyAutoGUI. Jev and the
deterministic Rule baseline can run against either action space, so policy and action space are not conflated.

Codex is treated as an external non-Jev runner, not relabelled Rule behavior. A Codex Hybrid run may use
browser automation, COM, CLI, filesystem tools and GUI actions; it should not be presented as GUI Only.
After Codex runs the same task and passes the same terminal verifier, import its measured result through
the local-only baseline contract. The first Codex measurements are pilot samples, not a statistically
supported speed ranking: Jev uses prebuilt task capability packs, whereas Codex plans with general tools.
The wall clock includes fixture setup, agent/tool time and terminal verification; explicit human approval
waits are excluded and must be disclosed. Missing values stay unavailable rather than being estimated:

```powershell
$bootstrap = Invoke-RestMethod http://127.0.0.1:8768/api/bootstrap
$body = @{
  agent = "codex_computer_use"; task = "edge"; action_space = "hybrid"
  success = $true; duration_ms = 42000; actions = 14
  channels = @{ script = 14 }; verifier = "shared_terminal_verifier"
} | ConvertTo-Json
Invoke-RestMethod http://127.0.0.1:8768/api/baselines -Method Post `
  -Headers @{ "X-CUA-JEV-CSRF" = $bootstrap.csrf } -ContentType "application/json" -Body $body
```

`scripts/codex_baseline_fixture.py` can prepare any v2 task in an isolated temporary workspace and invoke
that task's existing terminal evaluator. It intentionally does not solve the task; Codex must perform the
actions through its chosen tools. Its `verify` command checks the same final task predicate used by Jev.

### Codex Hybrid pilot (2026-09-23)

These are the first four **single-run** Codex Hybrid measurements against the frozen v2 tasks. The Jev
column is the median of existing successful Hybrid runs, not a matched same-day trial. Every listed run
passed the task's terminal evaluator.

| Task | Jev Hybrid median | Jev model USD | Jev runs | Codex Hybrid wall time | Codex reference USD | Codex runs |
|---|---:|---:|---:|---:|---:|---:|
| Edge | 79.5 s | $0.00072 | 2/2 | 77.4 s | ~$0.257 | 1/1 |
| Excel | 84.2 s | $0.00143 | 3/3 | 39.2 s | ~$0.071 | 1/1 |
| VS Code | 14.0 s | $0.00362 | 2/2 | 57.9 s | ~$0.098 | 1/1 |
| Explorer | 13.2 s | $0.00492 | 4/4 | 50.9 s | ~$0.106 | 1/1 |

Jev USD is calculated from each successful trace's API-reported input tokens at the [published Jev 1.13
rate](https://docs.typesafe.ai/models) of $0.042 per million; output is free. Codex USD is **a reference
estimate, not an observed bill**: local `token_count` events for the four pilot windows are converted with
OpenAI's [GPT-6 Sol Enterprise token-based USD rate card](https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing)
($2/$0.20/$10 per million uncached input/cached input/output tokens at Standard speed). The corresponding
[credit rates](https://learn.chatgpt.com/docs/pricing) are retained in the benchmark API, not foregrounded
on the website. Actual costs vary by account, region, plan, agreement and speed mode; included
subscription usage is not an incremental charge. The
Codex pilot ran inside an existing long conversation, so its large, mostly cached context should not be
interpreted as a fresh-task cost. The website foregrounds USD for readability; the benchmark API also
exposes token counts, credits and sample coverage. These are model-inference estimates, excluding other
infrastructure costs and any unreported failed Jev requests.
The [published pilot counters](benchmarks/v2-cost-pilot-2026-09-23.json) make the USD calculation reproducible.

Codex used a generic Playwright browser adapter for Edge, generic COM operations for Excel, and CLI/file
tools for VS Code and Explorer. Its clock includes fixture setup, model/tool interaction and terminal
verification. The 26.6 s spent waiting for human approval before the public demo checkout was excluded
from Edge's 77.4 s. Codex had access to this repository's task specifications; Jev used its already-built
capability packs. This pilot shows feasibility and exposes both wins and losses, **not** a general speed
ranking or an isolated measurement of model response latency. In these stored Jev runs, Edge and Excel
Hybrid selected GUI actions only; they do not demonstrate faster structured-route selection yet.

Run the no-key deterministic demo:

```powershell
cua-jev demo --policy rule
cua-jev episode-demo --policy rule
cua-jev experiment --policy rule --episodes 10
cua-jev tasks
cua-jev suite --task all --policy rule
```

It creates a small report under `demo-workspace/`, offers three equivalent read-only routes—typed filesystem
API, MCP and allowlisted PowerShell—selects one, executes it and writes the complete trace to
`runs/demo.jsonl`.

`episode-demo` is a real sixteen-step publishing loop. It resets a mixed inbox, selects ten eligible reports,
offers filesystem API, MCP and CLI routes, writes five release artifacts, then accepts completion only
after independent byte-for-byte, checksum and exclusion checks. `experiment` repeats this resettable episode without
dropping failures from the denominator.

The complete suite command runs four multi-step, independently verified workflows:

| Workflow | Required state transitions | Competing real routes |
|---|---|---|
| Edge long-horizon purchase | navigate, sign in, sort, add two products, validate cart, fill checkout, review and verify receipt (15 decisions) | PyAutoGUI in GUI Only; PyAutoGUI and live DOM in Hybrid |
| Excel analysis delivery | compute seven KPIs, mark reviewed, create two charts, verify through fresh COM (11 decisions) | PyAutoGUI in GUI Only; PyAutoGUI and live COM in Hybrid |
| VS Code diagnosis | run eight failing tests, repair one defect at a time through competing tools, rerun after every mutation, prove green (18 decisions) | PyAutoGUI in GUI Only; PyAutoGUI, MCP, filesystem API and CLI in Hybrid |
| Explorer publishing | select ten final Q3 reports among draft, prior-quarter and private distractors, archive them, write five release artifacts (16 decisions) | PyAutoGUI in GUI Only; PyAutoGUI, MCP, filesystem API and CLI in Hybrid |

These are not four fixed action scripts. At each state, the task builder offers every currently legal
**intent × execution route** pair. For example, the initial Excel state can expose multiple candidates across
ten pending subgoals and three backends; after one action, the remaining candidate set is rebuilt from the
new workbook state. Jev therefore chooses both *what to do next* and *how to do it*.

Use `--profile visible` for a recordable physical-GUI run. `--headed-edge`, `--open-vscode` and
`--visible-apps` are added by the web console; when invoking the CLI directly, pass them explicitly. Every
task is reset before each episode, and summary JSON plus per-task JSONL traces are written under `runs/`.

```powershell
cua-jev suite --task edge --policy rule --profile visible --headed-edge
cua-jev suite --task excel --policy rule --profile visible --visible-apps
cua-jev suite --task vscode --policy rule --profile visible --open-vscode
cua-jev suite --task explorer --policy rule --profile visible --visible-apps
```

Use `--profile adaptive` for the visible multi-action-space system. Add `--policy-fallback` when a demo
should finish through a transparently traced Rule fallback during transient Jev network outages:

```powershell
cua-jev suite --task all --policy jev --profile adaptive --policy-fallback `
  --headed-edge --open-vscode --visible-apps
```

The Edge GUI-only run deliberately targets the public `https://www.saucedemo.com/` site. The bundled HTML
page remains only as a deterministic regression fixture for the hybrid evaluation profile; it is not used
by the public demo.

To run the same candidates through real Jev:

```powershell
$env:TYPESAFE_API_KEY = "your-key"
cua-jev demo --policy jev
cua-jev suite --task all --policy jev
cua-jev suite --task all --policy jev --profile visible --headed-edge --open-vscode --visible-apps
```

For repeatable v2 paired experiments and publishable screen recordings, keep the key in the ignored local
`.env`, install the recording extra, and run the recorder. It executes the same Jev policy once against
`Hybrid Action Space` and once against `GUI Only` for every suite, writes benchmark-compatible records under
`runs/ui/`, and saves H.264 videos with a live route HUD under `artifacts/demos/`:

```powershell
Copy-Item .env.example .env
# Edit .env and set TYPESAFE_API_KEY locally; it is ignored by Git.
python -m pip install -e ".[all,ui,recording]"
python scripts/record_v2_demos.py --task all --profile both --policy jev
```

Use `--samples 3` to collect three paired samples while recording only the first run of each condition. The
showcase automatically exposes available `Hybrid` and `GUI Only` videos on the corresponding case card.
Recordings do not autoplay, and all measurements still come from the JSONL trace rather than video duration.

Validate only the API decision path, or repeat the frozen task for reliability measurements:

```powershell
cua-jev jev-smoke
cua-jev benchmark --policy jev --episodes 10
```

Never commit the key. `.env` files, traces and demo workspaces are ignored. The client sends credentials only
in the HTTPS Authorization header and never stores the key in a trace or exception.

## Edge DOM setup

CUA-JEV attaches only to a browser instance that the user explicitly starts with CDP enabled. Close existing
Edge instances or use a separate profile, then run:

```powershell
msedge.exe --remote-debugging-port=9222 --user-data-dir="$PWD\.edge-cua-profile"
```

The adapter defaults to `http://127.0.0.1:9222`. It does not launch or silently attach to a personal browser
profile.

## Safety contract

Actions are denied before execution unless all checks pass:

1. the decision references the current observation and one offered candidate;
2. the observation has not already been consumed;
3. every path stays under an explicitly allowed root;
4. local writes are enabled for that run;
5. destructive/external actions and confirmation-gated actions are explicitly authorized;
6. an executor exists for the selected channel.

CLI execution accepts only registered factories that return an argv list and always runs with `shell=False`.
Excel execution never runs VBA. MCP calls must be registered as typed tools. A successful executor receipt is
not enough for important tasks; add a state-based verifier such as `file.exists`, `file.contains`, a DOM
predicate or an Excel workbook predicate.

## Writing a predefined task

Tasks are JSON documents containing one structured observation and a list of complete action candidates.
The included example is
[`inspect_report.json`](src/cua_jev/predefined/inspect_report.json).

```json
{
  "name": "inspect_report",
  "description": "Inspect a report without changing it.",
  "subgoal": "Read it through one available channel.",
  "state": {"constraints": ["read_only"]},
  "candidates": [
    {
      "id": "api_read",
      "channel": "api",
      "capability": "filesystem.read_text",
      "description": "Read through the typed filesystem API.",
      "arguments": {"path": "${REPORT}"},
      "risk": "read_only",
      "verifier": "receipt.success"
    }
  ]
}
```

Candidate IDs and capability names are machine contracts. Descriptions and the structured state give Jev the
semantics needed to choose. Executors never trust descriptions as executable instructions.

## Evaluation plan

The first experiments should keep observations, candidates, guards and executors fixed and compare:

| Policy | Channels | Purpose |
|---|---|---|
| rule baseline | hybrid | deterministic lower bound |
| general LLM choice | hybrid | expensive decision baseline |
| Jev choice | hybrid | primary system |
| general LLM / Jev | GUI only | fair comparison with conventional CUA |

Record task success, verifier success, decision latency, end-to-end time, action count, channel distribution,
fallbacks, guard rejections and API usage. Do not interpret Jev action probabilities as calibrated task-success
probabilities.

## Scope and roadmap

The first release focuses on the action router, multi-route execution contract and a dense local experiment console. Next
milestones are:

1. replace the in-process demo MCP tools with configurable remote MCP servers;
2. run Jev-vs-rule-vs-LLM ablations over frozen tasks and publish traces;
3. add cross-route executor retry and richer DOM/UIA/Excel predicates;
4. grow from four workflows into parameterized task families with held-out instances;
5. add an optional VLM fallback only for observations that DOM/UIA/COM cannot resolve.

## Honest first-release boundary

The four representative suites are executable today, but they are deliberately frozen fixtures rather than
open-ended desktop tasks. CUA-JEV targets predefined tasks with structured DOM, UIA, COM, terminal and
filesystem state. It does not understand arbitrary screenshots, generate arbitrary shell commands, recover
from every application dialog, or claim general Windows autonomy.

Apache-2.0 licensed.

The console uses the official ZJU-REAL mark and Qiushi eagle assets from
[zjureal.com](https://zjureal.com/). Their inclusion identifies the lab project and does not change the
repository's code license.

# CUA-JEV

**A typed, verifiable Jev action router for hybrid Windows computer use.**

CUA-JEV tests a narrow hypothesis: once a task and the current computer state have been converted into a
small set of legal actions, can Jev select the next action faster and more cheaply than a general-purpose
agent while preserving safety and task success?

The first prototype deliberately uses **no VLM**. It combines structured observations from Edge DOM,
Windows UI Automation, Excel COM, VS Code/terminal text, filesystem APIs and MCP-shaped tools. Jev does
not generate shell commands or scripts. It chooses one complete, typed action candidate; a deterministic
guard validates it, a channel executor runs it, and an independent verifier checks the result.

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
| Edge | Playwright over an isolated Edge session | GUI-style DOM actions, injected DOM events, resource extraction |
| Windows UI | UI Automation through pywinauto | top-level snapshot, invoke, set text, hotkey |
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

For the local experiment console used in demos:

```powershell
python -m pip install -e ".[dev,all,ui]"
$env:TYPESAFE_API_KEY = "your-key"  # omit when using the Rule baseline
cua-jev-ui
```

Open `http://127.0.0.1:8768`. **Jev Demo** is the honest presentation mode: it always uses the live Jev
policy, does not silently replay a prior run, and can expose the real Edge, Excel, VS Code and Explorer
windows while the task executes. **Evaluation** makes Jev and the deterministic Rule baseline available for
controlled comparisons. Historical runs are labelled `REPLAY` and load only when selected explicitly.

The console shows the complete closed loop: structured observation, the currently legal intent-and-route
candidates, Jev probabilities, commitment, Guard approval, executor receipt and independent verification.
Run history stays under `runs/ui/`; the key is inherited from the server environment and is never entered in
or stored by the page. The console binds to localhost because its job is to operate local Windows
applications, not to act as a hosted control plane.

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

`episode-demo` is a real two-step closed loop. It resets a sandbox, offers filesystem API and MCP copy
routes, executes one, observes the changed filesystem, emits `control.done`, and accepts completion only
after an independent byte-for-byte verifier. `experiment` repeats this resettable episode without dropping
failures from the denominator.

The complete suite command runs four multi-step, independently verified workflows:

| Workflow | Required state transitions | Competing real routes |
|---|---|---|
| Edge procurement | set category, set budget, require stock, search, review, export | visible DOM GUI, injected DOM script, page resource API |
| Excel sales review | compute total, compute average, mark reviewed, create chart | visible Excel COM, background COM script, direct workbook API |
| VS Code diagnosis | run failing tests, repair either independent defect, rerun, repair the other, prove green | visible editor UIA, MCP, filesystem API, allowlisted CLI |
| Explorer publishing | distinguish final Q3 files from draft/prior-quarter distractors, archive both, write exact manifest | visible Explorer UIA, MCP, filesystem API, allowlisted CLI |

These are not four fixed action scripts. At each state, the task builder offers every currently legal
**intent × execution route** pair. For example, the initial Excel state can expose twelve candidates across
four pending subgoals and three backends; after one action, the remaining candidate set is rebuilt from the
new workbook state. Jev therefore chooses both *what to do next* and *how to do it*.

Use `--headed-edge`, `--open-vscode` and `--visible-apps` for a recordable run in which all four desktop GUI
routes are available. Every task is reset before each episode, and summary JSON plus per-task JSONL traces
are written under `runs/` by default.

To run the same candidates through real Jev:

```powershell
$env:TYPESAFE_API_KEY = "your-key"
cua-jev demo --policy jev
cua-jev suite --task all --policy jev
cua-jev suite --task all --policy jev --headed-edge --open-vscode --visible-apps
```

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
3. add action fallback/recovery policies, cross-route retry and richer DOM/UIA/Excel predicates;
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

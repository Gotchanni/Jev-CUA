# CUA-JEV

**A typed, verifiable Jev action router for hybrid Windows computer use.**

CUA-JEV tests a narrow hypothesis: once a task and the current computer state have been converted into a
small set of legal actions, can Jev select the next action faster and more cheaply than a general-purpose
agent while preserving safety and task success?

The v0.1 prototype deliberately uses **no VLM**. It combines structured observations from Edge DOM,
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

- strict TypeSafe Jev `choice` client with response validation, retries and credential redaction;
- composite `ActionCandidate` objects across GUI, CLI, MCP, script/API and control channels;
- fail-closed guard for stale decisions, replay, path boundaries, writes and confirmation;
- unified action receipts, verifier registry and JSONL traces;
- deterministic rule policy for a no-key baseline and ablation experiments;
- a reproducible multi-channel routing demo.

Initial capability adapters:

| Capability pack | Structured interface | v0.1 operations |
|---|---|---|
| Edge | Playwright over an explicitly launched CDP session | DOM snapshot, click, fill, navigate |
| Windows UI | UI Automation through pywinauto | top-level snapshot, invoke, set text, hotkey |
| Excel | COM through pywin32 | workbook snapshot, read/write range, create chart |
| VS Code/Terminal | official `code` CLI and allowlisted argv templates | open/goto, Git status/diff, PowerShell read |
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

Run the no-key deterministic demo:

```powershell
cua-jev demo --policy rule
```

It creates a small report under `demo-workspace/`, offers three equivalent read-only routes—typed filesystem
API, MCP and allowlisted PowerShell—selects one, executes it and writes the complete trace to
`runs/demo.jsonl`.

To run the same candidates through real Jev:

```powershell
$env:TYPESAFE_API_KEY = "your-key"
cua-jev demo --policy jev
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

v0.1 focuses on the action router and execution contract. Next milestones are:

1. complete four reproducible Windows task suites for Edge, Excel, VS Code and Explorer;
2. add DOM/UIA/Excel-specific state verifiers and reset fixtures;
3. add a standard remote MCP transport behind the current typed tool boundary;
4. run Jev-vs-rule-vs-LLM ablations over frozen tasks and publish traces;
5. add an optional VLM fallback only for observations that DOM/UIA/COM cannot resolve.

Apache-2.0 licensed.

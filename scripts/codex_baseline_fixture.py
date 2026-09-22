"""Hold a fresh v2 task fixture open for an external Computer Use baseline.

The agent performs task actions outside this process. This process only prepares
the same fixture used by the Jev suite and invokes its terminal evaluator.
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path

from cua_jev.models import ActionCandidate, ActionReceipt, Channel, Verification
from cua_jev.suites import SUITE_NAMES, make_suite


def terminal_result(task) -> dict[str, object]:
    now = time.time()
    done = ActionCandidate("external_done", Channel.CONTROL, "control.done", "Verify terminal state")
    receipt = ActionReceipt("external", "external", done.id, done.channel, done.capability, True, now, now)
    verification = Verification(True, "shared_terminal_verifier")
    result = task.evaluate(task.observe(()), done, receipt, verification)
    return {"success": result.success, "terminal": result.terminal, "reason": result.reason}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task", choices=SUITE_NAMES)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="cua-jev-codex-baseline-") as scratch:
        task = make_suite(
            args.task,
            Path(scratch),
            headed_edge=args.task == "edge",
            open_vscode=False,
            visible_apps=args.task == "excel",
            profile="visible" if args.task in {"edge", "excel"} else "hybrid",
        )
        try:
            task.reset()
            print(
                json.dumps({"event": "ready", "task": args.task, "workspace": str(task.workspace)}),
                flush=True,
            )
            while True:
                try:
                    line = input().strip()
                except EOFError:
                    break
                command = line.lower()
                if command == "verify":
                    print(json.dumps({"event": "verification", **terminal_result(task)}), flush=True)
                elif command == "stop":
                    break
                elif command == "observe":
                    print(json.dumps({"event": "observation", "state": task.observe(()).state}), flush=True)
                elif line.startswith("{"):
                    request = json.loads(line)
                    if args.task == "edge":
                        page = task._page
                        if request["op"] == "navigate":
                            page.goto(request["url"], wait_until="domcontentloaded")
                        elif request["op"] == "fill":
                            page.locator(request["selector"]).fill(request["value"])
                        elif request["op"] == "click":
                            page.locator(request["selector"]).click()
                        elif request["op"] == "select":
                            page.locator(request["selector"]).select_option(request["value"])
                        else:
                            raise ValueError("unknown browser operation")
                    elif args.task == "excel":
                        book = task._demo_book
                        if request["op"] == "set_cell":
                            book.Worksheets(request["sheet"]).Range(request["cell"]).Formula = request[
                                "value"
                            ]
                        elif request["op"] == "add_chart":
                            sheet = book.Worksheets(request["sheet"])
                            chart = sheet.ChartObjects().Add(
                                request["left"], request["top"], request["width"], request["height"]
                            )
                            chart.Chart.SetSourceData(
                                book.Worksheets(request["source_sheet"]).Range(request["source_range"])
                            )
                            chart.Chart.ChartType = request["chart_type"]
                        elif request["op"] == "save":
                            book.Save()
                        else:
                            raise ValueError("unknown Excel operation")
                    else:
                        raise ValueError("generic app command not supported for this task")
                    print(json.dumps({"event": "action", "op": request["op"], "ok": True}), flush=True)
                else:
                    print(json.dumps({"event": "error", "message": "unknown command"}), flush=True)
        finally:
            task.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI for the plain tool-calling model player: `python -m kestrel.agent run|all`."""
import argparse
import json
import sys

from . import runner
from .tasks import TASKS


def _last_error(result: dict):
    for frame in reversed(result["frames"]):
        if frame.get("error"):
            return frame["error"]
    return None


def _summary(task_id, player, result) -> dict:
    return {"task": task_id, "player": player, "status": result["status"],
            "completed_days": result["completed_days"], "requested_days": result["requested_days"],
            "usage": result["usage"], "error": _last_error(result)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m kestrel.agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run_p = sub.add_parser("run", help="run one task with one player")
    run_p.add_argument("--task", required=True, choices=sorted(TASKS))
    run_p.add_argument("--player", required=True, choices=["luna", "rule"])
    run_p.add_argument("--days", type=int, default=None)
    run_p.add_argument("--resume", action="store_true")

    all_p = sub.add_parser("all", help="run every task with one player")
    all_p.add_argument("--player", required=True, choices=["luna", "rule"])
    all_p.add_argument("--days", type=int, default=None)
    all_p.add_argument("--resume", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "run":
        try:
            result = runner.run(args.task, args.player, days=args.days, resume=args.resume)
        except ValueError as e:
            print(f"error: {e}")
            return 1
        print(json.dumps(_summary(args.task, args.player, result)))
        return 0

    exit_code = 0
    for task_id in TASKS:
        try:
            result = runner.run(task_id, args.player, days=args.days, resume=args.resume)
        except ValueError as e:
            print(f"error: {task_id}: {e}")
            exit_code = 1
            continue
        summary = _summary(task_id, args.player, result)
        print(json.dumps(summary))
        if summary["error"]:
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

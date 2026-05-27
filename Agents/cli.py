"""Run as: python -m Agents.cli review|show ..."""
from __future__ import annotations
import argparse
from pathlib import Path

from Agents.review import analyze, format_report
from Agents.show import format_session


def main() -> None:
    parser = argparse.ArgumentParser(prog="agents")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_review = sub.add_parser("review", help="Mine transcripts for whitelist & tool promotion")
    p_review.add_argument("--root", default="./Workspaces", help="Workspaces root directory")

    p_show = sub.add_parser("show", help="Pretty-print one session JSONL")
    p_show.add_argument("path", help="Path to a session .jsonl file")

    args = parser.parse_args()
    if args.cmd == "review":
        print(format_report(analyze(Path(args.root))))
    elif args.cmd == "show":
        print(format_session(args.path))


if __name__ == "__main__":
    main()

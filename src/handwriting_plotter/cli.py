"""Command-line boundary for Handwriting Plotter."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .domain.errors import ExitCode
from .version import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hplot",
        description="Generate deterministic single-line handwriting plotter artifacts.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.add_parser("version", help="print the application version")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "version":
        print(__version__)
        return ExitCode.OK
    parser.print_help()
    return ExitCode.OK


if __name__ == "__main__":
    raise SystemExit(main())


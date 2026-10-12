"""Command-line boundary for Handwriting Plotter."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .application.service import GenerationRequest, HandwritingPlotterService, read_utf8_text
from .domain.errors import ExitCode
from .domain.models import canonical_json_bytes, strict_json_loads
from .styles.models import StyleManifest
from .styles.repository import FileStyleRepository
from .version import __version__


def _generation_arguments(parser: argparse.ArgumentParser, *, output: bool) -> None:
    parser.add_argument("input", type=Path, help="UTF-8 input text file")
    if output:
        parser.add_argument("output", type=Path, help="new output bundle directory")
        parser.add_argument("--overwrite", action="store_true", help="atomically replace an existing bundle")
    parser.add_argument("--style", default="test-technical-v1", help="immutable style id")
    parser.add_argument("--style-revision", default="1.0.0", help="immutable style revision")
    parser.add_argument("--seed", type=int, default=1, help="unsigned 64-bit generation seed")
    parser.add_argument("--realism", type=float, default=0.35, help="bounded variation in [0,1]")
    parser.add_argument("--style-root", type=Path, help="explicit StylePack repository root")
    parser.add_argument("--profile", type=Path, help="explicit virtual profile JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hplot",
        description="Generate deterministic single-line handwriting plotter artifacts.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.add_parser("version", help="print the application version")
    inspect_parser = subparsers.add_parser("inspect", help="normalize text and report exact glyph coverage")
    _generation_arguments(inspect_parser, output=False)
    generate_parser = subparsers.add_parser("generate", help="atomically create SVG/PenPlan/virtual G-code bundle")
    _generation_arguments(generate_parser, output=True)
    export_parser = subparsers.add_parser("export", help="same verified bundle export as generate")
    _generation_arguments(export_parser, output=True)
    simulate_parser = subparsers.add_parser("simulate", help="run the full pipeline in memory and print its report")
    _generation_arguments(simulate_parser, output=False)
    styles_parser = subparsers.add_parser("styles", help="StylePack operations")
    styles_sub = styles_parser.add_subparsers(dest="styles_command", required=True)
    validate = styles_sub.add_parser("validate", help="validate one immutable StylePack directory")
    validate.add_argument("path", type=Path)
    return parser


def _request(args: argparse.Namespace) -> GenerationRequest:
    return GenerationRequest(args.style, args.style_revision, args.seed, args.realism)


def _service(args: argparse.Namespace) -> HandwritingPlotterService:
    return HandwritingPlotterService(args.style_root, args.profile)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if args.command == "version":
            print(__version__)
            return ExitCode.OK
        if args.command is None:
            parser.print_help()
            return ExitCode.OK
        if args.command == "styles":
            package = args.path.resolve()
            manifest_data = strict_json_loads((package / "manifest.json").read_bytes())
            manifest = StyleManifest.model_validate_json(canonical_json_bytes(manifest_data), strict=True)
            snapshot = FileStyleRepository(package.parents[1]).load(manifest.style_id, manifest.revision)
            print(json.dumps({
                "passed": True,
                "style_id": manifest.style_id,
                "revision": manifest.revision,
                "revision_hash": snapshot.revision_hash,
                "test_only": manifest.test_only,
                "production_eligible": manifest.production_eligible,
            }, ensure_ascii=False, sort_keys=True))
            return ExitCode.OK
        text = read_utf8_text(args.input)
        service = _service(args)
        request = _request(args)
        if args.command == "inspect":
            report = service.inspect(text, request)
            print(json.dumps(report, ensure_ascii=False, sort_keys=True))
            return ExitCode.OK if report["passed"] else ExitCode.VALIDATION_FAILED
        if args.command == "simulate":
            result = service.build(text, request)
            print(json.dumps(result.report, ensure_ascii=False, sort_keys=True))
            return ExitCode.OK
        result = service.generate(text, args.output, request, overwrite=args.overwrite)
        print(json.dumps({
            "complete": True,
            "document_id": result.document_id,
            "pages": result.page_count,
            "output": str(args.output),
            "test_only_style": result.test_only_style,
            "hardware_verified": False,
        }, ensure_ascii=False, sort_keys=True))
        return ExitCode.OK
    except (UnicodeError, ValueError, FileNotFoundError, FileExistsError) as error:
        print(json.dumps({"error": type(error).__name__, "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return ExitCode.VALIDATION_FAILED
    except OSError as error:
        print(json.dumps({"error": "IO_ERROR", "message": str(error)}, ensure_ascii=False), file=sys.stderr)
        return ExitCode.IO_ERROR


if __name__ == "__main__":
    raise SystemExit(main())


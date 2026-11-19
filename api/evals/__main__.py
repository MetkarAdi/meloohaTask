"""Run with `python -m evals [--smoke]`; npm scripts use the API venv."""

import argparse
from pathlib import Path

from .runner import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Gemini and Groq grounded astrology answers against fixed, synthetic chart cases.")
    parser.add_argument("--smoke", action="store_true", help="run the fixed six-case smoke set")
    parser.add_argument("--provider", choices=("both", "gemini", "groq"), default="both")
    parser.add_argument("--report", type=Path, help="Markdown report path")
    parser.add_argument("--json-report", type=Path, help="JSON report path")
    parser.add_argument("--previous-json", type=Path, help="previous JSON report used for deltas")
    parser.add_argument("--min-factual", type=float)
    parser.add_argument("--min-grounding", type=float)
    parser.add_argument("--min-interpretation", type=float)
    parser.add_argument("--strict-subjective", action="store_true", help="allow subjective judge threshold to gate the exit code")
    args = parser.parse_args()
    docs = Path(__file__).resolve().parents[2] / "docs"
    report = args.report
    json_report = args.json_report
    previous = args.previous_json
    if not args.smoke:
        report = report or docs / "eval-report.md"
        json_report = json_report or docs / "eval-report.json"
        previous = previous or json_report
    try:
        run(smoke=args.smoke, report_path=report, json_path=json_report, provider=args.provider,
            previous_json=previous, min_factual=args.min_factual, min_grounding=args.min_grounding,
            min_interpretation=args.min_interpretation,
            strict_subjective=True if args.strict_subjective else None)
    except (RuntimeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

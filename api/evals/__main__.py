"""Run with python -m evals [--smoke]."""

import argparse
from pathlib import Path

from .runner import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate grounded astrology answers with an independent Gemini judge.")
    parser.add_argument("--smoke", action="store_true", help="run only five fixed questions")
    parser.add_argument("--report", type=Path, help="write a Markdown report to this path")
    args = parser.parse_args()
    report = args.report
    if report is None and not args.smoke:
        report = Path(__file__).resolve().parents[2] / "docs" / "eval-report.md"
    try:
        run(smoke=args.smoke, report_path=report)
    except RuntimeError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()

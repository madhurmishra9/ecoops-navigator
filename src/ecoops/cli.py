"""Command line: ``ecoops generate | analyse | verify``."""

from __future__ import annotations

import argparse
import sys

from .generator import SIMULATABLE, generate
from .ingest import load_csv_dir, save_csv_dir
from .pipeline import run
from .report import export
from .settings import load_settings
from .utils import fmt_qty


def _generate(args: argparse.Namespace) -> int:
    written = save_csv_dir(generate(args.seed), args.out)
    print(f"Wrote {len(written)} synthetic telemetry tables to {args.out}")
    return 0


def _analyse(args: argparse.Namespace) -> int:
    settings = load_settings(args.config)
    data = load_csv_dir(args.data) if args.data else generate(args.seed)
    result = run(data, settings)
    written = export(result, args.out)
    s = result.summary
    c = result.currency
    print(f"Analysed {result.period_days} days | {s['opportunity_counts']['total']} opportunities "
          f"({s['opportunity_counts']['blocked']} blocked, {s['opportunity_counts']['conditional']} conditional)")
    print(f"Identified (annual, actionable): {fmt_qty(s['identified_savings']['annual_co2e_kg'] / 1000, 'tCO2e')}, "
          f"{fmt_qty(s['identified_savings']['annual_cost'], c)}")
    print("\nTop opportunities:")
    for o in s["top_opportunities"]:
        print(f"  {o['score']:5.1f}  {o['title']}  [{o['next_step']}]")
    for issue in result.data_issues:
        print(f"  data: {issue}")
    print(f"\nWrote {len(written)} files to {args.out}")
    return 0


def _verify(args: argparse.Namespace) -> int:
    from .verification import verify

    ids = list(SIMULATABLE) if args.all or not args.ids else args.ids
    df = verify(ids, seed=args.seed, settings=load_settings(args.config))
    cols = ["entity", "estimated_co2e_kg", "realised_co2e_kg", "estimated_cost", "realised_cost", "verdict"]
    print(df[cols].to_string(index=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ecoops", description="EcoOps Navigator decision-support CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="write synthetic telemetry CSVs")
    g.add_argument("--seed", type=int, default=42)
    g.add_argument("--out", default="data")
    g.set_defaults(func=_generate)

    a = sub.add_parser("analyse", help="run the analysis and write reports")
    a.add_argument("--data", help="directory of input CSVs (default: generate synthetic data in memory)")
    a.add_argument("--seed", type=int, default=42)
    a.add_argument("--config", help="directory with override YAML (factors/rules/constraints/scoring)")
    a.add_argument("--out", default="reports")
    a.set_defaults(func=_analyse)

    v = sub.add_parser("verify", help="simulate implemented actions and compare realised vs estimated")
    v.add_argument("ids", nargs="*", help=f"opportunity ids (choices: {', '.join(SIMULATABLE)})")
    v.add_argument("--all", action="store_true")
    v.add_argument("--seed", type=int, default=42)
    v.add_argument("--config")
    v.set_defaults(func=_verify)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

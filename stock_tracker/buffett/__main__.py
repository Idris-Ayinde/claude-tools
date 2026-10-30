"""Command-line refresh: `python -m buffett [--countries USA Canada] [--limit N]`."""
import argparse
import sys

from .config import COUNTRIES, RESULTS_FILE
from .pipeline import run_screen, save_results, top_picks


def main() -> None:
    parser = argparse.ArgumentParser(description="Moat Finder: run the Buffett-style screen and save results for the dashboard.")
    parser.add_argument("--countries", nargs="+", choices=COUNTRIES, default=list(COUNTRIES))
    parser.add_argument("--limit", type=int, default=None, help="max stocks per sector (quick test runs)")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--min-success", type=float, default=0.8,
                        help="don't save if fewer than this share of stocks could be scored (e.g. Yahoo throttling)")
    args = parser.parse_args()

    def progress(done, total, ticker):
        sys.stderr.write(f"\r[{done}/{total}] {ticker:<12}")

    df = run_screen(args.countries, limit_per_sector=args.limit, workers=args.workers, progress=progress)
    sys.stderr.write("\n")
    success = df["eligible"].fillna(False).astype(bool).mean() if len(df) else 0.0
    if success < args.min_success:
        print(f"Only {success:.0%} of {len(df)} stocks could be scored (need {args.min_success:.0%}); "
              f"keeping the previous results in {RESULTS_FILE}.")
        sys.exit(1)
    save_results(df)
    picks = top_picks(df)
    cols = ["country", "sector", "ticker", "name", "score", "checklist", "price", "intrinsic_value"]
    print(picks[cols].to_string(index=False, float_format=lambda x: f"{x:,.2f}"))
    print(f"\nScreened {len(df)} stocks, {int(df['eligible'].sum())} eligible. Saved to {RESULTS_FILE}")


if __name__ == "__main__":
    main()

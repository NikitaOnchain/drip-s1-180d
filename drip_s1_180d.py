"""DRIP Season 1, 180 days later: a quick protocol-level check with DefiLlama data.

What it does:
1. Downloads daily "borrowed" series per protocol and chain from the public DefiLlama API.
2. Computes borrowing at fixed checkpoints as a % of the pre-campaign baseline.
3. Compares each DRIP protocol on Arbitrum with the same protocol on Ethereum and Base
   (no DRIP there) and with Compound V3 on Arbitrum (not in DRIP).
4. Writes a CSV and two charts.

Run:  .venv/Scripts/python drip_s1_180d.py
"""

import csv
import datetime as dt
import json
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import requests

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
OUT_CSV = ROOT / "data" / "drip_s1_borrowed_index.csv"
DAILY_CSV = ROOT / "data" / "defillama_borrowed_daily.csv"
FIG = ROOT / "figures"

# Same calendar as the Morpho case study (campaign 2025-09-03 .. 2026-02-18).
BASELINE = (dt.date(2025, 7, 9), dt.date(2025, 9, 2))  # 56 days before the campaign
CHECKPOINTS = {
    "Campaign end": dt.date(2026, 2, 18),
    "+30d": dt.date(2026, 3, 20),
    "+90d": dt.date(2026, 5, 19),
    "+180d": dt.date(2026, 8, 17),
}

# (label, DefiLlama slug, in DRIP Season 1 on Arbitrum?)
PROTOCOLS = [
    ("Fluid", "fluid-lending", True),
    ("Morpho", "morpho-blue", True),
    ("Aave V3", "aave-v3", True),
    ("Dolomite", "dolomite", True),
    ("Silo V2", "silo-v2", True),
    ("Euler V2", "euler-v2", True),
    ("Compound V3", "compound-v3", False),
]
CHAINS = ["Arbitrum", "Ethereum", "Base"]
MIN_BASELINE_USD = 5e6  # skip tiny deployments: % of a tiny base is noise


def load_protocol(slug):
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{slug}.json"
    if not path.exists():
        resp = requests.get(f"https://api.llama.fi/protocol/{slug}", timeout=120)
        resp.raise_for_status()
        path.write_bytes(resp.content)
    return json.loads(path.read_text(encoding="utf-8"))


def borrowed_series(protocol, chain):
    points = protocol["chainTvls"].get(f"{chain}-borrowed", {}).get("tvl", [])
    return {
        dt.datetime.fromtimestamp(p["date"], dt.timezone.utc).date(): p["totalLiquidityUSD"]
        for p in points
    }


def write_daily_extract(all_series):
    """Save the daily series used here, so results can be checked even if DefiLlama revises data."""
    with DAILY_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["protocol", "chain", "date_utc", "borrowed_usd"])
        for (label, chain), series in all_series.items():
            for day in sorted(series):
                if BASELINE[0] <= day:
                    writer.writerow([label, chain, day.isoformat(), round(series[day])])


def main():
    rows = []
    all_series = {}
    for label, slug, in_drip in PROTOCOLS:
        protocol = load_protocol(slug)
        for chain in CHAINS:
            series = borrowed_series(protocol, chain)
            if series:
                all_series[(label, chain)] = series
            base_values = [v for d, v in series.items() if BASELINE[0] <= d <= BASELINE[1]]
            if len(base_values) < 50:
                continue
            baseline = statistics.mean(base_values)
            if baseline < MIN_BASELINE_USD:
                continue
            row = {
                "protocol": label,
                "chain": chain,
                "drip_s1": in_drip and chain == "Arbitrum",
                "baseline_borrowed_usd": round(baseline),
            }
            for name, day in CHECKPOINTS.items():
                value = series.get(day)
                row[f"{name} usd"] = round(value) if value is not None else ""
                row[f"{name} % of baseline"] = round(value / baseline * 100, 1) if value else ""
            rows.append(row)

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write_daily_extract(all_series)

    FIG.mkdir(exist_ok=True)
    plot_bars(rows)
    plot_lines(rows)
    for r in rows:
        print(f"{r['protocol']:12} {r['chain']:9} DRIP={str(r['drip_s1']):5} "
              f"base={r['baseline_borrowed_usd'] / 1e6:8.1f}M  "
              + "  ".join(f"{k}={r[f'{k} % of baseline']}%" for k in CHECKPOINTS))


def plot_bars(rows):
    """Borrowing at +180d as % of baseline: Arbitrum (DRIP) vs Ethereum (no DRIP)."""
    labels = [p[0] for p in PROTOCOLS]
    get = {(r["protocol"], r["chain"]): r["+180d % of baseline"] for r in rows}
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=150)
    y = range(len(labels))
    arb = [get.get((p, "Arbitrum"), 0) or 0 for p in labels]
    eth = [get.get((p, "Ethereum"), None) for p in labels]
    ax.barh([i + 0.2 for i in y], arb, height=0.38, color="#2b6cb0", label="Arbitrum")
    ax.barh([i - 0.2 for i in y], [e or 0 for e in eth], height=0.38, color="#a0aec0",
            label="Ethereum (no DRIP)")
    for i, (a, e) in enumerate(zip(arb, eth)):
        ax.text(a + 3, i + 0.2, f"{a:.0f}%", va="center", fontsize=8)
        ax.text((e or 0) + 3, i - 0.2, f"{e:.0f}%" if e is not None else "n/a",
                va="center", fontsize=8, color="#4a5568")
    ax.axvline(100, color="black", lw=0.8, ls="--")
    ax.text(101, len(labels) - 0.45, "baseline", fontsize=8)
    ax.set_yticks(list(y))
    ax.set_yticklabels([f"{p}{'' if d else '  (not in DRIP)'}" for p, _, d in PROTOCOLS])
    ax.invert_yaxis()
    ax.set_xlabel("Outstanding borrowing at +180 days, % of pre-campaign baseline (USD)")
    ax.set_title("DRIP Season 1, 180 days later: borrowing vs pre-campaign baseline",
                 loc="left", fontsize=11)
    ax.legend(loc="lower right", fontsize=8, frameon=False)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.text(0.01, 0.01, "Data: DefiLlama, protocol-level borrowed USD. Baseline = mean of "
             "56 days before 2025-09-03. Observational, not causal. @NikitaOnchain",
             fontsize=7, color="#4a5568")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "drip_s1_180d_bars.png")
    plt.close(fig)


def plot_lines(rows):
    """Trajectory for DRIP protocols on Arbitrum, log scale (Morpho starts from a tiny base)."""
    xs = ["Baseline"] + list(CHECKPOINTS)
    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=150)
    for r in rows:
        if r["chain"] != "Arbitrum":
            continue
        ys = [100] + [r[f"{k} % of baseline"] for k in CHECKPOINTS]
        style = dict(lw=2) if r["drip_s1"] else dict(lw=1.5, ls="--", color="black")
        ax.plot(xs, ys, marker="o", label=r["protocol"] + ("" if r["drip_s1"] else " (not in DRIP)"),
                **style)
    ax.set_yscale("log")
    ax.axhline(100, color="grey", lw=0.8)
    ax.set_ylabel("Borrowing, % of baseline (log scale)")
    ax.set_title("Arbitrum lending after DRIP Season 1", loc="left", fontsize=11)
    ax.legend(fontsize=8, frameon=False, ncol=2)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.text(0.01, 0.01, "Data: DefiLlama, protocol-level borrowed USD. Observational, not causal. "
             "@NikitaOnchain", fontsize=7, color="#4a5568")
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "drip_s1_180d_lines.png")
    plt.close(fig)


if __name__ == "__main__":
    main()

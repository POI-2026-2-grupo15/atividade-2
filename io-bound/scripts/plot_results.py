"""Consolida results/<cenário>/u<N>/ (Locust) e results/<cenário>/monitor.csv (VM) em tabela e gráficos."""

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

MONITOR_COLUMNS = {
    "system_cpu_percent": "cpu_percent",
    "cpu_iowait_percent": "iowait_percent",
    "ram_available_bytes": "ram_available_bytes",
    "app_rss_bytes": "app_rss_bytes",
    "app_cpu_percent": "app_cpu_percent",
    "disk_write_bytes_per_s": "disk_write_bytes_per_s",
    "disk_read_bytes_per_s": "disk_read_bytes_per_s",
}
PLOTS = [
    ("requests_per_s", "Vazão (req/s)"),
    ("median_ms", "Latência mediana (ms)"),
    ("p95_ms", "Latência p95 (ms)"),
    ("cpu_percent", "CPU da VM (%)"),
    ("app_cpu_percent", "CPU do processo da API (% de 1 núcleo)"),
    ("iowait_percent", "iowait da VM (%)"),
    ("disk_write_mib_s", "Escrita em disco (MiB/s)"),
    ("ram_available_mib", "RAM disponível (MiB)"),
    ("failure_percent", "Falhas (%)"),
]


def summarize_point(point: Path, monitor: pd.DataFrame | None) -> dict:
    stats = pd.read_csv(point / "locust_stats.csv")
    total = stats[stats["Name"] == "Aggregated"].iloc[0]
    row = {
        "users": int(point.name[1:]),
        "requests": int(total["Request Count"]),
        "failure_percent": 100 * total["Failure Count"] / max(total["Request Count"], 1),
        "requests_per_s": total["Requests/s"],
        "median_ms": total["Median Response Time"],
        "p95_ms": total["95%"],
        "p99_ms": total["99%"],
    }
    if monitor is not None:
        # Janela de medição: trecho em que todos os usuários já estavam ativos.
        history = pd.read_csv(point / "locust_stats_history.csv")
        history = history[(history["Name"] == "Aggregated") & (history["User Count"] == row["users"])]
        window = monitor[monitor["epoch"].between(history["Timestamp"].min(), history["Timestamp"].max())]
        for source, target in MONITOR_COLUMNS.items():
            row[target] = window[source].mean() if source in window else float("nan")
        row["monitor_samples"] = len(window)
    return row


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("results"))
    parser.add_argument("--output", type=Path, default=Path("results/plots"))
    args = parser.parse_args()
    rows = []
    for scenario in sorted(p for p in args.results.iterdir() if p.is_dir() and p != args.output):
        points = sorted(scenario.glob("u*/locust_stats.csv"))
        if not points:
            continue
        monitor = None
        if (scenario / "monitor.csv").exists():
            monitor = pd.read_csv(scenario / "monitor.csv")
            monitor["epoch"] = pd.to_datetime(monitor["timestamp_utc"]).astype("int64") / 1e9
        for stats in points:
            rows.append({"scenario": scenario.name, **summarize_point(stats.parent, monitor)})
    if not rows:
        raise SystemExit(f"Nenhum resultado em {args.results}/<cenário>/u<N>/")
    table = pd.DataFrame(rows).sort_values(["scenario", "users"])
    if "disk_write_bytes_per_s" in table:
        table["disk_write_mib_s"] = table["disk_write_bytes_per_s"] / 2**20
        table["ram_available_mib"] = table["ram_available_bytes"] / 2**20
    args.output.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.output / "summary.csv", index=False)
    for column, label in PLOTS:
        if column not in table or table[column].isna().all():
            continue
        fig, ax = plt.subplots(figsize=(7, 4.5))
        for scenario, group in table.groupby("scenario"):
            ax.plot(group["users"], group[column], marker="o", label=scenario)
        ax.set_xscale("log", base=2)
        ax.set_xticks(sorted(table["users"].unique()), labels=sorted(table["users"].unique()))
        ax.set_xlabel("Usuários simultâneos")
        ax.set_ylabel(label)
        ax.grid(alpha=0.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(args.output / f"{column}.png", dpi=150)
        plt.close(fig)
    print(table.to_string(index=False))
    print(f"\nTabela e gráficos em {args.output}")


if __name__ == "__main__":
    main()

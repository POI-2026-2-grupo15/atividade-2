import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
COLORS = ["#2563a6", "#008b8b", "#7057a3", "#c77d16"]
INK = "#203047"
MUTED = "#566579"
FOOTNOTE = (
    "Piloto Docker · uma execução de 60 s por cenário · sem intervalos de confiança.\n"
    "HTTP: snapshot acumulado do Locust; CPU: segundos 5–58; memória: máximo amostrado.\n"
    "Quota 8 usa SMT em um pool de 7 núcleos físicos. Resultados não equivalem a medições no VirtualBox."
)


def decimal(value: float, places: int = 2) -> str:
    return f"{value:.{places}f}".replace(".", ",")


def style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 11,
        "text.color": INK, "axes.labelcolor": INK, "axes.titlecolor": INK,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.spines.left": False, "axes.edgecolor": "#ccd4df",
        "axes.axisbelow": True, "axes.titleweight": "bold", "axes.titlepad": 16,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "xtick.major.size": 0, "ytick.major.size": 0,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "svg.fonttype": "none",
        "pdf.fonttype": 42,
    })


def prepare_axis(ax, data: pd.DataFrame, title: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=13)
    ax.set_ylabel(ylabel, labelpad=10)
    ax.set_xlabel("Quota de CPU do container", labelpad=9)
    ax.set_xticks(range(len(data)), data["cpu_limit"].astype(str))
    ax.grid(axis="y", color="#e6ebf2", linewidth=0.8)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: decimal(x, 0)))


def throughput(ax, data: pd.DataFrame) -> None:
    prepare_axis(ax, data, "Vazão", "Requisições por segundo")
    bars = ax.bar(range(len(data)), data["requests_per_second"], color=COLORS, width=0.57)
    ax.bar_label(bars, labels=[decimal(v) for v in data["requests_per_second"]], padding=7, fontsize=11)
    ax.set_ylim(0, data["requests_per_second"].max() * 1.22)


def latency(ax, data: pd.DataFrame) -> None:
    prepare_axis(ax, data, "Latência HTTP", "Segundos")
    positions = pd.Series(range(len(data)), dtype=float)
    for values, offset, color, label in [
        (data["average_latency_seconds"], -0.18, "#2563a6", "Média"),
        (data["p95_latency_seconds"], 0.18, "#c77d16", "p95"),
    ]:
        bars = ax.bar(positions + offset, values, width=0.33, color=color, label=label)
        ax.bar_label(bars, labels=[decimal(v) for v in values], padding=5, fontsize=10)
    ax.set_ylim(0, data["p95_latency_seconds"].max() * 1.24)
    ax.legend(frameon=False, loc="upper right", ncols=2)


def cpu(ax, data: pd.DataFrame) -> None:
    prepare_axis(ax, data, "CPU utilizada em relação à quota", "Utilização da quota (%)")
    bars = ax.bar(range(len(data)), data["allocated_cpu_utilization_percent"], color=COLORS, width=0.57)
    ax.axhline(100, color=MUTED, linestyle="--", linewidth=1)
    ax.bar_label(bars, labels=[decimal(v) + "%" for v in data["allocated_cpu_utilization_percent"]], padding=7, fontsize=10)
    ax.set_ylim(0, 118)


def memory(ax, data: pd.DataFrame) -> None:
    prepare_axis(ax, data, "Memória do container", "Memória (MiB)")
    bars = ax.bar(range(len(data)), data["memory_max_mib"], color=COLORS, width=0.57)
    ax.bar_label(bars, labels=[decimal(v, 1) for v in data["memory_max_mib"]], padding=6)
    ax.axhline(1024, color=MUTED, linestyle="--", linewidth=1)
    ax.text(0.02, 1047, "Limite fixo: 1.024 MiB", color=MUTED,
            transform=ax.get_yaxis_transform(), fontsize=10)
    ax.set_ylim(0, 1170)
    ax.set_yticks([0, 256, 512, 768, 1024])


def save(fig, output: Path, name: str) -> None:
    for extension in ("png", "svg", "pdf"):
        fig.savefig(output / f"{name}.{extension}", dpi=200, bbox_inches="tight")
    plt.close(fig)


def heading(fig, title: str, subtitle: str) -> None:
    fig.suptitle(title, x=0.08, y=0.985, ha="left", fontsize=19, fontweight="bold")
    fig.text(0.08, 0.93, subtitle, fontsize=11, color=MUTED, va="top")
    fig.text(0.08, 0.025, FOOTNOTE, fontsize=8.5, color=MUTED, linespacing=1.6)


def plot_timelines(source: Path, output: Path, data: pd.DataFrame) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex=True, sharey=True)
    for ax, (_, row), color in zip(axes.flat, data.iterrows(), COLORS):
        limit, users = int(row["cpu_limit"]), int(row["users"])
        samples = pd.read_csv(source / f"cpu-{limit}" / f"users-{users}" / "resources.csv")
        utilization = samples["container_cpu_percent"] / limit
        ax.axvspan(5, 58, color="#edf2f7", zorder=0)
        ax.axhline(100, linestyle="--", color=MUTED, linewidth=1)
        ax.plot(samples["elapsed_seconds"], utilization, color=color, linewidth=1.8)
        ax.set_title(f"Quota de {limit} CPUs", loc="left", fontsize=12)
        ax.set_xlabel("Tempo desde o início do cenário (s)")
        ax.set_ylabel("Utilização da quota (%)")
        ax.set_xlim(0, 62)
        ax.set_ylim(0, max(118, utilization.max() * 1.08))
        ax.grid(axis="y", color="#e6ebf2")
    heading(fig, "CPU ao longo de cada cenário", "100% = toda a quota disponível · área sombreada = janela usada na média de CPU")
    fig.subplots_adjust(left=0.08, right=0.97, bottom=0.19, top=0.83, hspace=0.48, wspace=0.22)
    save(fig, output, "cpu_ao_longo_do_tempo")


def plot_scaling(data: pd.DataFrame, output: Path) -> None:
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.plot(data["cpu_limit"], data["speedup_vs_2_cpu"], marker="o", linewidth=2.5,
            markersize=8, color="#2563a6", label="Ganho observado")
    ax.plot(data["cpu_limit"], data["cpu_limit"] / 2, linestyle="--", color=MUTED,
            label="Referência proporcional à quota")
    for _, row in data.iterrows():
        ax.annotate(decimal(row["speedup_vs_2_cpu"]) + "×",
                    (row["cpu_limit"], row["speedup_vs_2_cpu"]), xytext=(0, 10),
                    textcoords="offset points", ha="center", fontsize=11)
    ax.set_xticks(data["cpu_limit"])
    ax.set_xlim(1.7, 8.3)
    ax.set_ylim(0, data["speedup_vs_2_cpu"].max() * 1.22)
    ax.set_xlabel("Quota de CPU do container")
    ax.set_ylabel("Vazão relativa ao cenário de 2 CPUs")
    ax.grid(axis="y", color="#e6ebf2")
    ax.legend(frameon=False, loc="upper left", fontsize=10)
    heading(fig, "Ganho de vazão observado", "Base: 2 CPUs = 1× · a referência proporcional não é uma previsão de desempenho")
    fig.text(0.08, 0.135, "O salto em 8 CPUs exige repetição e controle de energia, escalonamento e SMT.",
             color=MUTED, fontsize=9)
    fig.subplots_adjust(left=0.10, right=0.96, bottom=0.25, top=0.81)
    save(fig, output, "ganho_de_vazao")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "results/cpu-scaling-2-4-6-8")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.input / "graficos"
    data = pd.read_csv(args.input / "comparison.csv").sort_values("cpu_limit").reset_index(drop=True)
    if data["cpu_limit"].tolist() != [2, 4, 6, 8]:
        parser.error("São esperados os quatro casos: 2, 4, 6 e 8 CPUs")
    required = ["workers", "users", "requests_per_second", "average_latency_ms",
                "p95_latency_ms", "allocated_cpu_utilization_percent", "memory_max_mib"]
    if data[required].isna().any().any() or (data[required] < 0).any().any():
        parser.error("Dados ausentes ou negativos nas métricas necessárias")
    if not data["workers"].eq(8).all() or not data["users"].eq(32).all():
        parser.error("Este relatório espera oito workers e 32 usuários em todos os casos")
    data["average_latency_seconds"] = data["average_latency_ms"] / 1000
    data["p95_latency_seconds"] = data["p95_latency_ms"] / 1000
    data["speedup_vs_2_cpu"] = data["requests_per_second"] / data.loc[0, "requests_per_second"]
    output.mkdir(parents=True, exist_ok=True)
    data.to_csv(output / "dados_dos_graficos.csv", index=False)
    style()
    charts = [("vazao", throughput), ("latencia", latency), ("cpu", cpu), ("memoria", memory)]
    subtitle = "RAM: 1 GiB · 8 workers · 32 usuários · 10 MiB × 100 iterações · espera zero"
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    for ax, (_, plot) in zip(axes.flat, charts):
        plot(ax, data)
    heading(fig, "Desempenho por quota de CPU", subtitle)
    fig.subplots_adjust(left=0.08, right=0.97, bottom=0.17, top=0.85, hspace=0.45, wspace=0.25)
    save(fig, output, "painel_comparativo")
    for name, plot in charts:
        fig, ax = plt.subplots(figsize=(9, 6))
        plot(ax, data)
        heading(fig, "Piloto Docker · 2, 4, 6 e 8 CPUs", subtitle)
        fig.subplots_adjust(left=0.12, right=0.97, bottom=0.22, top=0.77)
        save(fig, output, name)
    plot_timelines(args.input, output, data)
    plot_scaling(data, output)
    print(f"Gerados 7 gráficos em PNG, SVG e PDF, mais CSV tratado, em {output.resolve()}")


if __name__ == "__main__":
    main()

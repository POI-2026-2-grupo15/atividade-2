"""Generate report-ready plots from the raw VirtualBox CPU-bound runs."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

if __package__:
    from .virtualbox_analysis import CPUS, ExperimentData, load_experiments, summarize_selected
else:
    from virtualbox_analysis import CPUS, ExperimentData, load_experiments, summarize_selected


ROOT = Path(__file__).resolve().parents[1]
FIGURE_NAMES = (
    "painel_comparativo",
    "variacao_repeticoes",
    "ganho_eficiencia",
    "cpu_ao_longo_do_tempo",
    "vazao_ao_longo_do_tempo",
    "ram_ao_longo_do_tempo",
)
COLORS = {1: "#244f9e", 2: "#0d8385", 4: "#8054a5", 6: "#c47b19", 8: "#c34357"}
INK = "#203047"
MUTED = "#59677a"


def _style() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "text.color": INK, "axes.labelcolor": INK, "axes.titlecolor": INK,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#cbd4df", "axes.axisbelow": True,
        "axes.titleweight": "bold", "axes.titlepad": 12,
        "xtick.color": MUTED, "ytick.color": MUTED,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "svg.fonttype": "none", "pdf.fonttype": 42,
    })


def _decimal(value: float, places: int = 2) -> str:
    return f"{value:.{places}f}".replace(".", ",")


def _label_axes(ax: plt.Axes, title: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=12)
    ax.set_xlabel("vCPUs da VM")
    ax.set_ylabel(ylabel)
    ax.set_xticks(CPUS)
    ax.grid(axis="y", color="#e6ebf2", linewidth=0.8)


def _finish(fig: plt.Figure, title: str, note: str) -> None:
    fig.suptitle(title, x=0.06, ha="left", fontsize=17, fontweight="bold")
    fig.text(0.06, 0.025, note, fontsize=8.5, color=MUTED, va="bottom")
    fig.tight_layout(rect=(0.04, 0.08, 0.99, 0.92))


def _save(fig: plt.Figure, output: Path, name: str) -> list[Path]:
    paths = []
    for extension in ("png", "svg", "pdf"):
        target = output / f"{name}.{extension}"
        fig.savefig(target, dpi=190, bbox_inches="tight")
        paths.append(target)
    plt.close(fig)
    return paths


def _panel(summary: pd.DataFrame) -> plt.Figure:
    fig, axes = plt.subplots(2, 2, figsize=(13, 9))
    axes = axes.flat
    colors = [COLORS[cpu] for cpu in summary.cpu]

    ax = next(axes)
    bars = ax.bar(summary.cpu, summary.requests_per_second, color=colors, width=0.65)
    ax.bar_label(bars, labels=[_decimal(value) for value in summary.requests_per_second], padding=4)
    _label_axes(ax, "Vazão mediana", "Requisições/s")
    ax.set_ylim(0, summary.requests_per_second.max() * 1.28)

    ax = next(axes)
    positions = summary.cpu.astype(float)
    avg = ax.bar(positions - 0.17, summary.average_latency_ms / 1000, width=0.32,
                 color="#244f9e", label="Média")
    p95 = ax.bar(positions + 0.17, summary.p95_latency_ms / 1000, width=0.32,
                 color="#c47b19", label="p95")
    ax.bar_label(avg, labels=[_decimal(v, 1) for v in summary.average_latency_ms / 1000], padding=3, fontsize=8)
    ax.bar_label(p95, labels=[_decimal(v, 1) for v in summary.p95_latency_ms / 1000], padding=3, fontsize=8)
    _label_axes(ax, "Latência HTTP mediana", "Segundos")
    ax.set_ylim(0, (summary.p95_latency_ms / 1000).max() * 1.3)
    ax.legend(frameon=False, ncol=2)

    ax = next(axes)
    bars = ax.bar(summary.cpu, summary.cpu_percent, color=colors, width=0.65)
    ax.bar_label(bars, labels=[_decimal(v, 1) + "%" for v in summary.cpu_percent], padding=4, fontsize=8)
    ax.axhline(100, color=MUTED, linewidth=1, linestyle="--")
    _label_axes(ax, "CPU durante a carga", "Utilização média da VM (%)")
    ax.set_ylim(0, 116)

    ax = next(axes)
    bars = ax.bar(summary.cpu, summary.ram_max_mib, color=colors, width=0.65)
    ax.bar_label(bars, labels=[_decimal(v, 0) for v in summary.ram_max_mib], padding=4, fontsize=9)
    ax.axhline(1024, color=MUTED, linewidth=1, linestyle="--", label="RAM configurada: 1.024 MiB")
    _label_axes(ax, "Memória durante a carga", "Mediana do pico de RAM (MiB)")
    ax.set_ylim(0, 1170)
    ax.legend(frameon=False, fontsize=8)

    _finish(fig, "Desempenho no VirtualBox · 1 a 8 vCPUs",
            "15 execuções selecionadas: mediana de 3 por vCPU · 8 workers · 32 usuários · 60 s · 10 MiB × 100 iterações")
    return fig


def _variation(runs: pd.DataFrame, summary: pd.DataFrame) -> plt.Figure:
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    chosen = runs.loc[runs.selected]
    for ax, metric, title, ylabel, factor in (
        (axes[0], "requests_per_second", "Vazão por repetição", "Requisições/s", 1),
        (axes[1], "p95_latency_ms", "p95 por repetição", "Segundos", 1000),
    ):
        for cpu in CPUS:
            points = chosen.loc[chosen.cpu.eq(cpu)].sort_values("rep")
            xs = [cpu - 0.13, cpu, cpu + 0.13]
            ax.scatter(xs, points[metric] / factor, color=COLORS[cpu], s=58, zorder=3,
                       label=f"{cpu} vCPU" if ax is axes[0] else None)
            median = float(summary.loc[summary.cpu.eq(cpu), metric].iloc[0] / factor)
            ax.hlines(median, cpu - 0.24, cpu + 0.24, color=INK, linewidth=2.3, zorder=4)
        _label_axes(ax, title, ylabel)
        ax.set_ylim(bottom=0)
    axes[0].legend(frameon=False, ncol=3, fontsize=8, loc="upper left")
    _finish(fig, "Variação entre as três repetições válidas",
            "Cada ponto = uma execução · traço escuro = mediana · sem intervalo de confiança inferencial")
    return fig


def _scaling(summary: pd.DataFrame) -> plt.Figure:
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.5))
    base = float(summary.loc[summary.cpu.eq(1), "requests_per_second"].iloc[0])
    speedup = summary.requests_per_second / base
    efficiency = 100 * speedup / summary.cpu
    axes[0].plot(summary.cpu, speedup, marker="o", markersize=8, linewidth=2.2,
                 color="#244f9e", label="Observado")
    axes[0].plot(summary.cpu, summary.cpu, linestyle="--", color=MUTED,
                 label="Referência linear")
    _label_axes(axes[0], "Ganho de vazão relativo a 1 vCPU", "Ganho (×)")
    axes[0].legend(frameon=False)
    bars = axes[1].bar(summary.cpu, efficiency, color=[COLORS[c] for c in summary.cpu], width=0.65)
    axes[1].bar_label(bars, labels=[_decimal(v, 0) + "%" for v in efficiency], padding=4)
    _label_axes(axes[1], "Eficiência relativa", "Ganho observado / vCPUs (%)")
    axes[1].set_ylim(0, max(115, efficiency.max() * 1.2))
    _finish(fig, "Escalonamento da vazão",
            "Base: mediana de 1 vCPU = 1× · linha linear é referência matemática, não previsão de desempenho")
    return fig


def _timelines(frame: pd.DataFrame, metric: str, title: str, ylabel: str, limits: tuple[float, float] | None = None) -> plt.Figure:
    fig, axes = plt.subplots(len(CPUS), 1, figsize=(12, 12), sharex=True)
    for cpu, ax in zip(CPUS, axes):
        case = frame.loc[frame.cpu.eq(cpu)]
        if case.empty:
            raise ValueError(f"Histórico vazio para {cpu} vCPUs: {title}")
        for rep, points in case.groupby("rep"):
            points = points.sort_values("seconds_from_start")
            ax.plot(points.seconds_from_start, points[metric], color=COLORS[cpu],
                    alpha=0.54, linewidth=1.8, label=f"rep{rep}")
        ax.set_title(f"{cpu} vCPU" if cpu == 1 else f"{cpu} vCPUs", loc="left", fontsize=11)
        ax.set_ylabel(ylabel)
        ax.set_xlim(0, 60)
        if limits is not None:
            ax.set_ylim(*limits)
        else:
            ax.set_ylim(bottom=0)
        ax.grid(axis="y", color="#e6ebf2", linewidth=0.8)
        ax.legend(frameon=False, ncol=3, fontsize=8, loc="lower right")
    axes[-1].set_xlabel("Segundos desde o início do Locust")
    _finish(fig, title,
            "Três curvas por cenário · somente amostras dentro da janela real de carga · séries não são totais finais")
    return fig


def generate_figures(data: ExperimentData, summary: pd.DataFrame, output: Path) -> list[Path]:
    """Write 18 image files and the three audit/summary CSVs."""
    if summary.cpu.tolist() != list(CPUS):
        raise ValueError(f"O resumo deve conter exatamente {CPUS}")
    if data.runs.selected.sum() != 15 or data.monitor.empty or data.history.empty:
        raise ValueError("São esperadas 15 repetições selecionadas com monitor e histórico")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    data.runs.sort_values(["cpu", "rep"]).to_csv(output / "repeticoes.csv", index=False)
    summary.to_csv(output / "resumo_por_cpu.csv", index=False)
    data.audit.sort_values(["cpu", "rep"]).to_csv(output / "auditoria.csv", index=False)

    _style()
    figures = [
        _panel(summary),
        _variation(data.runs, summary),
        _scaling(summary),
        _timelines(data.monitor, "system_cpu_percent", "Utilização de CPU durante a carga", "CPU da VM (%)", (0, 110)),
        _timelines(data.history, "requests_per_second", "Vazão observada ao longo do teste", "Requisições/s"),
        _timelines(data.monitor, "ram_used_mib", "RAM usada durante a carga", "RAM da VM (MiB)"),
    ]
    created = []
    for name, fig in zip(FIGURE_NAMES, figures):
        created.extend(_save(fig, output, name))
    return created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "results", help="Pasta que contém os diretórios vbox-*cpu-*")
    parser.add_argument("--output", type=Path, default=ROOT / "results/virtualbox-graficos", help="Pasta de imagens e CSVs gerados")
    args = parser.parse_args()
    try:
        data = load_experiments(args.input)
        summary = summarize_selected(data.runs)
        created = generate_figures(data, summary, args.output)
    except (FileNotFoundError, ValueError) as exc:
        parser.error(str(exc))
    print(summary.to_string(index=False))
    print(f"Gerados {len(created)} arquivos de figura e 3 CSVs em {args.output.resolve()}")


if __name__ == "__main__":
    main()

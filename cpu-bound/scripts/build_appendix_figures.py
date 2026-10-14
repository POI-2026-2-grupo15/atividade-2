"""Regenera os esquemas explicativos do apêndice da matriz CPU-bound."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/figuras/cpu-bound"


def box(ax, x, y, width, height, title, body, color):
    ax.add_patch(FancyBboxPatch(
        (x, y), width, height, boxstyle="round,pad=0.015,rounding_size=0.025",
        linewidth=1.2, edgecolor=color, facecolor="#f7fafc",
    ))
    ax.text(x + 0.025, y + height - 0.065, title, color=color,
            fontsize=12, fontweight="bold", va="top")
    ax.text(x + 0.025, y + height - 0.135, body,
            color="#263238", fontsize=10, va="top", linespacing=1.5)


def save(fig, stem):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for suffix in ("png", "svg"):
        fig.savefig(OUTPUT / f"{stem}.{suffix}", dpi=220,
                    bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main():
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.suptitle("Execução e conferência de uma bateria de demanda",
                 fontsize=17, fontweight="bold", color="#17324d")
    items = [
        (0.03, "1. Preparar", "vCPUs e 1 GiB de RAM\nAPI com 8 workers\n/health e SSH ativos", "#1f77b4"),
        (0.275, "2. Executar", "script de bateria\n1, 2, 4, 8 e 16 usuários\n3 × 120 s por nível", "#e07b24"),
        (0.52, "3. Coletar", "Locust no hospedeiro\nmonitor + vmstat na VM\n15 pastas por cenário", "#2a8f72"),
        (0.765, "4. Analisar", "script de análise\nauditoria.csv + tabelas\nfiguras PNG e SVG", "#7953a6"),
    ]
    for x, title, body, color in items:
        box(ax, x, 0.32, 0.205, 0.47, title, body, color)
    for x in (0.238, 0.483, 0.728):
        ax.add_patch(FancyArrowPatch((x, 0.55), (x + 0.032, 0.55),
                                     arrowstyle="-|>", mutation_scale=18,
                                     linewidth=1.5, color="#536575"))
    ax.text(0.5, 0.18, "Os cinco cenários foram executados em sequência; os arquivos originais permanecem em results/.",
            ha="center", fontsize=10, color="#536575")
    save(fig, "apendice-fluxo-execucao")

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    fig.suptitle("Organização dos dados de uma bateria",
                 fontsize=17, fontweight="bold", color="#17324d")
    box(ax, 0.04, 0.62, 0.42, 0.24, "Pasta do cenário", "demand-vbox-<vcpus>cpu-<UTC>/\nmanifest.json · inventários · resumo", "#1f77b4")
    box(ax, 0.54, 0.62, 0.42, 0.24, "Cinco níveis de demanda", "u1/ · u2/ · u4/ · u8/ · u16/\nCada nível contém rep1/ · rep2/ · rep3/", "#e07b24")
    box(ax, 0.04, 0.18, 0.42, 0.29, "Em cada repetição: carga", "requests.csv · locust_stats.csv\nlocust_stats_history.csv · locust.log\nconfig.txt · dependencies.txt · run-status.json", "#2a8f72")
    box(ax, 0.54, 0.18, 0.42, 0.29, "Em cada repetição: VM", "monitor.csv · vmstat.txt · monitor.log\nCPU, RAM e swap registrados no convidado\nCópias reunidas na pasta do hospedeiro", "#7953a6")
    for start, end in [((0.46, 0.74), (0.535, 0.74)), ((0.75, 0.61), (0.75, 0.48))]:
        ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>",
                                     mutation_scale=18, linewidth=1.5, color="#536575"))
    save(fig, "apendice-organizacao-dados")


if __name__ == "__main__":
    main()

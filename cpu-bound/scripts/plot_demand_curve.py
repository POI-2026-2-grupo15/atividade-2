import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter
import pandas as pd

from plot_results import COLORS, INK, MUTED, decimal, style

ROOT = Path(__file__).resolve().parents[1]
CPUS = [2, 4, 6, 8]
USERS = [1, 2, 4, 8, 16, 32]
THRESHOLD = 95.0


def read_results(source: Path) -> pd.DataFrame:
    records = []
    power_states = set()
    for cpu in CPUS:
        case = source / f"cpu-{cpu}"
        results = json.loads((case / "summary.json").read_text())
        for result in results:
            samples = pd.read_csv(case / f"users-{result['users']}" / "resources.csv")
            power_states.update(str(value) for value in samples.host_power_plugged.dropna().unique())
        records.extend(results)
    if len(power_states) > 1:
        raise ValueError("A matriz mistura bateria e tomada; use a coleta refeita com alimentação constante")
    frame = pd.DataFrame(records).sort_values(["cpu_limit", "users"])
    expected = {(cpu, users) for cpu in CPUS for users in USERS}
    actual = set(zip(frame.cpu_limit, frame.users))
    if actual != expected or len(frame) != len(expected):
        raise ValueError("A matriz deve conter exatamente quatro quotas × seis níveis de usuários")
    frame["average_latency_seconds"] = frame.average_latency_ms / 1000
    frame["p95_latency_seconds"] = frame.p95_latency_ms / 1000
    frame["near_saturation"] = frame.allocated_cpu_utilization_percent >= THRESHOLD
    return frame


def curve(ax, frame: pd.DataFrame, metric: str, title: str, ylabel: str) -> None:
    for cpu, color, marker in zip(CPUS, COLORS, ["o", "s", "^", "D"]):
        points = frame[frame.cpu_limit == cpu]
        ax.plot(points.users, points[metric], color=color, marker=marker,
                linewidth=2, markersize=6, label=f"{cpu} CPUs")
    ax.set_title(title, loc="left", fontsize=13)
    ax.set_xlabel("Usuários simultâneos (escala log₂)")
    ax.set_ylabel(ylabel)
    ax.set_xscale("log", base=2)
    ax.set_xticks(USERS, [str(value) for value in USERS])
    ax.set_xlim(0.85, 37)
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda x, _: decimal(x, 0)))
    ax.grid(axis="y", color="#e6ebf2")
    if metric == "allocated_cpu_utilization_percent":
        ax.set_ylim(0, max(112, frame[metric].max() + 10))
        ax.axhspan(THRESHOLD, ax.get_ylim()[1], color="#fff3dc", zorder=0)
        ax.axhline(THRESHOLD, linestyle="--", color="#ad6d13", linewidth=1)
    ax.legend(frameon=False, ncols=2, fontsize=9, loc="best")


def footer(fig, duration: int) -> None:
    fig.text(0.08, 0.025,
             f"Docker · 1 GiB · 8 workers · 10 MiB × 100 · espera zero · uma execução de {duration} s por ponto.\n"
             f"CPU: média entre 5 e {duration - 2} s; HTTP: snapshot acumulado do Locust. Saturação operacional: média ≥ 95% da quota.\n"
             "Modelo fechado: usuários esperam a resposta. Pool de 7 núcleos físicos com SMT; piloto exploratório, sem intervalos de confiança.",
             fontsize=8.5, color=MUTED, linespacing=1.6)


def save(fig, output: Path, name: str) -> None:
    for extension in ("png", "svg", "pdf"):
        fig.savefig(output / f"{name}.{extension}", dpi=200, bbox_inches="tight")
    plt.close(fig)


def heatmap(frame: pd.DataFrame, output: Path, duration: int) -> None:
    matrix = frame.pivot(index="cpu_limit", columns="users", values="allocated_cpu_utilization_percent").reindex(index=CPUS, columns=USERS)
    fig, ax = plt.subplots(figsize=(11, 6))
    picture = ax.imshow(matrix, cmap="Blues", vmin=0, vmax=100, aspect="auto")
    for row in range(len(CPUS)):
        for column in range(len(USERS)):
            value = matrix.iloc[row, column]
            ax.text(column, row, decimal(value, 1) + "%", ha="center", va="center",
                    color="white" if value >= 60 else INK, fontsize=12, fontweight="bold")
            if value >= THRESHOLD:
                ax.add_patch(Rectangle((column - 0.47, row - 0.46), 0.94, 0.92,
                                       fill=False, edgecolor="#f4b343", linewidth=2.5))
    ax.set_xticks(range(len(USERS)), USERS)
    ax.set_yticks(range(len(CPUS)), [f"{cpu} CPUs" for cpu in CPUS])
    ax.set_xlabel("Usuários simultâneos")
    ax.set_ylabel("Quota do container")
    fig.colorbar(picture, ax=ax, label="Utilização da quota de CPU (%)", pad=0.025)
    fig.suptitle("Onde cada configuração satura?", x=0.08, y=0.98, ha="left", fontsize=19, fontweight="bold")
    fig.text(0.08, 0.905, "Borda dourada: média ≥ 95% da quota · cada célula corresponde a uma medição", color=MUTED)
    footer(fig, duration)
    fig.subplots_adjust(left=0.10, right=0.95, top=0.83, bottom=0.25)
    save(fig, output, "mapa_de_saturacao")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "results/demand-curve-ac")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.input / "graficos"
    frame = read_results(args.input)
    environments = [json.loads((args.input / f"cpu-{cpu}" / "environment.json").read_text()) for cpu in CPUS]
    durations = {env["duration_seconds"] for env in environments}
    if len(durations) != 1:
        raise ValueError("Todos os cenários devem usar a mesma duração")
    duration = durations.pop()
    if not frame.workers.eq(8).all() or any(env["host_config"]["Memory"] != 2**30 for env in environments):
        raise ValueError("Esta comparação requer oito workers e 1 GiB fixos")
    output.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.input / "comparison.csv", index=False)
    frame.pivot(index="cpu_limit", columns="users", values="allocated_cpu_utilization_percent").to_csv(output / "utilizacao_por_demanda.csv")
    thresholds = []
    for cpu in CPUS:
        series = frame[frame.cpu_limit == cpu]
        saturated = series[series.near_saturation]
        first = int(saturated.users.min()) if len(saturated) else None
        thresholds.append({
            "cpu_limit": cpu, "criterion_cpu_percent": THRESHOLD,
            "first_observed_users": first,
            "all_tested_levels_from_first_also_saturated": bool(series[series.users >= first].near_saturation.all()) if first is not None else False,
            "note": "Primeiro nível observado; não é mínimo exato nem limiar garantido em repetições.",
        })
    (output / "limiares_observados.json").write_text(json.dumps(thresholds, indent=2) + "\n")
    style()
    plots = [
        ("cpu_por_demanda", "allocated_cpu_utilization_percent", "Utilização de CPU × demanda", "Utilização da quota (%)"),
        ("vazao_por_demanda", "requests_per_second", "Vazão × demanda", "Requisições por segundo"),
        ("latencia_media_por_demanda", "average_latency_seconds", "Latência média × demanda", "Segundos"),
        ("p95_por_demanda", "p95_latency_seconds", "Latência p95 × demanda", "Segundos"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    for ax, (_, metric, title, ylabel) in zip(axes.flat, plots):
        curve(ax, frame, metric, title, ylabel)
    fig.suptitle("Curva de demanda: da folga à saturação", x=0.08, y=0.98, ha="left", fontsize=19, fontweight="bold")
    fig.text(0.08, 0.925, "Mesma carga por requisição e mesmos recursos por série; apenas o número de usuários aumenta.", color=MUTED)
    footer(fig, duration)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.85, bottom=0.17, hspace=0.48, wspace=0.24)
    save(fig, output, "painel_curva_demanda")
    for name, metric, title, ylabel in plots:
        fig, ax = plt.subplots(figsize=(10, 6))
        curve(ax, frame, metric, title, ylabel)
        footer(fig, duration)
        fig.subplots_adjust(left=0.10, right=0.97, top=0.88, bottom=0.25)
        save(fig, output, name)
    heatmap(frame, output, duration)
    print(frame.pivot(index="cpu_limit", columns="users", values="allocated_cpu_utilization_percent").round(1).to_string())
    print(json.dumps(thresholds, indent=2))
    print(f"Seis gráficos em PNG, SVG e PDF: {output}")


if __name__ == "__main__":
    main()

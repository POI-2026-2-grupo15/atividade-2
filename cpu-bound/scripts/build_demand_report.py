"""Audite a matriz de demanda e regenere tabelas e figuras a partir dos CSVs brutos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.demand_curve_analysis import BASE_USERS, CASE_PATTERN, CPUS, analyse_run, collect_runs
from scripts.virtualbox_analysis import parse_locust_log


CPU_COLORS = {1: "#355C7D", 2: "#C06C46", 4: "#6C9A5B", 6: "#8A6BAA", 8: "#B28A24"}
NUMERIC = ("requests_per_second", "average_latency_ms", "p95_latency_ms",
           "request_count", "failure_count", "cpu_percent", "ram_mean_mib",
           "swap_max_kib", "swap_in_kib", "swap_out_kib")
REQUIRED_FILES = ("config.txt", "dependencies.txt", "requests.csv", "locust.log",
                  "locust_stats.csv", "locust_stats_history.csv", "locust_failures.csv",
                  "locust_exceptions.csv", "monitor.csv", "vmstat.txt", "run-status.json")


def temporal_from_history(path: Path, vcpus: int, users: int, rep: int,
                          *, interval_seconds: int = 5) -> pd.DataFrame:
    """Diferenças dos contadores cumulativos, apenas entre limites observados."""
    frame = pd.read_csv(path)
    required = {"Timestamp", "Name", "Total Request Count", "Total Failure Count"}
    if not required.issubset(frame.columns):
        raise ValueError(f"Histórico incompleto: {path}")
    frame = frame.loc[frame.Name.eq("Aggregated"), list(required)].copy()
    for column in ("Timestamp", "Total Request Count", "Total Failure Count"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame.empty or frame.isna().any().any():
        raise ValueError(f"Histórico inválido: {path}")
    frame = frame.sort_values("Timestamp").drop_duplicates("Timestamp", keep="last")
    if (frame[["Total Request Count", "Total Failure Count"]].diff().dropna() < 0).any().any():
        raise ValueError(f"Contador cumulativo diminuiu: {path}")
    origin = int(frame.Timestamp.iloc[0])
    frame = frame.set_index("Timestamp")
    rows = []
    for end in range(interval_seconds, int(frame.index.max()) - origin + 1, interval_seconds):
        left, right = origin + end - interval_seconds, origin + end
        if left not in frame.index or right not in frame.index:
            continue
        completed = int(frame.loc[right, "Total Request Count"] - frame.loc[left, "Total Request Count"])
        failures = int(frame.loc[right, "Total Failure Count"] - frame.loc[left, "Total Failure Count"])
        rows.append({"vcpus": vcpus, "users": users, "rep": rep,
                     "elapsed_end_seconds": end, "interval_seconds": interval_seconds,
                     "completed_requests": completed, "failures": failures,
                     "requests_per_second": completed / interval_seconds})
    if not rows:
        raise ValueError(f"Nenhum intervalo temporal completo: {path}")
    return pd.DataFrame(rows)


def summarize_temporal(rows: pd.DataFrame) -> pd.DataFrame:
    grouped = rows.groupby(["vcpus", "users", "elapsed_end_seconds"], sort=True)
    result = grouped.requests_per_second.agg(rps_median="median", rps_min="min",
                                             rps_max="max", repetitions="count").reset_index()
    return result.loc[result.repetitions.eq(3)].reset_index(drop=True)


def _locust_duration(path: Path) -> float:
    text = path.read_text(encoding="utf-8")
    starts = re.findall(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+)\].*Starting Locust", text)
    ends = re.findall(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d+)\].*Shutting down", text)
    if len(starts) != 1 or len(ends) != 1 or "Run time limit set to 120 seconds" not in text:
        raise ValueError(f"Duração do Locust não comprovada: {path}")
    return (pd.Timestamp(ends[0]) - pd.Timestamp(starts[0])).total_seconds()


def audit_matrix(cases: list[Path]) -> pd.DataFrame:
    rows = []
    for case in cases:
        case = case.resolve()
        manifest = json.loads((case / "manifest.json").read_text())
        cpu = int(manifest["vcpus"])
        vm_info = (case / "virtualbox-info.txt").read_text()
        guest_info = (case / "guest-inventory.txt").read_text()
        for users in BASE_USERS:
            for rep in (1, 2, 3):
                run = case / f"u{users}" / f"rep{rep}"
                row = {"vcpus": cpu, "users": users, "rep": rep,
                       "directory": str(run.relative_to(ROOT)), "status": "valid", "reason": ""}
                try:
                    if any(not (run / name).is_file() for name in REQUIRED_FILES):
                        raise ValueError("Arquivo obrigatório ausente")
                    if any((run / name).stat().st_size == 0 for name in REQUIRED_FILES):
                        raise ValueError("Arquivo obrigatório vazio")
                    if (f"cpus={cpu}" not in vm_info or "memory=1024" not in vm_info
                            or f"vcpus={cpu}" not in guest_info):
                        raise ValueError("Inventário de VM incompatível")
                    if (manifest["duration_seconds"], manifest["data_size_mb"],
                        manifest["iterations"], manifest["workers"], manifest["ram_mib"],
                        manifest["warmup_seconds"], manifest["cooldown_seconds"]) != (
                            120, 10, 100, 8, 1024, 30, 5):
                        raise ValueError("Manifesto fora da matriz aprovada")
                    duration = _locust_duration(run / "locust.log")
                    if not 118 <= duration <= 123:
                        raise ValueError(f"Duração observada {duration:.1f} s")
                    final = parse_locust_log(run / "locust.log")
                    requests = pd.read_csv(run / "requests.csv")
                    if len(requests) != final["request_count"] or int(requests.failed.sum()) != final["failure_count"]:
                        raise ValueError("Contagens finais divergem entre log e respostas")
                    if pd.to_datetime(requests.timestamp_utc, utc=True, errors="coerce").isna().any():
                        raise ValueError("Timestamp HTTP inválido")
                    measures = analyse_run(run, manifest)
                    temporal_from_history(run / "locust_stats_history.csv", cpu, users, rep)
                    row.update({"locust_duration_seconds": duration,
                                "requests_full_test": len(requests),
                                "failures_full_test": int(requests.failed.sum()),
                                "timeouts_full_test": int(requests.error.fillna("").str.contains(
                                    "timeout|timed out", case=False, regex=True).sum()),
                                "window_seconds": measures["window_seconds"],
                                "window_requests": measures["request_count"],
                                "window_failures": measures["failure_count"],
                                "monitor_samples": measures["monitor_samples"],
                                "cpu_mean_percent": measures["cpu_percent"],
                                "ram_mean_mib": measures["ram_mean_mib"],
                                "swap_max_kib": measures["swap_max_kib"],
                                "swap_in_kib": measures["swap_in_kib"],
                                "swap_out_kib": measures["swap_out_kib"]})
                except (OSError, KeyError, ValueError, TypeError) as exc:
                    row.update(status="invalid", reason=str(exc))
                rows.append(row)
        for extra in case.glob("u*/rep*"):
            if extra.parent.name not in {f"u{u}" for u in BASE_USERS}:
                rows.append({"vcpus": cpu, "users": extra.parent.name,
                             "rep": extra.name, "directory": str(extra.relative_to(ROOT)),
                             "status": "outside_matrix", "reason": "Demanda fora da matriz aprovada"})
    return pd.DataFrame(rows)


def summarize_runs(runs: pd.DataFrame) -> pd.DataFrame:
    grouped = runs.groupby(["vcpus", "users"], sort=True)
    rows = []
    for (cpu, users), case in grouped:
        result = {"vcpus": cpu, "users": users, "repetitions": len(case),
                  "requests_total": int(case.request_count.sum()),
                  "failures_total": int(case.failure_count.sum())}
        for metric in NUMERIC:
            result[f"{metric}_median"] = float(case[metric].median())
            result[f"{metric}_min"] = float(case[metric].min())
            result[f"{metric}_max"] = float(case[metric].max())
        rows.append(result)
    return pd.DataFrame(rows)


def _save(fig: plt.Figure, path: Path) -> None:
    fig.savefig(path.with_suffix(".png"), dpi=260, bbox_inches="tight")
    fig.savefig(path.with_suffix(".svg"), bbox_inches="tight")
    plt.close(fig)


def _line_plot(summary: pd.DataFrame, metric: str, title: str, ylabel: str,
               path: Path, *, cpu_reference: bool = False) -> None:
    fig, ax = plt.subplots(figsize=(8.3, 5.1))
    for cpu in CPUS:
        case = summary.loc[summary.vcpus.eq(cpu)].sort_values("users")
        x = case.users.to_numpy()
        y = case[f"{metric}_median"].to_numpy()
        color = CPU_COLORS[cpu]
        ax.plot(x, y, "o-", color=color, lw=2, markersize=5, label=f"{cpu} vCPU" if cpu == 1 else f"{cpu} vCPUs")
    if cpu_reference:
        ax.axhline(95, color="#555555", ls="--", lw=1, label="95%: referência operacional")
        ax.set_ylim(0, 105)
    else:
        ax.set_ylim(bottom=0)
    ax.set(xlabel="Usuários simultâneos", ylabel=ylabel, title=title)
    ax.set_xticks(BASE_USERS)
    ax.grid(alpha=0.2)
    ax.legend(ncol=2, fontsize=9)
    fig.text(0.01, -0.015, "Fonte: CSVs Locust e monitor da matriz de demanda (14/10/2026). Ponto = mediana de 3 repetições; mínimo e máximo em resumo.csv.", fontsize=8)
    fig.tight_layout()
    _save(fig, path)


def plot_temporal(temporal: pd.DataFrame, figures: Path) -> None:
    for cpu in CPUS:
        case = temporal.loc[temporal.vcpus.eq(cpu)]
        ymax = case.rps_max.max() * 1.1
        fig, axes = plt.subplots(5, 1, figsize=(9, 10.5), sharex=True, sharey=True)
        for ax, users in zip(axes, BASE_USERS):
            level = case.loc[case.users.eq(users)].sort_values("elapsed_end_seconds")
            x = level.elapsed_end_seconds.to_numpy()
            ax.plot(x, level.rps_median.to_numpy(), color=CPU_COLORS[cpu], lw=1.6,
                    label="Mediana das 3 repetições")
            ax.axvline(30, color="#777777", ls="--", lw=0.9,
                       label="Fim do aquecimento (~30 s)" if users == BASE_USERS[0] else None)
            ax.set_title(f"{users} usuário" if users == 1 else f"{users} usuários", loc="left", fontsize=10)
            ax.grid(alpha=0.2)
            ax.set_ylim(0, ymax)
        axes[0].legend(loc="upper right", fontsize=8)
        axes[2].set_ylabel("Requisições concluídas por segundo (req/s)")
        axes[-1].set_xlabel("Tempo desde o primeiro registro do Locust (s)")
        fig.suptitle(f"RPS temporal — {cpu} vCPU" if cpu == 1 else f"RPS temporal — {cpu} vCPUs")
        fig.text(0.01, 0.005, "Fonte: locust_stats_history.csv; diferenças de contadores cumulativos em intervalos observados de 5 s. Linha = mediana de 3 repetições; dispersão no CSV; último registro antes de 120 s.", fontsize=8)
        fig.tight_layout(rect=(0, 0.015, 1, 0.975))
        _save(fig, figures / f"rps-temporal-{cpu}vcpu")


def plot_speedup(summary: pd.DataFrame, figures: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(8, 7), sharex=True)
    baseline = summary.loc[summary.vcpus.eq(1)].set_index("users").requests_per_second_median
    for cpu in CPUS:
        case = summary.loc[summary.vcpus.eq(cpu)].sort_values("users")
        speedup = case.requests_per_second_median.to_numpy() / baseline.loc[case.users].to_numpy()
        axes[0].plot(case.users, speedup, "o-", color=CPU_COLORS[cpu], label=f"{cpu} vCPU" if cpu == 1 else f"{cpu} vCPUs")
        axes[1].plot(case.users, 100 * speedup / cpu, "o-", color=CPU_COLORS[cpu])
    axes[0].set(ylabel="Speedup relativo a 1 vCPU (×)", title="Ganho de vazão e eficiência relativa")
    axes[1].set(xlabel="Usuários simultâneos", ylabel="Eficiência relativa (%)")
    axes[1].set_xticks(BASE_USERS)
    for ax in axes:
        ax.grid(alpha=0.2)
        ax.set_ylim(bottom=0)
    axes[0].legend(ncol=3, fontsize=8)
    fig.text(0.01, 0.005, "Fonte: medianas de vazão por combinação; speedup = R_n/R_1; eficiência = 100 × speedup/n. 1 vCPU usa outra VM.", fontsize=8)
    fig.tight_layout(rect=(0, 0.02, 1, 1))
    _save(fig, figures / "speedup-eficiencia-vs-demanda")


def build(cases: list[Path], output: Path, figures: Path) -> None:
    if output.exists() or figures.exists():
        raise FileExistsError("Diretório derivado já existe; escolha novos --output e --figures para preservar resultados")
    audit = audit_matrix(cases)
    if (audit.status == "invalid").any():
        output.mkdir(parents=True)
        audit.to_csv(output / "auditoria.csv", index=False)
        raise ValueError("Há execuções inválidas; auditoria preservada, gráficos não gerados")
    runs = collect_runs(cases)
    summary = summarize_runs(runs)
    if len(runs) != 75 or len(summary) != 25 or not summary.repetitions.eq(3).all():
        raise ValueError("Matriz incompleta")
    temporal_rows = []
    for case in cases:
        cpu = int(json.loads((case / "manifest.json").read_text())["vcpus"])
        for users in BASE_USERS:
            for rep in (1, 2, 3):
                temporal_rows.append(temporal_from_history(case / f"u{users}" / f"rep{rep}" /
                                                           "locust_stats_history.csv", cpu, users, rep))
    temporal = pd.concat(temporal_rows, ignore_index=True)
    temporal_summary = summarize_temporal(temporal)
    output.mkdir(parents=True)
    figures.mkdir(parents=True)
    audit.to_csv(output / "auditoria.csv", index=False)
    runs.to_csv(output / "repeticoes.csv", index=False)
    summary.to_csv(output / "resumo.csv", index=False)
    temporal.to_csv(output / "rps-temporal-repeticoes.csv", index=False)
    temporal_summary.to_csv(output / "rps-temporal-resumo.csv", index=False)
    charts = (
        ("requests_per_second", "Vazão em função da demanda por provisionamento", "Vazão (req/s)", "vazao-vs-demanda"),
        ("p95_latency_ms", "Latência p95 em função da demanda", "Mediana dos p95 por repetição (ms)", "latencia-p95-vs-demanda"),
        ("average_latency_ms", "Latência média em função da demanda", "Latência média (ms)", "latencia-media-vs-demanda"),
        ("cpu_percent", "Utilização de CPU em função da demanda", "CPU total da VM, normalizada (%)", "cpu-vs-demanda"),
        ("request_count", "Requisições concluídas por nível de demanda", "Requisições concluídas na janela", "requisicoes-totais-vs-demanda"),
        ("ram_mean_mib", "Consumo de RAM em função da demanda", "RAM usada na VM (MiB)", "ram-vs-demanda"),
    )
    for metric, title, ylabel, stem in charts:
        _line_plot(summary, metric, title, ylabel, figures / stem,
                   cpu_reference=metric == "cpu_percent")
    plot_temporal(temporal_summary, figures)
    plot_speedup(summary, figures)


def select_cases(results: Path, explicit: list[Path] | None = None) -> list[Path]:
    if explicit:
        by_cpu = {}
        for case in explicit:
            match = CASE_PATTERN.match(case.name)
            if not case.is_dir() or match is None:
                raise ValueError(f"Diretório de bateria inválido: {case}")
            cpu = int(match.group(1))
            if cpu in by_cpu:
                raise ValueError(f"Mais de uma bateria indicada para {cpu} vCPUs")
            by_cpu[cpu] = case
        if set(by_cpu) != set(CPUS):
            raise ValueError(f"Indique uma bateria para cada provisionamento: {CPUS}")
        return [by_cpu[cpu] for cpu in CPUS]
    cases = []
    for cpu in CPUS:
        found = sorted(results.glob(f"demand-vbox-{cpu}cpu-*"))
        if len(found) != 1:
            raise ValueError(f"Esperada uma bateria definitiva de {cpu} vCPUs; encontradas {len(found)}. Use --case para selecioná-la.")
        cases.append(found[0])
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=ROOT / "results")
    parser.add_argument("--output", type=Path, default=ROOT / "results" / "demand-vbox-analysis")
    parser.add_argument("--figures", type=Path, default=ROOT / "docs" / "figuras" / "cpu-bound")
    parser.add_argument("--case", type=Path, action="append", help="Pasta de uma bateria definitiva; repita para os cinco provisionamentos")
    args = parser.parse_args()
    try:
        cases = select_cases(args.results, args.case)
    except ValueError as exc:
        parser.error(str(exc))
    build(cases, args.output, args.figures)
    print(f"Análise: {args.output}\nFiguras: {args.figures}")


if __name__ == "__main__":
    main()

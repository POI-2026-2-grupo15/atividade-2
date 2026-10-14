"""Audita as coletas e produz tabelas/gráficos a partir de execuções independentes."""

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics

os.environ.setdefault('MPLCONFIGDIR', '/tmp/memory-bound-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

PROJECT = Path(__file__).resolve().parents[1]
COLORS = {500: '#D55E00', 1024: '#E69F00', 2048: '#009E73', 4096: '#0072B2'}
LABELS = {500: '500 MiB', 1024: '1 GiB', 2048: '2 GiB', 4096: '4 GiB'}
METRICS = ['success_rps', 'mean_ms', 'p95_ms', 'failure_percent', 'cpu_percent_of_limit',
           'memory_peak_mib', 'app_rss_peak_mib', 'generator_cpu_percent_of_one_core',
           'in_flight_at_end', 'oom_kill_total', 'sampled_oom_kill_delta', 'latency_samples']
RESOURCE_METRICS = {'cpu_percent_of_limit', 'memory_peak_mib', 'app_rss_peak_mib', 'sampled_oom_kill_delta'}


def save_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def save_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(key for row in rows for key in row))
    with path.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def audit_point(point, row, environment):
    issues = []
    checks = 0
    inspect = json.loads((point / 'container.json').read_text())
    for condition, message in (
        (inspect['HostConfig']['Memory'] == row['ram_mib'] * 2**20, 'limite de RAM divergente'),
        (inspect['HostConfig']['MemorySwap'] == inspect['HostConfig']['Memory'], 'swap não desabilitado'),
        (inspect['HostConfig']['NanoCpus'] == int(row['cpus'] * 1e9), 'quota CPU divergente'),
        (inspect['Image'] == environment['image']['Id'], 'imagem diverge da identidade inicial'),
    ):
        checks += 1
        if not condition:
            issues.append(message)
    command = inspect['Config']['Cmd']
    worker_value = command[command.index('--workers') + 1] if '--workers' in command else None
    checks += 1
    if worker_value != str(row['workers']):
        issues.append('número de workers diverge do comando efetivo')
    if row.get('complete'):
        checks += 1
        if json.loads((point / 'load/dataset-manifest.json').read_text()) != environment['dataset_manifest']:
            issues.append('manifesto do dataset diverge da preparação inicial')
        meter = json.loads((point / 'load/measurement.json').read_text())
        with (point / 'load/requests.csv').open() as handle:
            records = list(csv.DictReader(handle))
        inside = [r for r in records if meter['start_epoch'] <= float(r['completed_epoch']) < meter['end_epoch']]
        valid_latencies = [float(r['response_time_ms']) for r in inside
                           if float(r['started_epoch']) >= meter['start_epoch'] and r['failure'] == '0']
        checks += 6
        if len(inside) != meter['requests']:
            issues.append('contagem de conclusões diverge do CSV')
        if sum(int(r['failure']) for r in inside) != meter['failures']:
            issues.append('contagem de falhas diverge do CSV')
        if len(valid_latencies) != meter['latency_samples']:
            issues.append('amostra de latência diverge do CSV')
        expected_mean = statistics.mean(valid_latencies) if valid_latencies else None
        if expected_mean != meter['mean_ms']:
            issues.append('média de latência diverge do CSV')
        if not math.isclose(meter['end_epoch'] - meter['start_epoch'], meter['duration_seconds'], abs_tol=1e-5):
            issues.append('duração da janela divergente')
        expected_rps = (meter['requests'] - meter['failures']) / meter['duration_seconds']
        if not math.isclose(expected_rps, meter['success_rps']):
            issues.append('vazão diverge da janela')
        checks += 4
        ordered = sorted(valid_latencies)
        expected_p95 = ordered[math.ceil(len(ordered) * 0.95) - 1] if ordered else None
        if expected_p95 != meter['p95_ms']:
            issues.append('p95 diverge dos registros individuais')
        with (point / 'monitor.csv').open() as handle:
            samples = [r for r in csv.DictReader(handle)
                       if meter['start_epoch'] <= datetime.fromisoformat(r['timestamp_utc']).timestamp() <= meter['end_epoch']]
        if len(samples) != row['resource_samples']:
            issues.append('número de amostras de recursos divergente')
        expected_memory = max(float(r['container_memory_bytes']) for r in samples) / 2**20 if samples else None
        if expected_memory != row['memory_peak_mib']:
            issues.append('pico de memória diverge do CSV')
        expected_cpu = None
        if len(samples) >= 2:
            elapsed = float(samples[-1]['elapsed_seconds']) - float(samples[0]['elapsed_seconds'])
            expected_cpu = (int(samples[-1]['container_cpu_usage_usec']) - int(samples[0]['container_cpu_usage_usec'])) / elapsed / (row['cpus'] * 10000)
        actual_cpu = row['cpu_percent_of_limit']
        if (expected_cpu is None) != (actual_cpu is None) or (expected_cpu is not None and not math.isclose(expected_cpu, actual_cpu, abs_tol=1e-9)):
            issues.append('CPU diverge do contador cgroup')
    return {'point': point.name, 'checks': checks, 'issues': issues}


def aggregate(rows):
    grouped = []
    for ram in sorted({r['ram_mib'] for r in rows}):
        for users in sorted({r['users'] for r in rows}):
            subset = [r for r in rows if r['ram_mib'] == ram and r['users'] == users]
            if not subset:
                continue
            result = {'ram_mib': ram, 'users': users, 'runs': len(subset),
                      'complete_windows': sum(bool(r.get('complete')) for r in subset),
                      'covered_resource_windows': sum(bool(r.get('resource_window_covered')) for r in subset),
                      'oom_runs': sum(bool(r.get('oom_kill_total')) or r.get('container_oom_killed', False) for r in subset)}
            for metric in METRICS:
                values = [float(r[metric]) for r in subset if r.get(metric) is not None
                          and (metric not in RESOURCE_METRICS or r.get('resource_window_covered'))]
                result[metric + '_n'] = len(values)
                result[metric + '_mean'] = statistics.mean(values) if values else None
                result[metric + '_sd'] = statistics.stdev(values) if len(values) > 1 else None
                result[metric + '_min'] = min(values) if values else None
                result[metric + '_max'] = max(values) if values else None
            grouped.append(result)
    return grouped


def decorate(ax, title, ylabel):
    ax.set_title(title, loc='left', fontsize=12, fontweight='bold', pad=12)
    ax.set_xlabel('Usuários simultâneos')
    ax.set_ylabel(ylabel)
    ax.set_xscale('log', base=2)
    ax.set_xticks([1, 2, 4, 8], labels=['1', '2', '4', '8'])
    ax.grid(axis='y', alpha=0.2)
    ax.spines[['top', 'right']].set_visible(False)


def draw_curve(ax, rows, groups, metric, scale=1):
    for ram in sorted({r['ram_mib'] for r in rows}):
        points = sorted([g for g in groups if g['ram_mib'] == ram], key=lambda g: g['users'])
        x = [g['users'] for g in points]
        y = [g[metric + '_mean'] * scale if g[metric + '_mean'] is not None else np.nan for g in points]
        sd = [g[metric + '_sd'] * scale if g[metric + '_sd'] is not None else np.nan for g in points]
        ax.errorbar(x, y, yerr=sd, marker='o', capsize=3, linewidth=1.7,
                    color=COLORS[ram], label=LABELS[ram], markersize=5)
        for row in rows:
            if row['ram_mib'] == ram and row.get(metric) is not None and metric in RESOURCE_METRICS and not row.get('resource_window_covered'):
                ax.scatter(row['users'], row[metric] * scale, color=COLORS[ram], marker='x', s=35, alpha=0.8)
            if row['ram_mib'] == ram and row.get(metric) is not None and (metric not in RESOURCE_METRICS or row.get('resource_window_covered')):
                jitter = 2 ** ((row['repetition'] - 2) * 0.025)
                ax.scatter(row['users'] * jitter, row[metric] * scale, color=COLORS[ram], s=17, alpha=0.4)


def save_plot(fig, output, name):
    fig.savefig(output / f'{name}.png', dpi=200, bbox_inches='tight')
    fig.savefig(output / f'{name}.svg', bbox_inches='tight')
    plt.close(fig)


def figures(rows, groups, output):
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10, 'axes.labelsize': 10,
                         'figure.facecolor': 'white', 'savefig.facecolor': 'white'})
    definitions = [
        ('vazao', 'success_rps', 'Vazão de respostas válidas', 'Requisições por segundo', 1),
        ('latencia', 'mean_ms', 'Latência média das respostas válidas', 'Segundos', 0.001),
        ('p95', 'p95_ms', 'Percentil 95 das respostas válidas', 'Segundos', 0.001),
        ('cpu', 'cpu_percent_of_limit', 'Utilização de CPU do container', '% da quota de 6 CPUs', 1),
        ('memoria', 'memory_peak_mib', 'Pico de memória amostrado na janela', 'MiB no cgroup', 1),
        ('falhas', 'failure_percent', 'Falhas nas respostas concluídas', '% das respostas na janela', 1),
        ('oom', 'oom_kill_total', 'Mortes por falta de memória', 'Eventos OOM kill no ponto inteiro', 1),
        ('pendentes', 'in_flight_at_end', 'Requisições pendentes no fim da janela', 'Requisições censuradas', 1),
    ]
    for name, metric, title, ylabel, scale in definitions:
        fig, ax = plt.subplots(figsize=(6.8, 3.5))
        draw_curve(ax, rows, groups, metric, scale)
        decorate(ax, title, ylabel)
        ax.set_ylim(bottom=0)
        if metric in ('failure_percent', 'cpu_percent_of_limit'):
            ax.set_ylim(0, 105)
        ax.legend(ncol=2, loc='best', fontsize=9, frameon=False)
        note = ('Média ± desvio padrão; × = coleta com lacunas, fora da média.' if metric in RESOURCE_METRICS
                else 'Média ± desvio padrão entre repetições; pontos claros = execuções individuais.')
        fig.subplots_adjust(bottom=0.23)
        fig.text(0.12, 0.015, note, fontsize=8, color='#444444')
        save_plot(fig, output, name)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8))
    for ax, spec in zip(axes.flat, [definitions[0], definitions[1], definitions[3], definitions[4]]):
        _, metric, title, ylabel, scale = spec
        draw_curve(ax, rows, groups, metric, scale)
        decorate(ax, title, ylabel)
        ax.set_ylim(bottom=0)
    axes[0, 0].legend(ncol=4, frameon=False, fontsize=9)
    fig.tight_layout(pad=2)
    save_plot(fig, output, 'painel')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=PROJECT / 'output/analysis')
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    plan = json.loads((args.input / 'plan.json').read_text())
    summaries = sorted(args.input.glob('rep*/summary.json'))
    rows = [json.loads(path.read_text()) for path in summaries]
    wanted = Counter((r['repetition'], r['ram_mib'], r['users']) for r in plan['runs'])
    received = Counter((r['repetition'], r['ram_mib'], r['users']) for r in rows)
    if (wanted != received or any(r.get('status') == 'incomplete_window' for r in rows)) and not args.allow_partial:
        raise SystemExit('Matriz incompleta: use --allow-partial somente para inspeção provisória')
    args.output.mkdir(parents=True, exist_ok=True)
    environment = json.loads((args.input / 'environment.json').read_text())
    audits = [audit_point(path.parent, row, environment) for path, row in zip(summaries, rows)]
    for row in rows:
        row['failure_percent'] = row['failures'] / row['requests'] * 100 if row.get('requests') else None
        events = row.get('memory_events_final')
        row['oom_kill_total'] = events.get('oom_kill') if events is not None else None
        row['source_point'] = str((args.input / f"rep{row['repetition']}-ram{row['ram_mib']}-u{row['users']}").resolve())
    issues = [entry for entry in audits if entry['issues']]
    audit = {'expected_runs': len(plan['runs']), 'observed_runs': len(rows), 'complete_matrix': wanted == received,
             'checks': sum(entry['checks'] for entry in audits), 'issues': issues,
             'statuses': dict(Counter(r['status'] for r in rows)),
             'incomplete_resource_windows': [r['source_point'] for r in rows if r.get('complete') and not r.get('resource_window_covered')],
             'input': str(args.input.resolve()), 'created_utc': datetime.now(timezone.utc).isoformat()}
    save_json(args.output / 'audit.json', audit)
    if issues:
        raise SystemExit('Auditoria encontrou divergências; confira audit.json antes de interpretar os resultados')
    groups = aggregate(rows)
    save_json(args.output / 'runs.json', rows)
    save_json(args.output / 'comparison.json', groups)
    save_csv(args.output / 'runs.csv', rows)
    save_csv(args.output / 'comparison.csv', groups)
    save_json(args.output / 'provenance.json', {
        'input': str(args.input.resolve()), 'environment': environment,
        'analysis_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'matplotlib': matplotlib.__version__, 'numpy': np.__version__,
        'host_observation': json.loads((args.input / 'host-observation.json').read_text()) if (args.input / 'host-observation.json').exists() else None,
    })
    figures(rows, groups, args.output)
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    main()

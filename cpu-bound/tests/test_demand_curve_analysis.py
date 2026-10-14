from datetime import datetime, timedelta, timezone
import json

import pandas as pd
import pytest

from scripts.demand_curve_analysis import analyse_run, collect_runs, summarize_runs


BASE = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
MANIFEST = {
    "vcpus": 1, "users": [1, 2, 4, 8, 16], "repetitions": 3,
    "duration_seconds": 120, "data_size_mb": 10, "iterations": 100,
    "spawn_rate": 32, "wait_seconds": 0, "workers": 8, "ram_mib": 1024,
    "warmup_seconds": 30, "cooldown_seconds": 5, "smoke": False,
    "vm_provenance": "separate-1cpu-vm",
}


def _fixture_run(tmp_path, *, monitor_rows=121):
    run = tmp_path / "u1" / "rep1"
    run.mkdir(parents=True)
    history = pd.DataFrame({
        "Timestamp": [(BASE + timedelta(seconds=second)).timestamp() for second in range(121)],
        "User Count": [1] * 121, "Name": ["Aggregated"] * 121,
    })
    history.to_csv(run / "locust_stats_history.csv", index=False)
    pd.DataFrame([
        {"timestamp_utc": (BASE + timedelta(seconds=second)).isoformat(),
         "system_cpu_percent": 50, "app_cpu_percent": 45,
         "ram_used_bytes": 512 * 2**20, "ram_available_bytes": 512 * 2**20,
         "system_cpu_per_core_percent": "[50.0]"}
        for second in range(monitor_rows)
    ]).to_csv(run / "monitor.csv", index=False)
    pd.DataFrame([
        {"timestamp_utc": (BASE + timedelta(seconds=end)).isoformat(),
         "started_utc": (BASE + timedelta(seconds=end) - timedelta(milliseconds=latency)).isoformat(),
         "method": "POST", "name": "/benchmark", "response_time_ms": latency,
         "failed": failed, "error": "HTTP 503" if failed else ""}
        for end, latency, failed in ((20, 1000, 0), (40, 1000, 0),
                                      (90, 500, 1), (100, 2000, 0), (116, 1000, 0))
    ]).to_csv(run / "requests.csv", index=False)
    (run / "run-status.json").write_text(json.dumps({"locust_exit_code": 0, "error": ""}))
    (run / "config.txt").write_text("users=1\nspawn_rate=32\nduration=120s\ndata_size_mb=10\niterations=100\nwait_seconds=0\n")
    (run / "vmstat.txt").write_text(
        "procs memory swap io system cpu\n"
        "r b swpd free buff cache si so bi bo in cs us sy id wa st\n"
        "0 0 0 1 1 1 99 99 0 0 0 0 0 0 100 0 0\n"
        "0 0 0 1 1 1 0 0 0 0 0 0 50 0 50 0 0\n"
    )
    return run


def test_uses_same_stable_window_for_cpu_and_completed_http_requests(tmp_path):
    run = _fixture_run(tmp_path)
    values = analyse_run(run, MANIFEST)
    assert values["window_seconds"] == 85
    assert values["cpu_percent"] == 50
    assert values["ram_mean_mib"] == 512
    assert values["request_count"] == 3
    assert values["failure_count"] == 1
    assert values["requests_per_second"] == pytest.approx(2 / 85)
    assert values["average_latency_ms"] == 1500
    assert values["p95_latency_ms"] == 1950
    assert values["monitor_samples"] == 86


def test_rejects_short_monitor_coverage_in_stable_window(tmp_path):
    run = _fixture_run(tmp_path, monitor_rows=40)
    with pytest.raises(ValueError, match="Cobertura insuficiente"):
        analyse_run(run, MANIFEST)


def test_summary_uses_median_and_reports_repeat_dispersion():
    runs = pd.DataFrame([
        {"vcpus": 1, "users": 2, "rep": rep, "cpu_percent": cpu,
         "app_cpu_percent": cpu - 5,
         "requests_per_second": rate, "p95_latency_ms": 1000,
         "average_latency_ms": 800, "ram_mean_mib": 500,
         "ram_available_mean_mib": 524, "ram_max_mib": 510,
         "failure_count": 0, "request_count": 20, "window_seconds": 85}
        for rep, cpu, rate in ((1, 40, 1.0), (2, 50, 2.0), (3, 60, 3.0))
    ])
    summary = summarize_runs(runs)
    assert summary.loc[0, "cpu_percent"] == 50
    assert summary.loc[0, "requests_per_second"] == 2
    assert summary.loc[0, "requests_per_second_q25"] == 1.5
    assert summary.loc[0, "requests_per_second_q75"] == 2.5


def test_collect_runs_refuses_incomplete_matrix(tmp_path):
    case = tmp_path / "demand-vbox-1cpu-20261014T120000Z"
    case.mkdir()
    (case / "manifest.json").write_text(json.dumps(MANIFEST))
    with pytest.raises(ValueError, match="Execução ausente"):
        collect_runs([case], require_complete=False)


def test_collect_runs_refuses_smoke_as_definitive_result(tmp_path):
    case = tmp_path / "demand-vbox-1cpu-20261014T120000Z"
    case.mkdir()
    (case / "manifest.json").write_text(json.dumps({**MANIFEST, "smoke": True}))
    with pytest.raises(ValueError, match="smoke"):
        collect_runs([case])

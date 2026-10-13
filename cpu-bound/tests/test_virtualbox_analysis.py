from pathlib import Path
import shutil

import pandas as pd
import pytest

from scripts.virtualbox_analysis import _vmstat_metrics, load_experiments, parse_locust_log, summarize_selected


RESULTS = Path(__file__).resolve().parents[1] / "results"


def test_final_locust_log_wins_over_periodic_csv():
    case = RESULTS / "vbox-1cpu-20261013T2036Z" / "rep1"
    periodic = pd.read_csv(case / "locust_stats.csv")
    assert int(periodic.loc[periodic["Name"] == "Aggregated", "Request Count"].iloc[0]) == 105

    final = parse_locust_log(case / "locust.log")
    assert final["request_count"] == 108
    assert final["failure_count"] == 0
    assert final["requests_per_second"] == pytest.approx(1.82)
    assert final["average_latency_ms"] == 13869
    assert final["p95_latency_ms"] == 33000


def test_loads_all_runs_but_selects_only_valid_repetitions():
    data = load_experiments(RESULTS)
    assert len(data.runs) == 19
    assert data.runs.selected.sum() == 15
    assert data.runs.groupby("cpu").selected.sum().to_dict() == {1: 3, 2: 3, 4: 3, 6: 3, 8: 3}
    assert data.audit.loc[~data.audit.selected, "reason"].notna().all()
    assert len(data.audit.loc[~data.audit.selected]) == 4
    assert not data.monitor.empty
    assert (data.monitor.timestamp_utc >= data.monitor.window_start_utc).all()
    assert (data.monitor.timestamp_utc <= data.monitor.window_end_utc).all()
    assert not data.history.empty


def test_summary_uses_median_of_selected_runs():
    runs = pd.DataFrame([
        {"cpu": 1, "rep": 1, "selected": True, "requests_per_second": 1.0, "average_latency_ms": 1000, "p95_latency_ms": 2000, "cpu_percent": 90.0, "ram_max_mib": 400.0, "request_count": 60, "failure_count": 0},
        {"cpu": 1, "rep": 2, "selected": True, "requests_per_second": 3.0, "average_latency_ms": 3000, "p95_latency_ms": 4000, "cpu_percent": 100.0, "ram_max_mib": 500.0, "request_count": 180, "failure_count": 0},
        {"cpu": 1, "rep": 3, "selected": True, "requests_per_second": 2.0, "average_latency_ms": 2000, "p95_latency_ms": 3000, "cpu_percent": 95.0, "ram_max_mib": 450.0, "request_count": 120, "failure_count": 0},
        {"cpu": 1, "rep": 4, "selected": False, "requests_per_second": 99.0, "average_latency_ms": 99999, "p95_latency_ms": 99999, "cpu_percent": 1.0, "ram_max_mib": 9999.0, "request_count": 999, "failure_count": 1},
    ])
    summary = summarize_selected(runs)
    assert summary.cpu.tolist() == [1]
    assert summary.requests_per_second.tolist() == [2.0]
    assert summary.average_latency_ms.tolist() == [2000]
    assert summary.p95_latency_ms.tolist() == [3000]
    assert summary.cpu_percent.tolist() == [95.0]
    assert summary.failure_count.tolist() == [0]


def test_missing_log_is_reported_with_path(tmp_path):
    missing = tmp_path / "rep1" / "locust.log"
    with pytest.raises(FileNotFoundError, match="locust.log"):
        parse_locust_log(missing)


def test_truncated_log_is_not_accepted(tmp_path):
    log = tmp_path / "locust.log"
    log.write_text(
        "[2026-10-13 17:00:00,000] host/INFO/locust.main: Starting Locust\n"
        "[2026-10-13 17:01:00,000] host/INFO/locust.main: Shutting down (exit code 0)\n"
        "POST /benchmark 105 0(0.00%) | 1000 1 2 3 | 1.0 0.0\n"
    )
    with pytest.raises(ValueError, match="percentis|p95"):
        parse_locust_log(log)


def test_vmstat_boot_average_is_not_counted_as_test_swap_io(tmp_path):
    vmstat = tmp_path / "rep1-vmstat.txt"
    vmstat.write_text(
        "procs memory swap io system cpu\n"
        "r b swpd free buff cache si so bi bo in cs us sy id wa st\n"
        "1 0 524 1 1 1 99 88 0 0 0 0 1 1 98 0 0\n"
        "1 0 524 1 1 1 0 0 0 0 0 0 90 8 2 0 0\n"
    )
    assert _vmstat_metrics(vmstat) == {"swap_max_kib": 524, "swap_in_kib": 0, "swap_out_kib": 0}


def test_missing_selected_monitor_fails_with_its_path(tmp_path):
    for case in RESULTS.glob("vbox-*cpu-*"):
        if case.is_dir():
            shutil.copytree(case, tmp_path / case.name)
    missing = next(tmp_path.glob("vbox-1cpu-*/rep1-monitor.csv"))
    missing.unlink()
    with pytest.raises(FileNotFoundError, match="rep1-monitor.csv"):
        load_experiments(tmp_path)


def test_selected_run_without_overlap_fails_instead_of_plotting_idle_cpu(tmp_path):
    for case in RESULTS.glob("vbox-*cpu-*"):
        if case.is_dir():
            shutil.copytree(case, tmp_path / case.name)
    monitor = next(tmp_path.glob("vbox-1cpu-*/rep1-monitor.csv"))
    frame = pd.read_csv(monitor)
    frame["timestamp_utc"] = "2026-10-14T00:00:00Z"
    frame.to_csv(monitor, index=False)
    with pytest.raises(ValueError, match="Sem sobreposição"):
        load_experiments(tmp_path)


def test_selected_run_with_only_one_monitor_sample_is_rejected(tmp_path):
    for case in RESULTS.glob("vbox-*cpu-*"):
        if case.is_dir():
            shutil.copytree(case, tmp_path / case.name)
    monitor = next(tmp_path.glob("vbox-1cpu-*/rep1-monitor.csv"))
    frame = pd.read_csv(monitor)
    frame.iloc[10:11].to_csv(monitor, index=False)
    with pytest.raises(ValueError, match="Cobertura insuficiente"):
        load_experiments(tmp_path)


def test_selected_run_with_different_workload_is_rejected(tmp_path):
    for case in RESULTS.glob("vbox-*cpu-*"):
        if case.is_dir():
            shutil.copytree(case, tmp_path / case.name)
    config = next(tmp_path.glob("vbox-1cpu-*/rep1/config.txt"))
    config.write_text(config.read_text().replace("users=32", "users=31"))
    with pytest.raises(ValueError, match="config.txt.*users"):
        load_experiments(tmp_path)


def test_malformed_monitor_of_excluded_run_stays_in_audit(tmp_path):
    for case in RESULTS.glob("vbox-*cpu-*"):
        if case.is_dir():
            shutil.copytree(case, tmp_path / case.name)
    excluded = next(tmp_path.glob("vbox-2cpu-*/rep3-monitor.csv"))
    excluded.write_text("invalid_column\n1\n")
    data = load_experiments(tmp_path)
    audit = data.audit.loc[data.audit.cpu.eq(2) & data.audit.rep.eq(3)].iloc[0]
    assert not audit.selected
    assert "Colunas ausentes" in audit.monitor_error
    assert data.runs.selected.sum() == 15


def test_selected_run_without_valid_locust_history_is_rejected(tmp_path):
    for case in RESULTS.glob("vbox-*cpu-*"):
        if case.is_dir():
            shutil.copytree(case, tmp_path / case.name)
    history = next(tmp_path.glob("vbox-1cpu-*/rep1/locust_stats_history.csv"))
    frame = pd.read_csv(history)
    frame["Requests/s"] = "N/A"
    frame.to_csv(history, index=False)
    with pytest.raises(ValueError, match="Histórico válido ausente"):
        load_experiments(tmp_path)

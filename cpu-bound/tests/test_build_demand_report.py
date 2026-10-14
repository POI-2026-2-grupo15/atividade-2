from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from scripts import build_demand_report
from scripts.build_demand_report import temporal_from_history, summarize_temporal


def test_explicit_cases_select_definitive_sources_when_another_run_exists(tmp_path: Path):
    originals = [tmp_path / f"demand-vbox-{cpu}cpu-original" for cpu in (1, 2, 4, 6, 8)]
    for path in originals:
        path.mkdir()
    (tmp_path / "demand-vbox-1cpu-new-validation").mkdir()
    selected = build_demand_report.select_cases(tmp_path, list(reversed(originals)))
    assert selected == originals


def test_script_can_run_directly_from_repository():
    root = Path(__file__).resolve().parents[1]
    process = subprocess.run([sys.executable, str(root / "scripts/build_demand_report.py"), "--help"],
                             cwd=root, capture_output=True, text=True)
    assert process.returncode == 0, process.stderr


def test_temporal_uses_cumulative_counter_differences_at_real_boundaries(tmp_path: Path):
    path = tmp_path / "locust_stats_history.csv"
    pd.DataFrame({
        "Timestamp": [100, 105, 110, 115, 100, 105, 110, 115],
        "Name": ["Aggregated"] * 4 + ["/benchmark"] * 4,
        "Total Request Count": [0, 4, 10, 16, 0, 4, 10, 16],
        "Total Failure Count": [0] * 8,
    }).to_csv(path, index=False)
    result = temporal_from_history(path, 2, 4, 1, interval_seconds=5)
    assert result.elapsed_end_seconds.tolist() == [5, 10, 15]
    assert result.requests_per_second.tolist() == pytest.approx([0.8, 1.2, 1.2])
    assert result.completed_requests.tolist() == [4, 6, 6]


def test_temporal_skips_missing_boundaries_instead_of_interpolating(tmp_path: Path):
    path = tmp_path / "locust_stats_history.csv"
    pd.DataFrame({
        "Timestamp": [100, 105, 115], "Name": ["Aggregated"] * 3,
        "Total Request Count": [0, 4, 16], "Total Failure Count": [0] * 3,
    }).to_csv(path, index=False)
    result = temporal_from_history(path, 2, 4, 1, interval_seconds=5)
    assert result.elapsed_end_seconds.tolist() == [5]


def test_temporal_summary_uses_median_and_min_max_across_repetitions():
    rows = pd.DataFrame({
        "vcpus": [2, 2, 2], "users": [4, 4, 4], "rep": [1, 2, 3],
        "elapsed_end_seconds": [5, 5, 5],
        "requests_per_second": [1.0, 2.0, 4.0],
    })
    summary = summarize_temporal(rows)
    assert summary.loc[0, "rps_median"] == 2.0
    assert summary.loc[0, "rps_min"] == 1.0
    assert summary.loc[0, "rps_max"] == 4.0

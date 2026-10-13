from pathlib import Path

import pandas as pd
import pytest

from scripts.plot_virtualbox_results import FIGURE_NAMES, generate_figures
from scripts.virtualbox_analysis import load_experiments, summarize_selected


RESULTS = Path(__file__).resolve().parents[1] / "results"


def test_generates_six_figures_in_three_formats_and_auditable_csvs(tmp_path):
    data = load_experiments(RESULTS)
    summary = summarize_selected(data.runs)
    created = generate_figures(data, summary, tmp_path)

    assert len(FIGURE_NAMES) == 6
    assert len(created) == 18
    assert {path.name for path in created} == {
        f"{name}.{extension}" for name in FIGURE_NAMES for extension in ("png", "svg", "pdf")
    }
    assert all(path.is_file() and path.stat().st_size > 1000 for path in created)
    repetitions = pd.read_csv(tmp_path / "repeticoes.csv")
    audit = pd.read_csv(tmp_path / "auditoria.csv")
    exported = pd.read_csv(tmp_path / "resumo_por_cpu.csv")
    assert len(repetitions) == 19
    assert repetitions.selected.sum() == 15
    assert len(audit.loc[~audit.selected]) == 4
    assert exported.cpu.tolist() == [1, 2, 4, 6, 8]
    assert exported.requests_per_second.tolist() == [1.81, 3.59, 7.16, 10.13, 12.72]


def test_history_for_plots_has_one_aggregated_snapshot_per_second():
    history = load_experiments(RESULTS).history
    assert not history.empty
    assert history.Name.eq("Aggregated").all()
    assert history.groupby(["cpu", "rep", "Timestamp"]).size().max() == 1
    assert history.requests_per_second.notna().all()
    assert history.seconds_from_start.between(0, 60).all()


def test_non_virtualbox_directories_do_not_enter_the_analysis(tmp_path):
    (tmp_path / "virtualbox-graficos").mkdir()
    (tmp_path / "print-live-1cpu").mkdir()
    with pytest.raises(ValueError, match="casos"):
        load_experiments(tmp_path)

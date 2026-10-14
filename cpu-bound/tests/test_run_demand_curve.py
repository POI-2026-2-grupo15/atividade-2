import pytest

from scripts.run_demand_curve import check_vm_info, parse_args, planned_runs


def test_default_matrix_includes_one_cpu_and_five_demand_levels():
    args = parse_args(["--vcpus", "1"])
    assert args.vm_name == "cpu_Bound"
    assert args.remote_project == "/home/osboxes/atividade-2-git/cpu-bound"
    assert planned_runs(args) == [(users, rep) for users in (1, 2, 4, 8, 16) for rep in (1, 2, 3)]


def test_smoke_is_one_short_run_and_cannot_join_definitive_matrix():
    args = parse_args(["--vcpus", "4", "--smoke"])
    assert args.vm_name == "cpu__bound_2cpu"
    assert args.duration_seconds == 8
    assert (args.data_size_mb, args.iterations) == (1, 1)
    assert planned_runs(args) == [(1, 1)]


def test_environment_selects_validation_vm_and_remote_project(monkeypatch):
    monkeypatch.setenv("CPU_BOUND_VM_NAME", "cpu_bound_validacao_apendice")
    monkeypatch.setenv("CPU_BOUND_REMOTE_PROJECT", "/home/osboxes/atividade-2-git/cpu-bound")
    args = parse_args(["--vcpus", "1", "--smoke"])
    assert args.vm_name == "cpu_bound_validacao_apendice"
    assert args.remote_project == "/home/osboxes/atividade-2-git/cpu-bound"


def test_command_line_options_override_environment(monkeypatch):
    monkeypatch.setenv("CPU_BOUND_VM_NAME", "cpu_bound_validacao_apendice")
    monkeypatch.setenv("CPU_BOUND_REMOTE_PROJECT", "/home/osboxes/atividade-2-git/cpu-bound")
    args = parse_args(["--vcpus", "1", "--vm-name", "chosen-vm", "--remote-project", "/srv/cpu-bound"])
    assert args.vm_name == "chosen-vm"
    assert args.remote_project == "/srv/cpu-bound"


def test_vm_preflight_rejects_wrong_cpu_before_generating_results():
    info = 'VMState="running"\ncpus=8\nmemory=1024\nnic1="nat"\n'
    with pytest.raises(ValueError, match="8 vCPUs.*2 esperadas"):
        check_vm_info(info, expected_vcpus=2)


def test_vm_preflight_accepts_matching_running_nat_vm():
    info = 'VMState="running"\ncpus=2\nmemory=1024\nnic1="nat"\n'
    check_vm_info(info, expected_vcpus=2)

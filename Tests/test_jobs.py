"""SLURM mechanics: templating, submission, status -- all through an injectable
`run` so no test needs a real cluster."""
import subprocess

import pytest

from askslm.cli import jobs


def test_cpu_template_names_the_partition_and_the_worker_command(tmp_path):
    script = jobs.render_sbatch(tmp_path, worker_cmd="python -m askslm.cli.worker",
                                gpu=False)

    assert "#SBATCH --partition=cpu192G-48h" in script
    assert "#SBATCH --cpus-per-task=8" in script
    assert "#SBATCH --mem=48G" in script
    assert "python -m askslm.cli.worker" in script
    assert "--gres=gpu" not in script


def test_gpu_template_requests_the_h200_partition_and_a_gpu(tmp_path):
    script = jobs.render_sbatch(tmp_path, worker_cmd="python -m askslm.cli.worker --gpu",
                                gpu=True)

    assert "#SBATCH --partition=H200-12h" in script
    assert "#SBATCH --cpus-per-task=16" in script
    assert "#SBATCH --mem=128G" in script
    assert "#SBATCH --gres=gpu:1" in script


def test_write_sbatch_writes_the_script_into_the_plan_folder(tmp_path):
    path = jobs.write_sbatch(tmp_path, worker_cmd="echo hi", gpu=False)

    assert path == tmp_path / "job.sbatch"
    assert "echo hi" in path.read_text()


def test_submit_parses_the_job_id_from_sbatch_stdout(tmp_path):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0,
                                           stdout="Submitted batch job 4213765\n", stderr="")

    job_id = jobs.submit(tmp_path / "job.sbatch", run=fake_run)

    assert job_id == "4213765"


def test_submit_raises_if_sbatch_output_is_unparseable(tmp_path):
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0,
                                           stdout="sbatch: error: something broke\n", stderr="")

    with pytest.raises(RuntimeError, match="something broke"):
        jobs.submit(tmp_path / "job.sbatch", run=fake_run)


def test_squeue_state_reports_none_once_the_job_has_left_the_queue():
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    assert jobs.squeue_state("4213765", run=fake_run) is None


def test_squeue_state_reports_the_job_state_while_queued():
    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, stdout="RUNNING\n", stderr="")

    assert jobs.squeue_state("4213765", run=fake_run) == "RUNNING"


def test_job_id_and_status_round_trip_through_the_plan_folder(tmp_path):
    jobs.write_job_id(tmp_path, "4213765")
    jobs.write_status(tmp_path, "RUNNING")

    assert jobs.read_job_id(tmp_path) == "4213765"
    assert jobs.read_status(tmp_path) == "RUNNING"


def test_missing_job_id_and_status_read_as_none(tmp_path):
    assert jobs.read_job_id(tmp_path) is None
    assert jobs.read_status(tmp_path) is None

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RunnerContext:
    view_name: str
    workspace_dir: Path
    workspace_input_dir: Path
    config_dir: Path
    results_dir: Path
    logs_dir: Path
    cache_dir: Path
    run_log_path: Path
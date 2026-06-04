from pathlib import Path

import pytest

from pybash.shell import PyBashShell


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


def _script_files() -> list[Path]:
    return sorted(SCRIPTS_DIR.glob("*.pybash"))


def _script_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip() and not line.strip().startswith("#")]


SCRIPT_MARKERS = {
    "01_env_and_status.pybash": "PROJECT_NON_EMPTY",
    "02_filesystem_flow.pybash": "DATA_DIR_EXISTS",
    "03_conditionals_and_tests.pybash": "done",
    "04_end_to_end_hearty.pybash": "COMPLETE",
    "05_pipes_tee_dup.pybash": "PIPE_DEMO_DONE",
    "06_pipeline_regression.pybash": "REG_DONE",
    "07_system_utilities.pybash": "COMPLETE_UTILS",
    "08_dynamic_uptime_load.pybash": "COMPLETE_DYNAMIC",
}


@pytest.mark.parametrize("script_path", _script_files(), ids=lambda p: p.name)
def test_scripts_execute_successfully(script_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shell = PyBashShell()

    status = 0
    for line in _script_lines(script_path):
        status = shell.execute_line(line)

    captured = capsys.readouterr()
    out = captured.out

    assert status == 0, f"final status for {script_path.name} was {status}"

    marker = SCRIPT_MARKERS.get(script_path.name)
    assert marker is not None, f"missing marker mapping for {script_path.name}"
    assert marker in out, f"expected marker '{marker}' not found in output for {script_path.name}"

import runpy
from types import SimpleNamespace

import pytest


def test_cli_main_invokes_shell(monkeypatch):
    from pybash import cli

    state = SimpleNamespace(ran=False)

    class DummyShell:
        def __init__(self) -> None:
            self.exit_code = 3

        def run(self) -> None:
            state.ran = True

    monkeypatch.setattr(cli, "PyBashShell", DummyShell)
    assert cli.main() == 3
    assert state.ran is True


def test_module_main_exits_with_cli_status(monkeypatch):
    import pybash.cli as cli

    monkeypatch.setattr(cli, "main", lambda: 9)

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("pybash.__main__", run_name="__main__")

    assert exc.value.code == 9


def test_alias_package_imports_shell_class():
    from pybash_native import PyBashShell

    shell = PyBashShell()
    assert shell.cwd == "/home/user"


def test_alias_module_main_exits_with_cli_status(monkeypatch):
    import pybash.cli as cli

    monkeypatch.setattr(cli, "main", lambda: 11)

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("pybash_native.__main__", run_name="__main__")

    assert exc.value.code == 11

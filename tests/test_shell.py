import pytest

from pybash.shell import PyBashShell, ShellRuntimeError, VirtualFileSystem


@pytest.fixture
def shell() -> PyBashShell:
    return PyBashShell()


def run_and_capture(shell: PyBashShell, capsys: pytest.CaptureFixture[str], command: str) -> tuple[int, str, str]:
    status = shell.execute_line(command)
    captured = capsys.readouterr()
    return status, captured.out, captured.err


def test_bootstrap_directories_exist(shell: PyBashShell) -> None:
    assert shell.cwd == "/home/user"
    assert shell.vfs.is_dir("/home")
    assert shell.vfs.is_dir("/home/user")
    assert shell.vfs.is_dir("/tmp")


def test_pwd_and_cd(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "pwd")
    assert status == 0
    assert out == "/home/user\n"

    status, out, _ = run_and_capture(shell, capsys, "mkdir workspace; cd workspace; pwd")
    assert status == 0
    assert out.endswith("/home/user/workspace\n")


def test_pipeline_echo_to_cat(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "echo hello | cat")
    assert status == 0
    assert out == "hello\n"


def test_redirection_write_and_read(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "echo alpha > note")
    assert status == 0
    assert out == ""

    status, out, _ = run_and_capture(shell, capsys, "cat note")
    assert status == 0
    assert out == "alpha\n"


def test_append_redirection(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, _, _ = run_and_capture(shell, capsys, "echo first > stream")
    assert status == 0

    status, _, _ = run_and_capture(shell, capsys, "echo second >> stream")
    assert status == 0

    status, out, _ = run_and_capture(shell, capsys, "cat stream")
    assert status == 0
    assert out == "first\nsecond\n"


def test_input_redirection(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, _, _ = run_and_capture(shell, capsys, "echo payload > data")
    assert status == 0

    status, out, _ = run_and_capture(shell, capsys, "cat < data")
    assert status == 0
    assert out == "payload\n"


def test_export_and_expansion_temporal(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, _, _ = run_and_capture(shell, capsys, "export NAME=pybash")
    assert status == 0

    status, out, _ = run_and_capture(shell, capsys, "echo $NAME")
    assert status == 0
    assert out == "pybash\n"


def test_unset_temporal(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, _, _ = run_and_capture(shell, capsys, "export TOKEN=abc")
    assert status == 0

    status, _, _ = run_and_capture(shell, capsys, "unset TOKEN")
    assert status == 0

    status, out, _ = run_and_capture(shell, capsys, "echo ${TOKEN}")
    assert status == 0
    assert out == "\n"


def test_status_variable_temporal(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, _, _ = run_and_capture(shell, capsys, "false")
    assert status == 1

    status, out, _ = run_and_capture(shell, capsys, "echo $?")
    assert status == 0
    assert out == "1\n"


def test_pid_variable_expands(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "echo $$")
    assert status == 0
    assert out == "1\n"


def test_unknown_command(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "nope")
    assert status == 127
    assert "command not found: nope" in out


def test_history_tracks_sequence(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, _, _ = run_and_capture(shell, capsys, "echo one")
    assert status == 0

    status, _, _ = run_and_capture(shell, capsys, "echo two")
    assert status == 0

    status, out, _ = run_and_capture(shell, capsys, "history")
    assert status == 0
    assert "1  echo one" in out
    assert "2  echo two" in out
    assert "3  history" in out


def test_exit_sets_running_state(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "exit 7")
    assert status == 7
    assert out == ""
    assert shell.running is False


def test_vfs_normalize_paths() -> None:
    vfs = VirtualFileSystem()
    assert vfs.normalize("/home/user", "docs") == "/home/user/docs"
    assert vfs.normalize("/home/user", "../tmp") == "/home/tmp"
    assert vfs.normalize("/home/user", "/var/log") == "/var/log"
    assert vfs.normalize("/", "../x") == "/x"


def test_vfs_core_file_operations() -> None:
    vfs = VirtualFileSystem()
    vfs.mkdir("/home")
    vfs.mkdir("/home/user")
    vfs.write_file("/home/user/note", "a")
    assert vfs.read_file("/home/user/note") == "a"
    vfs.append_file("/home/user/note", "b")
    assert vfs.read_file("/home/user/note") == "ab"
    vfs.touch("/home/user/empty")
    assert vfs.read_file("/home/user/empty") == ""
    assert vfs.exists("/home/user/note") is True
    assert vfs.is_dir("/home/user") is True


def test_vfs_error_paths() -> None:
    vfs = VirtualFileSystem()
    vfs.mkdir("/home")
    vfs.mkdir("/home/user")
    vfs.mkdir("/home/user/dir")

    with pytest.raises(ShellRuntimeError):
        vfs.mkdir("/home/user/dir")
    with pytest.raises(ShellRuntimeError):
        vfs.listdir("/home/user/missing")
    with pytest.raises(ShellRuntimeError):
        vfs.read_file("/home/user/missing")
    with pytest.raises(ShellRuntimeError):
        vfs.write_file("/home/user/dir", "x")
    with pytest.raises(ShellRuntimeError):
        vfs.append_file("/home/user/dir", "x")
    with pytest.raises(ShellRuntimeError):
        vfs.touch("/home/user/dir")
    with pytest.raises(ShellRuntimeError):
        vfs.rm_file("/home/user/dir")
    with pytest.raises(ShellRuntimeError):
        vfs.rmdir("/")
    with pytest.raises(ShellRuntimeError):
        vfs.rmdir("/home/user")


def test_vfs_parent_and_node_additional_errors() -> None:
    vfs = VirtualFileSystem()
    vfs.mkdir("/home")
    vfs.write_file("/home/file", "x")

    with pytest.raises(ShellRuntimeError):
        vfs._get_parent_dir("/")
    with pytest.raises(ShellRuntimeError):
        vfs._get_node("/home/file/child")


def test_parser_errors_map_to_status_2(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "|")
    assert status == 2
    assert "invalid null command" in out

    status, out, _ = run_and_capture(shell, capsys, "echo hi >")
    assert status == 2
    assert "redirection missing path" in out


def test_input_redirection_missing_file(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "cat < missing")
    assert status == 1
    assert "no such file or directory" in out


def test_split_statements_respects_quotes(shell: PyBashShell) -> None:
    chunks = shell._split_statements("echo 'a;b'; echo c")
    assert chunks == ["echo 'a;b'", "echo c"]


def test_split_statements_respects_escaped_separator(shell: PyBashShell) -> None:
    chunks = shell._split_statements(r"echo a\;b; echo c")
    assert chunks == [r"echo a\;b", "echo c"]


def test_export_invalid_identifier(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "export 9BAD=x")
    assert status == 1
    assert "not a valid identifier" in out


def test_set_lists_variables(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "set")
    assert status == 0
    assert "HOME=/home/user" in out
    assert "USER=user" in out


def test_cd_error_paths(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "cd /does/not/exist")
    assert status == 1
    assert "no such directory" in out


def test_ls_on_file_reports_error(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, _, _ = run_and_capture(shell, capsys, "touch item")
    assert status == 0

    status, out, _ = run_and_capture(shell, capsys, "ls item")
    assert status == 1
    assert "not a directory" in out


def test_missing_operands_report_errors(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "mkdir")
    assert status == 1
    assert "missing operand" in out

    status, out, _ = run_and_capture(shell, capsys, "touch")
    assert status == 1
    assert "missing file operand" in out

    status, out, _ = run_and_capture(shell, capsys, "rm")
    assert status == 1
    assert "missing operand" in out

    status, out, _ = run_and_capture(shell, capsys, "rmdir")
    assert status == 1
    assert "missing operand" in out


def test_write_and_append_usage_errors(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "write")
    assert status == 1
    assert "usage: write FILE" in out

    status, out, _ = run_and_capture(shell, capsys, "append")
    assert status == 1
    assert "usage: append FILE" in out


def test_rm_dir_and_rmdir_non_empty_errors(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, _, _ = run_and_capture(shell, capsys, "mkdir box")
    assert status == 0
    status, _, _ = run_and_capture(shell, capsys, "touch box/file")
    assert status == 0

    status, out, _ = run_and_capture(shell, capsys, "rm box")
    assert status == 1
    assert "is a directory" in out

    status, out, _ = run_and_capture(shell, capsys, "rmdir box")
    assert status == 1
    assert "directory not empty" in out


def test_misc_builtins(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "whoami")
    assert status == 0
    assert out == "user\n"

    status, out, _ = run_and_capture(shell, capsys, "help")
    assert status == 0
    assert "builtins:" in out

    status, out, _ = run_and_capture(shell, capsys, "true")
    assert status == 0
    assert out == ""

    status, out, _ = run_and_capture(shell, capsys, "false")
    assert status == 1
    assert out == ""


def test_exit_invalid_numeric_arg(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "exit no")
    assert status == 2
    assert "numeric argument required" in out


def test_logical_and_short_circuit(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "false && echo should_not_print")
    assert status == 1
    assert out == ""


def test_logical_or_short_circuit(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "true || echo should_not_print")
    assert status == 0
    assert out == ""


def test_logical_chain_executes_expected_branches(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "false || echo yes && echo ok")
    assert status == 0
    assert out == "yes\nok\n"


def test_conditionals_with_quotes(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "echo 'a && b' && echo done")
    assert status == 0
    assert out == "a && b\ndone\n"


def test_unmatched_quote_is_parse_error(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "echo 'x")
    assert status == 2
    assert "No closing quotation" in out


def test_test_builtin_string_ops(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "test a = a")
    assert status == 0
    assert out == ""

    status, out, _ = run_and_capture(shell, capsys, "test a != a")
    assert status == 1
    assert out == ""


def test_test_builtin_unary_and_file_ops(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, _, _ = run_and_capture(shell, capsys, "mkdir dir1; touch file1")
    assert status == 0

    status, _, _ = run_and_capture(shell, capsys, "test -d dir1")
    assert status == 0
    status, _, _ = run_and_capture(shell, capsys, "test -f file1")
    assert status == 0
    status, _, _ = run_and_capture(shell, capsys, "test -e file1")
    assert status == 0
    status, _, _ = run_and_capture(shell, capsys, "test -z ''")
    assert status == 0
    status, _, _ = run_and_capture(shell, capsys, "test -n text")
    assert status == 0


def test_bracket_builtin(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "[ a = a ]")
    assert status == 0
    assert out == ""


def test_bracket_missing_closer(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "[ a = a")
    assert status == 2
    assert "missing ']'" in out


def test_test_reports_unsupported_ops(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "test -x file1")
    assert status == 2
    assert "unsupported unary operator" in out

    status, out, _ = run_and_capture(shell, capsys, "test a -eq b")
    assert status == 2
    assert "unsupported binary operator" in out


def test_test_complex_expression_not_supported(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "test a = b c")
    assert status == 2
    assert "complex test expressions" in out


def test_tee_pipes_and_writes_file(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "echo hello | tee out | cat")
    assert status == 0
    assert out == "hello\n"

    status, out, _ = run_and_capture(shell, capsys, "cat out")
    assert status == 0
    assert out == "hello\n"


def test_tee_append_mode(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, _, _ = run_and_capture(shell, capsys, "echo one | tee lines")
    assert status == 0

    status, _, _ = run_and_capture(shell, capsys, "echo two | tee -a lines")
    assert status == 0

    status, out, _ = run_and_capture(shell, capsys, "cat lines")
    assert status == 0
    assert out == "one\ntwo\n"


def test_dup_duplicates_stream(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "echo x | dup 3 | cat")
    assert status == 0
    assert out == "x\nx\nx\n"


def test_dup_errors(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "echo x | dup nope")
    assert status == 1
    assert "COUNT must be an integer" in out

    status, out, _ = run_and_capture(shell, capsys, "echo x | dup -1")
    assert status == 1
    assert "COUNT must be >= 0" in out


def test_export_name_without_value(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, _, _ = run_and_capture(shell, capsys, "export FLAG")
    assert status == 0
    status, out, _ = run_and_capture(shell, capsys, "echo ${FLAG}")
    assert status == 0
    assert out == "\n"


def test_parse_pipeline_empty(shell: PyBashShell) -> None:
    assert shell._parse_pipeline("") == []


def test_run_loop_eof(monkeypatch: pytest.MonkeyPatch, shell: PyBashShell) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(EOFError()))
    shell.run()
    assert shell.running is True


def test_run_loop_keyboard_interrupt_then_eof(monkeypatch: pytest.MonkeyPatch, shell: PyBashShell) -> None:
    state = {"calls": 0}

    def fake_input(_prompt: str) -> str:
        state["calls"] += 1
        if state["calls"] == 1:
            raise KeyboardInterrupt()
        raise EOFError()

    monkeypatch.setattr("builtins.input", fake_input)
    shell.run()
    assert shell.last_status == 130


def test_execute_line_empty_returns_existing_status(shell: PyBashShell) -> None:
    shell.last_status = 7
    assert shell.execute_line("   ") == 7

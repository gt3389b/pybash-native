from pathlib import Path

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
    assert "hostname" in out
    assert "os-release" in out
    assert "id" in out
    assert "uptime" in out
    assert "load" in out

    status, out, _ = run_and_capture(shell, capsys, "true")
    assert status == 0
    assert out == ""

    status, out, _ = run_and_capture(shell, capsys, "false")
    assert status == 1
    assert out == ""


def test_uname_defaults(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "uname")
    assert status == 0
    assert out == "PyBash\n"

    status, out, _ = run_and_capture(shell, capsys, "uname -a")
    assert status == 0
    assert out == "PyBash pybash 0.1 pybash-native pyvm\n"


def test_ifconfig_defaults(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "ifconfig")
    assert status == 0
    assert "lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384" in out
    assert "\tinet 127.0.0.1 netmask 0xff000000" in out
    assert "\tether 00:00:00:00:00:00" in out


def test_hostname_defaults(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "hostname")
    assert status == 0
    assert out == "pybash\n"


def test_hostname_short_option(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    shell.update_system_context({"uname": {"nodename": "node.lab.local"}})
    status, out, _ = run_and_capture(shell, capsys, "hostname -s")
    assert status == 0
    assert out == "node\n"


def test_os_release_defaults(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "os-release")
    assert status == 0
    assert 'NAME="PyBash Linux"' in out
    assert 'VERSION_ID="0.1"' in out


def test_os_release_key_selection(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "os-release ID VERSION_ID")
    assert status == 0
    assert out == "pybash\n0.1\n"


def test_id_defaults(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "id")
    assert status == 0
    assert "uid=1000(user)" in out
    assert "gid=1000(user)" in out
    assert "groups=1000(user),4(adm)" in out


def test_id_option_modes(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "id -u")
    assert status == 0
    assert out == "1000\n"

    status, out, _ = run_and_capture(shell, capsys, "id -un")
    assert status == 0
    assert out == "user\n"

    status, out, _ = run_and_capture(shell, capsys, "id -Gn")
    assert status == 0
    assert out == "user adm\n"


def test_id_option_errors(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "id -n")
    assert status == 1
    assert "-n requires" in out

    status, out, _ = run_and_capture(shell, capsys, "id -z")
    assert status == 1
    assert "unsupported option" in out


def test_uptime_and_load_defaults(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "uptime")
    assert status == 0
    assert " up " in out
    assert "load average:" in out

    status, out, _ = run_and_capture(shell, capsys, "load")
    assert status == 0
    parts = out.strip().split(" ")
    assert len(parts) == 3


def test_dynamic_uptime_and_load_with_fake_clock(capsys: pytest.CaptureFixture[str]) -> None:
    state = {"now": 1_700_000_000}

    def fake_now() -> float:
        return float(state["now"])

    shell = PyBashShell(
        now_provider=fake_now,
        system_context={
            "runtime": {"boot_epoch": state["now"] - 120, "last_load_epoch": state["now"]},
            "load": {"avg_1": 0.10, "avg_5": 0.05, "avg_15": 0.02, "trend_per_min": 0.60},
            "sessions": {"active_users": 2},
        },
    )

    status, out1, _ = run_and_capture(shell, capsys, "uptime")
    assert status == 0
    assert "2 users" in out1
    assert "load average: 0.10, 0.05, 0.02" in out1

    state["now"] += 120
    status, out2, _ = run_and_capture(shell, capsys, "uptime")
    assert status == 0
    assert "0:04" in out2
    assert "load average: 1.30, 0.89, 0.50" in out2

    state["now"] += 60
    status, out3, _ = run_and_capture(shell, capsys, "load")
    assert status == 0
    assert out3 == "1.90 1.31 0.74\n"


def test_uptime_and_load_usage_errors(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "uptime -x")
    assert status == 1
    assert "usage: uptime" in out

    status, out, _ = run_and_capture(shell, capsys, "load -x")
    assert status == 1
    assert "usage: load" in out


def test_update_system_context_rejects_bad_runtime_sessions_load(shell: PyBashShell) -> None:
    with pytest.raises(ShellRuntimeError):
        shell.update_system_context({"runtime": "bad"})
    with pytest.raises(ShellRuntimeError):
        shell.update_system_context({"sessions": "bad"})
    with pytest.raises(ShellRuntimeError):
        shell.update_system_context({"load": "bad"})


def test_uptime_invalid_context(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    shell.update_system_context({"runtime": {"boot_epoch": "nope"}})
    status, out, _ = run_and_capture(shell, capsys, "uptime")
    assert status == 1
    assert "invalid system context" in out


def test_context_customization_on_instantiation(capsys: pytest.CaptureFixture[str]) -> None:
    shell = PyBashShell(
        initial_env={"USER": "custom-user"},
        system_context={
            "uname": {"sysname": "DemoOS", "nodename": "demo-host", "release": "9.9", "version": "v1", "machine": "x86-demo"},
            "interfaces": {
                "en0": {
                    "flags": "8863<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST>",
                    "mtu": 1500,
                    "inet": "10.0.0.2",
                    "netmask": "0xffffff00",
                    "ether": "de:ad:be:ef:00:01",
                }
            },
        },
    )

    status, out, _ = run_and_capture(shell, capsys, "whoami")
    assert status == 0
    assert out == "custom-user\n"

    status, out, _ = run_and_capture(shell, capsys, "uname -a")
    assert status == 0
    assert out == "DemoOS demo-host 9.9 v1 x86-demo\n"

    status, out, _ = run_and_capture(shell, capsys, "ifconfig en0")
    assert status == 0
    assert "en0: flags=8863<UP,BROADCAST,RUNNING,SIMPLEX,MULTICAST> mtu 1500" in out
    assert "\tether de:ad:be:ef:00:01" in out


def test_context_customization_post_instantiation(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    shell.set_uname(sysname="AcmeOS", machine="arm64")
    shell.set_interface(
        "en9",
        flags="8843<UP,BROADCAST,RUNNING,SIMPLEX>",
        mtu=1400,
        inet="192.168.64.2",
        netmask="0xffffff00",
        ether="aa:bb:cc:dd:ee:ff",
    )

    status, out, _ = run_and_capture(shell, capsys, "uname -sm")
    assert status == 0
    assert out == "AcmeOS arm64\n"

    status, out, _ = run_and_capture(shell, capsys, "ifconfig en9")
    assert status == 0
    assert "en9: flags=8843<UP,BROADCAST,RUNNING,SIMPLEX> mtu 1400" in out
    assert "\tinet 192.168.64.2 netmask 0xffffff00" in out
    assert "\tether aa:bb:cc:dd:ee:ff" in out


def test_register_builtin_post_instantiation(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    def _hello(args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        return 0, "hello " + " ".join(args), ""

    shell.register_builtin("hello", _hello)

    status, out, _ = run_and_capture(shell, capsys, "hello pybash")
    assert status == 0
    assert out == "hello pybash\n"


def test_register_builtin_requires_replace_for_existing(shell: PyBashShell) -> None:
    with pytest.raises(ShellRuntimeError):
        shell.register_builtin("echo", shell._cmd_echo)


def test_ifconfig_missing_interface(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "ifconfig en404")
    assert status == 1
    assert "interface not found" in out


def test_uname_unsupported_option(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "uname -z")
    assert status == 1
    assert "unsupported option" in out


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


def test_template_builtin_simple_render(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    shell.register_template_builtin("banner", "{{ env.USER }}@{{ cwd }}")
    status, out, _ = run_and_capture(shell, capsys, "banner")
    assert status == 0
    assert out == "user@/home/user\n"


def test_template_builtin_with_mapping_hook(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    def hook(context: dict[str, object]) -> dict[str, object]:
        return {"message": f"args={len(context['args'])}"}

    shell.register_template_builtin("mkmsg", "{{ message }}", hook=hook)
    status, out, _ = run_and_capture(shell, capsys, "mkmsg a b")
    assert status == 0
    assert out == "args=2\n"


def test_template_builtin_with_tuple_hook_short_circuit(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    def hook(_context: dict[str, object]) -> tuple[int, str, str]:
        return (3, "", "blocked")

    shell.register_template_builtin("guard", "{{ env.USER }}", hook=hook)
    status, out, _ = run_and_capture(shell, capsys, "guard")
    assert status == 3
    assert "blocked" in out


def test_template_builtin_with_invalid_hook_return(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    def hook(_context: dict[str, object]) -> str:
        return "bad"

    shell.register_template_builtin("badhook", "ok", hook=hook)
    status, out, _ = run_and_capture(shell, capsys, "badhook")
    assert status == 1
    assert "hook must return mapping" in out


def test_template_builtin_with_hook_errors(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    def runtime_error_hook(_context: dict[str, object]) -> None:
        raise ShellRuntimeError("boom")

    shell.register_template_builtin("err1", "ok", hook=runtime_error_hook)
    status, out, _ = run_and_capture(shell, capsys, "err1")
    assert status == 1
    assert "pybash: err1: boom" in out

    def generic_error_hook(_context: dict[str, object]) -> None:
        raise ValueError("oops")

    shell.register_template_builtin("err2", "ok", hook=generic_error_hook)
    status, out, _ = run_and_capture(shell, capsys, "err2")
    assert status == 1
    assert "hook error: oops" in out


def test_template_builtin_template_error(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    shell.register_template_builtin("oops", "{{ missing_value }}")
    status, out, _ = run_and_capture(shell, capsys, "oops")
    assert status == 1
    assert "template error" in out


def test_template_registration_error_paths(shell: PyBashShell) -> None:
    with pytest.raises(ShellRuntimeError):
        shell.register_template_builtin("", "x")

    with pytest.raises(ShellRuntimeError):
        shell.register_template_builtin("broken", "{{")

    with pytest.raises(ShellRuntimeError):
        shell.register_template_hook("missing", lambda _ctx: None)


def test_template_hook_registration_replace_rules(shell: PyBashShell) -> None:
    shell.register_template_builtin("templ", "{{ value }}")
    shell.register_template_hook("templ", lambda _ctx: {"value": "one"})
    with pytest.raises(ShellRuntimeError):
        shell.register_template_hook("templ", lambda _ctx: {"value": "two"})
    shell.register_template_hook("templ", lambda _ctx: {"value": "three"}, replace=True)


def test_template_utility_registration_and_replace(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    shell.register_template_utility("xupper", lambda value: str(value).upper())
    shell.register_template_builtin("utilcmd", "{{ xupper(env.USER) }}")
    status, out, _ = run_and_capture(shell, capsys, "utilcmd")
    assert status == 0
    assert out == "USER\n"

    with pytest.raises(ShellRuntimeError):
        shell.register_template_utility("xupper", lambda value: value)
    shell.register_template_utility("xupper", lambda value: f"<{value}>", replace=True)
    status, out, _ = run_and_capture(shell, capsys, "utilcmd")
    assert status == 0
    assert out == "<user>\n"


def test_template_initialization_overrides_and_hook_only(capsys: pytest.CaptureFixture[str]) -> None:
    shell = PyBashShell(
        builtin_templates={"uname": "{{ uname_values | join('::') }}", "hello": "{{ greeting }}"},
        builtin_template_hooks={
            "uname": lambda _ctx: {"uname_values": ["Linux", "host"]},
            "ifconfig": lambda _ctx: {
                "interfaces": [
                    {
                        "name": "en0",
                        "flags": "UP",
                        "mtu": 1500,
                        "address_lines": [{"label": "inet", "value": "10.0.0.2"}],
                    }
                ]
            },
            "hello": lambda _ctx: {"greeting": "hello-world"},
        },
    )

    status, out, _ = run_and_capture(shell, capsys, "uname")
    assert status == 0
    assert out == "Linux::host\n"

    status, out, _ = run_and_capture(shell, capsys, "ifconfig")
    assert status == 0
    assert "en0: flags=UP mtu 1500" in out
    assert "\tinet 10.0.0.2" in out

    status, out, _ = run_and_capture(shell, capsys, "hello")
    assert status == 0
    assert out == "hello-world\n"


def test_internal_template_builtin_not_found(shell: PyBashShell) -> None:
    status, stdout, stderr = shell._run_template_builtin("missing", [], "")
    assert status == 1
    assert stdout == ""
    assert "template builtin not found" in stderr


def test_ifconfig_mtu_fallback_when_invalid(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    shell.update_system_context(
        {
            "interfaces": {
                "bad0": {
                    "flags": "UP",
                    "mtu": "nope",
                    "inet": "10.2.3.4",
                }
            }
        }
    )
    status, out, _ = run_and_capture(shell, capsys, "ifconfig bad0")
    assert status == 0
    assert "bad0: flags=UP mtu 1500" in out


def test_hostname_usage_error(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "hostname -x")
    assert status == 1
    assert "usage: hostname" in out


def test_os_release_usage_error(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "os-release -x")
    assert status == 1
    assert "usage: os-release" in out


def test_update_system_context_os_release_and_identity(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    shell.update_system_context(
        {
            "os_release": {"ID": "demo", "VERSION_ID": "2.0"},
            "identity": {
                "uid": 42,
                "gid": 84,
                "user": "alice",
                "group": "staff",
                "groups": [{"gid": 84, "name": "staff"}, {"gid": 33, "name": "www"}],
            },
        }
    )

    status, out, _ = run_and_capture(shell, capsys, "os-release ID VERSION_ID")
    assert status == 0
    assert out == "demo\n2.0\n"

    status, out, _ = run_and_capture(shell, capsys, "id")
    assert status == 0
    assert "uid=42(alice)" in out
    assert "gid=84(staff)" in out
    assert "groups=84(staff),33(www)" in out


def test_update_system_context_rejects_bad_new_sections(shell: PyBashShell) -> None:
    with pytest.raises(ShellRuntimeError):
        shell.update_system_context({"os_release": "bad"})
    with pytest.raises(ShellRuntimeError):
        shell.update_system_context({"identity": "bad"})


def test_id_identity_context_validation(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    shell.update_system_context({"identity": {"uid": "oops"}})
    status, out, _ = run_and_capture(shell, capsys, "id")
    assert status == 1
    assert "invalid identity context" in out


def test_id_multiple_selector_lines(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "id -ug")
    assert status == 0
    assert out == "1000\n1000\n"


def test_load_template_builtin_from_relative_template_dir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    (template_dir / "hello.tmpl").write_text("hello {{ env.USER }}", encoding="utf-8")
    shell = PyBashShell(template_dir=template_dir)

    shell.load_template_builtin("hello", "hello.tmpl")
    status, out, _ = run_and_capture(shell, capsys, "hello")
    assert status == 0
    assert out == "hello user\n"


def test_load_template_builtin_missing_file_raises(shell: PyBashShell) -> None:
    with pytest.raises(ShellRuntimeError):
        shell.load_template_builtin("missingtpl", "does-not-exist.tmpl")


def test_register_builtin_empty_name_raises(shell: PyBashShell) -> None:
    with pytest.raises(ShellRuntimeError):
        shell.register_builtin("", shell._cmd_echo)


def test_register_template_utility_empty_name_raises(shell: PyBashShell) -> None:
    with pytest.raises(ShellRuntimeError):
        shell.register_template_utility("", lambda x: x)


def test_set_interface_empty_name_raises(shell: PyBashShell) -> None:
    with pytest.raises(ShellRuntimeError):
        shell.set_interface("")


def test_template_source_tracking_and_replace_clear(tmp_path: Path, shell: PyBashShell) -> None:
    source = tmp_path / "src.tmpl"
    source.write_text("hi", encoding="utf-8")
    shell.load_template_builtin("tracked", source)
    assert shell._template_builtin_sources["tracked"] == source.resolve()

    shell.register_template_builtin("tracked", "inline", replace=True)
    assert "tracked" not in shell._template_builtin_sources


def test_hook_uname_invalid_args_type(shell: PyBashShell) -> None:
    status, _stdout, stderr = shell._hook_uname({"args": "bad"})  # type: ignore[arg-type]
    assert status == 1
    assert "invalid arguments" in stderr


def test_hook_ifconfig_invalid_args_and_context(shell: PyBashShell) -> None:
    status, _stdout, stderr = shell._hook_ifconfig({"args": "bad"})  # type: ignore[arg-type]
    assert status == 1
    assert "invalid arguments" in stderr

    shell.system_context["interfaces"] = "bad"
    status, _stdout, stderr = shell._hook_ifconfig({"args": []})
    assert status == 1
    assert "invalid interfaces context" in stderr


def test_hook_hostname_invalid_args_type(shell: PyBashShell) -> None:
    status, _stdout, stderr = shell._hook_hostname({"args": "bad"})  # type: ignore[arg-type]
    assert status == 1
    assert "invalid arguments" in stderr


def test_hook_os_release_invalid_args_and_context(shell: PyBashShell) -> None:
    status, _stdout, stderr = shell._hook_os_release({"args": "bad"})  # type: ignore[arg-type]
    assert status == 1
    assert "invalid arguments" in stderr

    shell.system_context["os_release"] = "bad"
    status, _stdout, stderr = shell._hook_os_release({"args": []})
    assert status == 1
    assert "invalid os_release context" in stderr


def test_hook_id_invalid_args_type(shell: PyBashShell) -> None:
    status, _stdout, stderr = shell._hook_id({"args": "bad"})  # type: ignore[arg-type]
    assert status == 1
    assert "invalid arguments" in stderr


def test_id_usage_error_for_non_option_arg(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    status, out, _ = run_and_capture(shell, capsys, "id user")
    assert status == 1
    assert "usage: id" in out


def test_id_groups_scalar_entries(shell: PyBashShell, capsys: pytest.CaptureFixture[str]) -> None:
    shell.update_system_context({"identity": {"groups": [1000, 1001]}})
    status, out, _ = run_and_capture(shell, capsys, "id")
    assert status == 0
    assert "groups=1000(1000),1001(1001)" in out


def test_runtime_and_sessions_context_invalid_mappings(shell: PyBashShell) -> None:
    shell.system_context["runtime"] = "bad"
    with pytest.raises(ShellRuntimeError):
        shell._runtime_context()

    shell.system_context["runtime"] = {"boot_epoch": 1, "last_load_epoch": 1}
    shell.system_context["sessions"] = "bad"
    with pytest.raises(ShellRuntimeError):
        shell._sessions_context()


def test_update_load_snapshot_invalid_contexts(shell: PyBashShell) -> None:
    shell.system_context["load"] = "bad"
    with pytest.raises(ShellRuntimeError):
        shell._update_load_snapshot()

    shell.system_context["load"] = {"avg_1": 0.1, "avg_5": 0.1, "avg_15": 0.1}
    shell.system_context["runtime"] = "bad"
    with pytest.raises(ShellRuntimeError):
        shell._update_load_snapshot()


def test_format_uptime_day_variants(shell: PyBashShell) -> None:
    assert shell._format_uptime(3600) == "1:00"
    assert shell._format_uptime(90061) == "1 day, 01:01"
    assert shell._format_uptime(176461) == "2 days, 01:01"

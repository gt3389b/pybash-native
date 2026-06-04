from __future__ import annotations

from dataclasses import dataclass
import re
import shlex
from typing import Callable

from .vfs import ShellRuntimeError, VirtualFileSystem


@dataclass
class ParsedCommand:
    argv: list[str]
    stdin_path: str | None = None
    stdout_path: str | None = None
    stdout_append: bool = False


class PyBashShell:
    """Native Python Bash-like shell with no host command execution."""

    def __init__(self) -> None:
        self.vfs = VirtualFileSystem()
        self.cwd = "/"
        self.running = True
        self.last_status = 0
        self.history: list[str] = []
        self.env = {
            "HOME": "/home/user",
            "USER": "user",
            "SHELL": "pybash",
            "PS1": "pybash$ ",
        }
        self._boot_filesystem()
        self.builtins: dict[str, Callable[[list[str], str], tuple[int, str, str]]] = {
            "help": self._cmd_help,
            "exit": self._cmd_exit,
            "cd": self._cmd_cd,
            "pwd": self._cmd_pwd,
            "echo": self._cmd_echo,
            "set": self._cmd_set,
            "export": self._cmd_export,
            "unset": self._cmd_unset,
            "history": self._cmd_history,
            "ls": self._cmd_ls,
            "mkdir": self._cmd_mkdir,
            "touch": self._cmd_touch,
            "cat": self._cmd_cat,
            "write": self._cmd_write,
            "append": self._cmd_append,
            "rm": self._cmd_rm,
            "rmdir": self._cmd_rmdir,
            "whoami": self._cmd_whoami,
            "true": self._cmd_true,
            "false": self._cmd_false,
            "tee": self._cmd_tee,
            "dup": self._cmd_dup,
            "test": self._cmd_test,
            "[": self._cmd_test_bracket,
        }

    def _boot_filesystem(self) -> None:
        self.vfs.mkdir("/home")
        self.vfs.mkdir("/home/user")
        self.vfs.mkdir("/tmp")
        self.cwd = "/home/user"

    def run(self) -> None:
        while self.running:
            try:
                line = input(self._prompt())
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                self.last_status = 130
                continue

            self.execute_line(line)

    def _prompt(self) -> str:
        return self.env.get("PS1", "pybash$ ").replace("\\w", self.cwd)

    def execute_line(self, line: str) -> int:
        line = line.strip()
        if not line:
            return self.last_status

        self.history.append(line)

        status = self.last_status
        for segment in self._split_statements(line):
            status = self._execute_conditional_chain(segment, status)
        self.last_status = status
        return status

    def _execute_conditional_chain(self, statement: str, status: int) -> int:
        for op, segment in self._split_conditionals(statement):
            should_run = op is None or (op == "&&" and status == 0) or (op == "||" and status != 0)
            if not should_run:
                continue

            status, stdout, stderr = self._execute_pipeline(segment)
            if stdout:
                print(stdout, end="" if stdout.endswith("\n") else "\n")
            if stderr:
                print(stderr, end="" if stderr.endswith("\n") else "\n")

        return status

    def _split_statements(self, line: str) -> list[str]:
        chunks: list[str] = []
        current: list[str] = []
        quote: str | None = None
        escaped = False
        for ch in line:
            if escaped:
                current.append(ch)
                escaped = False
                continue
            if ch == "\\":
                current.append(ch)
                escaped = True
                continue
            if ch in ('"', "'"):
                if quote is None:
                    quote = ch
                elif quote == ch:
                    quote = None
            if ch == ";" and quote is None:
                candidate = "".join(current).strip()
                if candidate:
                    chunks.append(candidate)
                current = []
            else:
                current.append(ch)
        tail = "".join(current).strip()
        if tail:
            chunks.append(tail)
        return chunks

    def _split_conditionals(self, line: str) -> list[tuple[str | None, str]]:
        parts: list[tuple[str | None, str]] = []
        current: list[str] = []
        quote: str | None = None
        escaped = False
        pending_op: str | None = None
        i = 0

        while i < len(line):
            ch = line[i]

            if escaped:
                current.append(ch)
                escaped = False
                i += 1
                continue
            if ch == "\\":
                current.append(ch)
                escaped = True
                i += 1
                continue

            if ch in ('"', "'"):
                if quote is None:
                    quote = ch
                elif quote == ch:
                    quote = None
                current.append(ch)
                i += 1
                continue

            if quote is None and i + 1 < len(line):
                op = line[i : i + 2]
                if op in {"&&", "||"}:
                    segment = "".join(current).strip()
                    if not segment:
                        raise ShellRuntimeError("invalid null command")
                    parts.append((pending_op, segment))
                    pending_op = op
                    current = []
                    i += 2
                    continue

            current.append(ch)
            i += 1

        tail = "".join(current).strip()
        if not tail:
            raise ShellRuntimeError("invalid null command")
        parts.append((pending_op, tail))
        return parts

    def _tokenize(self, line: str) -> list[str]:
        try:
            lexer = shlex.shlex(line, posix=True, punctuation_chars="|<>")
            lexer.whitespace_split = True
            lexer.commenters = ""
            return list(lexer)
        except ValueError as err:
            raise ShellRuntimeError(str(err)) from err

    def _parse_pipeline(self, line: str) -> list[ParsedCommand]:
        tokens = self._tokenize(line)
        if not tokens:
            return []

        commands: list[ParsedCommand] = []
        current = ParsedCommand(argv=[])
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token == "|":
                if not current.argv:
                    raise ShellRuntimeError("invalid null command")
                commands.append(current)
                current = ParsedCommand(argv=[])
                i += 1
                continue

            if token in ("<", ">"):
                if i + 1 >= len(tokens):
                    raise ShellRuntimeError("redirection missing path")
                target = self._expand(tokens[i + 1])
                if token == "<":
                    current.stdin_path = target
                else:
                    current.stdout_path = target
                    current.stdout_append = False
                i += 2
                continue

            if token == ">>":
                if i + 1 >= len(tokens):
                    raise ShellRuntimeError("redirection missing path")
                current.stdout_path = self._expand(tokens[i + 1])
                current.stdout_append = True
                i += 2
                continue

            current.argv.append(self._expand(token))
            i += 1

        if not current.argv:
            raise ShellRuntimeError("invalid null command")
        commands.append(current)
        return commands

    def _expand(self, token: str) -> str:
        token = self._expand_tilde(token)
        return self._expand_vars(token)

    def _expand_tilde(self, token: str) -> str:
        if token.startswith("~"):
            home = self.env.get("HOME", "/home/user")
            if token == "~":
                return home
            if token.startswith("~/"):
                return f"{home}/{token[2:]}"
        return token

    def _expand_vars(self, token: str) -> str:
        pattern = re.compile(r"\$\?|\$\$|\$\{[A-Za-z_][A-Za-z0-9_]*\}|\$[A-Za-z_][A-Za-z0-9_]*")

        def repl(match: re.Match[str]) -> str:
            key = match.group(0)
            if key == "$?":
                return str(self.last_status)
            if key == "$$":
                return "1"
            if key.startswith("${"):
                name = key[2:-1]
            else:
                name = key[1:]
            return self.env.get(name, "")

        return pattern.sub(repl, token)

    def _execute_pipeline(self, line: str) -> tuple[int, str, str]:
        try:
            commands = self._parse_pipeline(line)
        except ShellRuntimeError as err:
            return 2, "", f"pybash: {err}"

        stdin_buffer = ""
        final_stdout = ""
        final_stderr = ""
        status = 0

        for index, cmd in enumerate(commands):
            if cmd.stdin_path:
                abs_in = self.vfs.normalize(self.cwd, cmd.stdin_path)
                try:
                    stdin_buffer = self.vfs.read_file(abs_in)
                except ShellRuntimeError as err:
                    return 1, "", f"pybash: {err}"

            status, stdout, stderr = self._run_command(cmd.argv, stdin_buffer)
            stdin_buffer = stdout

            if index == len(commands) - 1:
                if cmd.stdout_path:
                    abs_out = self.vfs.normalize(self.cwd, cmd.stdout_path)
                    try:
                        if cmd.stdout_append:
                            self.vfs.append_file(abs_out, stdout)
                        else:
                            self.vfs.write_file(abs_out, stdout)
                    except ShellRuntimeError as err:
                        return 1, "", f"pybash: {err}"
                    final_stdout = ""
                else:
                    final_stdout = stdout
                final_stderr = stderr

        return status, final_stdout, final_stderr

    def _run_command(self, argv: list[str], stdin_text: str) -> tuple[int, str, str]:
        if not argv:
            return 0, "", ""

        name = argv[0]
        handler = self.builtins.get(name)
        if handler is None:
            return 127, "", f"pybash: command not found: {name}"

        try:
            return handler(argv[1:], stdin_text)
        except ShellRuntimeError as err:
            return 1, "", f"pybash: {name}: {err}"

    def _cmd_help(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = (args, stdin_text)
        items = sorted(self.builtins.keys())
        return 0, "builtins: " + " ".join(items), ""

    def _cmd_exit(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        code = self.last_status
        if args:
            try:
                code = int(args[0])
            except ValueError:
                return 2, "", "pybash: exit: numeric argument required"
        self.running = False
        return code, "", ""

    def _cmd_cd(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        target = args[0] if args else self.env.get("HOME", "/home/user")
        abs_target = self.vfs.normalize(self.cwd, target)
        if not self.vfs.is_dir(abs_target):
            raise ShellRuntimeError(f"no such directory: {target}")
        self.cwd = abs_target
        return 0, "", ""

    def _cmd_pwd(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = (args, stdin_text)
        return 0, self.cwd, ""

    def _cmd_echo(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        newline = True
        if args and args[0] == "-n":
            newline = False
            args = args[1:]
        text = " ".join(args)
        if newline:
            text += "\n"
        return 0, text, ""

    def _cmd_set(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = (args, stdin_text)
        lines = [f"{k}={v}" for k, v in sorted(self.env.items())]
        return 0, "\n".join(lines), ""

    def _cmd_export(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        if not args:
            return self._cmd_set([], "")
        for item in args:
            if "=" not in item:
                self.env[item] = self.env.get(item, "")
                continue
            key, value = item.split("=", 1)
            if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
                raise ShellRuntimeError(f"not a valid identifier: {key}")
            self.env[key] = value
        return 0, "", ""

    def _cmd_unset(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        for key in args:
            self.env.pop(key, None)
        return 0, "", ""

    def _cmd_history(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = (args, stdin_text)
        lines = [f"{i + 1}  {entry}" for i, entry in enumerate(self.history)]
        return 0, "\n".join(lines), ""

    def _cmd_ls(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        path = args[0] if args else "."
        abs_path = self.vfs.normalize(self.cwd, path)
        names = self.vfs.listdir(abs_path)
        return 0, "\n".join(names), ""

    def _cmd_mkdir(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        if not args:
            raise ShellRuntimeError("missing operand")
        for path in args:
            self.vfs.mkdir(self.vfs.normalize(self.cwd, path))
        return 0, "", ""

    def _cmd_touch(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        if not args:
            raise ShellRuntimeError("missing file operand")
        for path in args:
            self.vfs.touch(self.vfs.normalize(self.cwd, path))
        return 0, "", ""

    def _cmd_cat(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        if not args:
            return 0, stdin_text, ""
        chunks: list[str] = []
        for path in args:
            chunks.append(self.vfs.read_file(self.vfs.normalize(self.cwd, path)))
        return 0, "".join(chunks), ""

    def _cmd_write(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        if not args:
            raise ShellRuntimeError("usage: write FILE [TEXT...]")
        file_path = self.vfs.normalize(self.cwd, args[0])
        text = " ".join(args[1:]) if len(args) > 1 else stdin_text
        self.vfs.write_file(file_path, text)
        return 0, "", ""

    def _cmd_append(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        if not args:
            raise ShellRuntimeError("usage: append FILE [TEXT...]")
        file_path = self.vfs.normalize(self.cwd, args[0])
        text = " ".join(args[1:]) if len(args) > 1 else stdin_text
        self.vfs.append_file(file_path, text)
        return 0, "", ""

    def _cmd_rm(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        if not args:
            raise ShellRuntimeError("missing operand")
        for path in args:
            self.vfs.rm_file(self.vfs.normalize(self.cwd, path))
        return 0, "", ""

    def _cmd_rmdir(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        if not args:
            raise ShellRuntimeError("missing operand")
        for path in args:
            self.vfs.rmdir(self.vfs.normalize(self.cwd, path))
        return 0, "", ""

    def _cmd_whoami(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = (args, stdin_text)
        return 0, self.env.get("USER", "user"), ""

    def _cmd_true(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = (args, stdin_text)
        return 0, "", ""

    def _cmd_false(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = (args, stdin_text)
        return 1, "", ""

    def _cmd_tee(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        append_mode = False
        if args and args[0] == "-a":
            append_mode = True
            args = args[1:]

        for path in args:
            abs_path = self.vfs.normalize(self.cwd, path)
            if append_mode:
                self.vfs.append_file(abs_path, stdin_text)
            else:
                self.vfs.write_file(abs_path, stdin_text)

        return 0, stdin_text, ""

    def _cmd_dup(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        count = 2
        if args:
            try:
                count = int(args[0])
            except ValueError as err:
                raise ShellRuntimeError("dup: COUNT must be an integer") from err
        if count < 0:
            raise ShellRuntimeError("dup: COUNT must be >= 0")
        return 0, stdin_text * count, ""

    def _cmd_test_bracket(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        if not args or args[-1] != "]":
            return 2, "", "pybash: [: missing ']'"
        return self._cmd_test(args[:-1], stdin_text)

    def _cmd_test(self, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        _ = stdin_text
        try:
            ok = self._eval_test_expr(args)
        except ShellRuntimeError as err:
            return 2, "", f"pybash: test: {err}"
        return (0 if ok else 1), "", ""

    def _eval_test_expr(self, args: list[str]) -> bool:
        if not args:
            return False

        if len(args) == 1:
            return args[0] != ""

        if len(args) == 2:
            op, value = args
            if op == "-n":
                return value != ""
            if op == "-z":
                return value == ""
            abs_path = self.vfs.normalize(self.cwd, value)
            if op == "-e":
                return self.vfs.exists(abs_path)
            if op == "-d":
                return self.vfs.is_dir(abs_path)
            if op == "-f":
                return self.vfs.is_file(abs_path)
            raise ShellRuntimeError(f"unsupported unary operator: {op}")

        if len(args) == 3:
            left, op, right = args
            if op == "=":
                return left == right
            if op == "!=":
                return left != right
            raise ShellRuntimeError(f"unsupported binary operator: {op}")

        raise ShellRuntimeError("complex test expressions are not supported yet")


__all__ = ["PyBashShell", "ShellRuntimeError", "VirtualFileSystem"]

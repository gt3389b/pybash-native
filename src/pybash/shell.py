from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import time
from typing import Any, Callable, Mapping

from jinja2 import Environment, StrictUndefined, TemplateError

from .vfs import ShellRuntimeError, VirtualFileSystem


@dataclass
class ParsedCommand:
    argv: list[str]
    stdin_path: str | None = None
    stdout_path: str | None = None
    stdout_append: bool = False


BuiltinHandler = Callable[[list[str], str], tuple[int, str, str]]
TemplateHookResult = Mapping[str, Any] | tuple[int, str, str] | None
TemplateHook = Callable[[dict[str, Any]], TemplateHookResult]


class PyBashShell:
    """Native Python Bash-like shell with no host command execution."""

    def __init__(
        self,
        *,
        initial_env: Mapping[str, str] | None = None,
        system_context: Mapping[str, Any] | None = None,
        builtin_overrides: Mapping[str, BuiltinHandler] | None = None,
        builtin_templates: Mapping[str, str] | None = None,
        builtin_template_hooks: Mapping[str, TemplateHook] | None = None,
        template_utilities: Mapping[str, Callable[..., Any]] | None = None,
        template_dir: str | Path | None = None,
        now_provider: Callable[[], float] | None = None,
    ) -> None:
        self.vfs = VirtualFileSystem()
        self.cwd = "/"
        self.running = True
        self.last_status = 0
        self.exit_code = 0
        self.history: list[str] = []
        self.env: dict[str, str] = {
            "HOME": "/home/user",
            "USER": "user",
            "SHELL": "pybash",
            "PS1": "pybash$ ",
        }
        if initial_env:
            self.env.update(dict(initial_env))
        self._now_provider = now_provider or time.time

        self.system_context = self._default_system_context()
        if system_context:
            self.update_system_context(system_context)
        runtime = self.system_context.setdefault("runtime", {})
        if not isinstance(runtime, dict):
            raise ShellRuntimeError("system_context.runtime is not mutable")
        runtime.setdefault("boot_epoch", int(self._now_provider()))
        runtime.setdefault("last_load_epoch", int(self._now_provider()))

        self._template_environment = Environment(
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
            undefined=StrictUndefined,
        )
        self.template_utilities = self._default_template_utilities()
        if template_utilities:
            self.template_utilities.update(dict(template_utilities))
        self._template_environment.globals.update(self.template_utilities)
        self._template_builtins: dict[str, str] = {}
        self._template_builtin_hooks: dict[str, TemplateHook] = {}
        self._template_builtin_sources: dict[str, Path] = {}
        self._default_template_dir = Path(__file__).resolve().parent / "templates"
        if template_dir is None:
            self.template_dir = self._default_template_dir
        else:
            self.template_dir = Path(template_dir).expanduser().resolve()

        self._boot_filesystem()
        self.builtins: dict[str, BuiltinHandler] = {
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
        self._register_default_template_builtins()

        if builtin_templates:
            hooks = dict(builtin_template_hooks or {})
            for name, template in builtin_templates.items():
                self.register_template_builtin(name, template, hook=hooks.get(name), replace=True)

        if builtin_template_hooks:
            for name, hook in builtin_template_hooks.items():
                if builtin_templates and name in builtin_templates:
                    continue
                self.register_template_hook(name, hook, replace=True)

        if builtin_overrides:
            for name, handler in builtin_overrides.items():
                self.register_builtin(name, handler, replace=True)

    def _default_template_utilities(self) -> dict[str, Callable[..., Any]]:
        def tojson(value: Any) -> str:
            return json.dumps(value, sort_keys=True)

        def now_utc() -> str:
            return datetime.now(timezone.utc).isoformat()

        def join_lines(items: list[Any]) -> str:
            return "\n".join(str(item) for item in items)

        return {
            "tojson": tojson,
            "now_utc": now_utc,
            "shquote": shlex.quote,
            "join_lines": join_lines,
        }

    def register_template_utility(self, name: str, utility: Callable[..., Any], *, replace: bool = False) -> None:
        if not name:
            raise ShellRuntimeError("template utility name must not be empty")
        if not replace and name in self.template_utilities:
            raise ShellRuntimeError(f"template utility already exists: {name}")
        self.template_utilities[name] = utility
        self._template_environment.globals[name] = utility

    def _default_system_context(self) -> dict[str, Any]:
        return {
            "uname": {
                "sysname": "PyBash",
                "nodename": "pybash",
                "release": "0.1",
                "version": "pybash-native",
                "machine": "pyvm",
            },
            "os_release": {
                "NAME": "PyBash Linux",
                "ID": "pybash",
                "VERSION_ID": "0.1",
                "PRETTY_NAME": "PyBash Linux 0.1",
                "HOME_URL": "https://example.invalid/pybash",
            },
            "identity": {
                "uid": 1000,
                "gid": 1000,
                "user": "user",
                "group": "user",
                "groups": [
                    {"gid": 1000, "name": "user"},
                    {"gid": 4, "name": "adm"},
                ],
            },
            "runtime": {
                "boot_epoch": 0,
                "last_load_epoch": 0,
            },
            "sessions": {
                "active_users": 1,
            },
            "load": {
                "avg_1": 0.11,
                "avg_5": 0.07,
                "avg_15": 0.05,
                "trend_per_min": 0.02,
            },
            "interfaces": {
                "lo0": {
                    "flags": "8049<UP,LOOPBACK,RUNNING,MULTICAST>",
                    "mtu": 16384,
                    "inet": "127.0.0.1",
                    "netmask": "0xff000000",
                    "ether": "00:00:00:00:00:00",
                }
            },
        }

    def register_builtin(
        self,
        name: str,
        handler: BuiltinHandler,
        *,
        replace: bool = False,
    ) -> None:
        if not name:
            raise ShellRuntimeError("builtin name must not be empty")
        if not replace and name in self.builtins:
            raise ShellRuntimeError(f"builtin already exists: {name}")
        self.builtins[name] = handler

    def register_template_builtin(
        self,
        name: str,
        template: str,
        *,
        hook: TemplateHook | None = None,
        replace: bool = False,
    ) -> None:
        if not name:
            raise ShellRuntimeError("builtin name must not be empty")
        if not replace and name in self.builtins:
            raise ShellRuntimeError(f"builtin already exists: {name}")
        try:
            self._template_environment.from_string(template)
        except TemplateError as err:
            raise ShellRuntimeError(f"invalid template for builtin {name}: {err}") from err

        self._template_builtins[name] = template
        if replace:
            self._template_builtin_sources.pop(name, None)
        if hook is not None:
            self._template_builtin_hooks[name] = hook
        elif replace:
            self._template_builtin_hooks.pop(name, None)
        self.builtins[name] = self._build_template_builtin_handler(name)

    def load_template_builtin(
        self,
        name: str,
        template_path: str | Path,
        *,
        hook: TemplateHook | None = None,
        replace: bool = False,
    ) -> None:
        resolved_path = Path(template_path)
        if not resolved_path.is_absolute():
            resolved_path = self.template_dir / resolved_path
        resolved_path = resolved_path.resolve()

        try:
            template = resolved_path.read_text(encoding="utf-8")
        except OSError as err:
            raise ShellRuntimeError(f"unable to load template {resolved_path}: {err}") from err

        self.register_template_builtin(name, template, hook=hook, replace=replace)
        self._template_builtin_sources[name] = resolved_path

    def register_template_hook(self, name: str, hook: TemplateHook, *, replace: bool = False) -> None:
        if name not in self._template_builtins:
            raise ShellRuntimeError(f"template builtin does not exist: {name}")
        if not replace and name in self._template_builtin_hooks:
            raise ShellRuntimeError(f"template hook already exists: {name}")
        self._template_builtin_hooks[name] = hook

    def _register_default_template_builtins(self) -> None:
        self.load_template_builtin(
            "uname",
            self._default_template_dir / "uname.tmpl",
            hook=self._hook_uname,
            replace=True,
        )
        self.load_template_builtin(
            "ifconfig",
            self._default_template_dir / "ifconfig.tmpl",
            hook=self._hook_ifconfig,
            replace=True,
        )
        self.load_template_builtin(
            "hostname",
            self._default_template_dir / "hostname.tmpl",
            hook=self._hook_hostname,
            replace=True,
        )
        self.load_template_builtin(
            "os-release",
            self._default_template_dir / "os-release.tmpl",
            hook=self._hook_os_release,
            replace=True,
        )
        self.load_template_builtin(
            "id",
            self._default_template_dir / "id.tmpl",
            hook=self._hook_id,
            replace=True,
        )
        self.load_template_builtin(
            "uptime",
            self._default_template_dir / "uptime.tmpl",
            hook=self._hook_uptime,
            replace=True,
        )
        self.load_template_builtin(
            "load",
            self._default_template_dir / "load.tmpl",
            hook=self._hook_load,
            replace=True,
        )

    def _build_template_builtin_handler(self, name: str) -> BuiltinHandler:
        def handler(args: list[str], stdin_text: str) -> tuple[int, str, str]:
            return self._run_template_builtin(name, args, stdin_text)

        return handler

    def _build_template_context(self, name: str, args: list[str], stdin_text: str) -> dict[str, Any]:
        return {
            "command": name,
            "args": list(args),
            "argv": [name, *args],
            "stdin": stdin_text,
            "env": self.env,
            "system": self.system_context,
            "cwd": self.cwd,
            "last_status": self.last_status,
            "shell": self,
        }

    def _run_template_builtin(self, name: str, args: list[str], stdin_text: str) -> tuple[int, str, str]:
        template_source = self._template_builtins.get(name)
        if template_source is None:
            return 1, "", f"pybash: {name}: template builtin not found"

        context = self._build_template_context(name, args, stdin_text)
        hook = self._template_builtin_hooks.get(name)
        if hook is not None:
            try:
                hook_result = hook(context)
            except ShellRuntimeError as err:
                return 1, "", f"pybash: {name}: {err}"
            except Exception as err:
                return 1, "", f"pybash: {name}: hook error: {err}"

            if hook_result is not None:
                if isinstance(hook_result, tuple) and len(hook_result) == 3:
                    return int(hook_result[0]), str(hook_result[1]), str(hook_result[2])
                if isinstance(hook_result, Mapping):
                    context.update(dict(hook_result))
                else:
                    return 1, "", f"pybash: {name}: hook must return mapping, 3-tuple, or None"

        try:
            rendered = self._template_environment.from_string(template_source).render(**context)
        except TemplateError as err:
            return 1, "", f"pybash: {name}: template error: {err}"
        return 0, str(rendered), ""

    def _hook_uname(self, context: dict[str, Any]) -> TemplateHookResult:
        args = context.get("args", [])
        if not isinstance(args, list):
            return 1, "", "pybash: uname: invalid arguments"

        uname_context = self.system_context.get("uname", {})
        if not isinstance(uname_context, Mapping):
            return 1, "", "pybash: uname: invalid system context"

        field_order = ["sysname", "nodename", "release", "version", "machine"]

        def field(name: str) -> str:
            return str(uname_context.get(name, ""))

        if not args:
            return {
                "uname_fields": [{"name": "sysname", "value": field("sysname")}],
            }

        supported = {
            "-s": "sysname",
            "-n": "nodename",
            "-r": "release",
            "-v": "version",
            "-m": "machine",
        }

        selected: list[str] = []
        for arg in args:
            if arg == "-a":
                selected.extend(field_order)
                continue

            if arg.startswith("-") and len(arg) > 2:
                for opt in arg[1:]:
                    key = supported.get(f"-{opt}")
                    if key is None:
                        return 1, "", f"pybash: uname: unsupported option: -{opt}"
                    selected.append(key)
                continue

            key = supported.get(arg)
            if key is None:
                return 1, "", f"pybash: uname: unsupported option: {arg}"
            selected.append(key)

        return {
            "uname_fields": [{"name": name, "value": field(name)} for name in selected],
        }

    def _normalize_interface(self, name: str, iface: Mapping[str, Any]) -> dict[str, Any]:
        flags = str(iface.get("flags", ""))
        mtu_raw = iface.get("mtu", 1500)
        try:
            mtu = int(mtu_raw)
        except (TypeError, ValueError):
            mtu = 1500

        inet = iface.get("inet")
        netmask = iface.get("netmask")
        ether = iface.get("ether")

        address_lines: list[dict[str, str]] = []
        if inet:
            value = str(inet)
            if netmask:
                value += f" netmask {netmask}"
            address_lines.append({"label": "inet", "value": value})
        if ether:
            address_lines.append({"label": "ether", "value": str(ether)})

        return {
            "name": str(name),
            "flags": flags,
            "mtu": mtu,
            "address_lines": address_lines,
        }

    def _hook_ifconfig(self, context: dict[str, Any]) -> TemplateHookResult:
        args = context.get("args", [])
        if not isinstance(args, list):
            return 1, "", "pybash: ifconfig: invalid arguments"

        interfaces = self.system_context.get("interfaces", {})
        if not isinstance(interfaces, Mapping):
            return 1, "", "pybash: ifconfig: invalid interfaces context"

        if len(args) > 1:
            return 1, "", "pybash: ifconfig: usage: ifconfig [INTERFACE]"

        if args:
            name = args[0]
            iface = interfaces.get(name)
            if not isinstance(iface, Mapping):
                return 1, "", f"pybash: ifconfig: interface not found: {name}"
            return {"interfaces": [self._normalize_interface(name, iface)]}

        normalized: list[dict[str, Any]] = []
        for name in sorted(interfaces.keys()):
            iface = interfaces.get(name)
            if isinstance(iface, Mapping):
                normalized.append(self._normalize_interface(str(name), iface))
        return {"interfaces": normalized}

    def _hook_hostname(self, context: dict[str, Any]) -> TemplateHookResult:
        args = context.get("args", [])
        if not isinstance(args, list):
            return 1, "", "pybash: hostname: invalid arguments"

        nodename = str(self.system_context.get("uname", {}).get("nodename", ""))
        if not args:
            return {"hostname": nodename}
        if len(args) == 1 and args[0] == "-s":
            return {"hostname": nodename.split(".", 1)[0]}
        return 1, "", "pybash: hostname: usage: hostname [-s]"

    def _hook_os_release(self, context: dict[str, Any]) -> TemplateHookResult:
        args = context.get("args", [])
        if not isinstance(args, list):
            return 1, "", "pybash: os-release: invalid arguments"

        os_release = self.system_context.get("os_release", {})
        if not isinstance(os_release, Mapping):
            return 1, "", "pybash: os-release: invalid os_release context"

        if args and any(arg.startswith("-") for arg in args):
            return 1, "", "pybash: os-release: usage: os-release [KEY ...]"

        if args:
            values = [str(os_release.get(key, "")) for key in args]
            return {"os_release_mode": "values", "os_release_values": values}

        items = [{"key": str(key), "value": str(value)} for key, value in os_release.items()]
        return {"os_release_mode": "pairs", "os_release_items": items}

    def _identity_context(self) -> dict[str, Any]:
        identity = self.system_context.get("identity", {})
        if not isinstance(identity, Mapping):
            raise ShellRuntimeError("invalid identity context")

        user = str(identity.get("user", self.env.get("USER", "user")))
        group = str(identity.get("group", user))
        uid = int(identity.get("uid", 1000))
        gid = int(identity.get("gid", 1000))

        groups_raw = identity.get("groups", [{"gid": gid, "name": group}])
        groups: list[dict[str, Any]] = []
        if isinstance(groups_raw, list):
            for entry in groups_raw:
                if isinstance(entry, Mapping):
                    group_gid = int(entry.get("gid", gid))
                    group_name = str(entry.get("name", group))
                    groups.append({"gid": group_gid, "name": group_name})
                else:
                    groups.append({"gid": int(entry), "name": str(entry)})
        if not groups:
            groups.append({"gid": gid, "name": group})

        return {
            "user": user,
            "group": group,
            "uid": uid,
            "gid": gid,
            "groups": groups,
        }

    def _hook_id(self, context: dict[str, Any]) -> TemplateHookResult:
        args = context.get("args", [])
        if not isinstance(args, list):
            return 1, "", "pybash: id: invalid arguments"

        try:
            identity = self._identity_context()
        except (ValueError, TypeError, ShellRuntimeError):
            return 1, "", "pybash: id: invalid identity context"

        if not args:
            return {"id_mode": "default", "identity": identity}

        opts = set()
        for arg in args:
            if not arg.startswith("-") or len(arg) == 1:
                return 1, "", "pybash: id: usage: id [-u|-g|-G] [-n]"
            for ch in arg[1:]:
                if ch not in {"u", "g", "G", "n"}:
                    return 1, "", f"pybash: id: unsupported option: -{ch}"
                opts.add(ch)

        if "n" in opts and not ({"u", "g", "G"} & opts):
            return 1, "", "pybash: id: -n requires -u, -g, or -G"

        lines: list[str] = []
        if "u" in opts:
            lines.append(identity["user"] if "n" in opts else str(identity["uid"]))
        if "g" in opts:
            lines.append(identity["group"] if "n" in opts else str(identity["gid"]))
        if "G" in opts:
            if "n" in opts:
                lines.append(" ".join(group["name"] for group in identity["groups"]))
            else:
                lines.append(" ".join(str(group["gid"]) for group in identity["groups"]))

        return {"id_mode": "lines", "id_lines": lines}

    def _runtime_context(self) -> dict[str, Any]:
        runtime = self.system_context.get("runtime", {})
        if not isinstance(runtime, Mapping):
            raise ShellRuntimeError("invalid runtime context")
        return {
            "boot_epoch": int(runtime.get("boot_epoch", int(self._now_provider()))),
            "last_load_epoch": int(runtime.get("last_load_epoch", int(self._now_provider()))),
        }

    def _sessions_context(self) -> dict[str, Any]:
        sessions = self.system_context.get("sessions", {})
        if not isinstance(sessions, Mapping):
            raise ShellRuntimeError("invalid sessions context")
        return {
            "active_users": int(sessions.get("active_users", 1)),
        }

    def _update_load_snapshot(self) -> dict[str, float]:
        load_ctx = self.system_context.get("load", {})
        if not isinstance(load_ctx, Mapping):
            raise ShellRuntimeError("invalid load context")

        runtime_ctx = self.system_context.get("runtime", {})
        if not isinstance(runtime_ctx, dict):
            raise ShellRuntimeError("invalid runtime context")

        now_epoch = int(self._now_provider())
        last_epoch = int(runtime_ctx.get("last_load_epoch", now_epoch))
        delta_seconds = max(0, now_epoch - last_epoch)
        delta_minutes = delta_seconds / 60.0
        trend = float(load_ctx.get("trend_per_min", 0.0))

        avg_1 = max(0.0, float(load_ctx.get("avg_1", 0.0)) + trend * delta_minutes)
        avg_5 = max(0.0, float(load_ctx.get("avg_5", 0.0)) + (trend * 0.7) * delta_minutes)
        avg_15 = max(0.0, float(load_ctx.get("avg_15", 0.0)) + (trend * 0.4) * delta_minutes)

        if isinstance(load_ctx, dict):
            load_ctx["avg_1"] = avg_1
            load_ctx["avg_5"] = avg_5
            load_ctx["avg_15"] = avg_15
        runtime_ctx["last_load_epoch"] = now_epoch

        return {
            "avg_1": avg_1,
            "avg_5": avg_5,
            "avg_15": avg_15,
        }

    def _format_uptime(self, elapsed_seconds: int) -> str:
        days, rem = divmod(max(0, elapsed_seconds), 86400)
        hours, rem = divmod(rem, 3600)
        minutes, _ = divmod(rem, 60)
        if days > 0:
            unit = "day" if days == 1 else "days"
            return f"{days} {unit}, {hours:02d}:{minutes:02d}"
        return f"{hours}:{minutes:02d}"

    def _hook_uptime(self, context: dict[str, Any]) -> TemplateHookResult:
        args = context.get("args", [])
        if not isinstance(args, list):
            return 1, "", "pybash: uptime: invalid arguments"
        if args:
            return 1, "", "pybash: uptime: usage: uptime"

        try:
            runtime = self._runtime_context()
            sessions = self._sessions_context()
            load = self._update_load_snapshot()
        except (ShellRuntimeError, ValueError, TypeError):
            return 1, "", "pybash: uptime: invalid system context"

        now_epoch = int(self._now_provider())
        elapsed = max(0, now_epoch - runtime["boot_epoch"])
        return {
            "uptime": {
                "now_clock": datetime.fromtimestamp(now_epoch).strftime("%H:%M:%S"),
                "elapsed_seconds": elapsed,
                "pretty": self._format_uptime(elapsed),
                "active_users": sessions["active_users"],
                "load": load,
            }
        }

    def _hook_load(self, context: dict[str, Any]) -> TemplateHookResult:
        args = context.get("args", [])
        if not isinstance(args, list):
            return 1, "", "pybash: load: invalid arguments"
        if args:
            return 1, "", "pybash: load: usage: load"
        try:
            load = self._update_load_snapshot()
        except (ShellRuntimeError, ValueError, TypeError):
            return 1, "", "pybash: load: invalid system context"
        return {"load": load}

    def update_system_context(self, updates: Mapping[str, Any]) -> None:
        uname_updates = updates.get("uname")
        if uname_updates is not None:
            if not isinstance(uname_updates, Mapping):
                raise ShellRuntimeError("system_context.uname must be a mapping")
            uname_context = self.system_context.setdefault("uname", {})
            if not isinstance(uname_context, dict):
                raise ShellRuntimeError("system_context.uname is not mutable")
            for key in ("sysname", "nodename", "release", "version", "machine"):
                if key in uname_updates:
                    uname_context[key] = str(uname_updates[key])

        interfaces_updates = updates.get("interfaces")
        if interfaces_updates is not None:
            if not isinstance(interfaces_updates, Mapping):
                raise ShellRuntimeError("system_context.interfaces must be a mapping")
            interfaces_context = self.system_context.setdefault("interfaces", {})
            if not isinstance(interfaces_context, dict):
                raise ShellRuntimeError("system_context.interfaces is not mutable")
            for name, iface_data in interfaces_updates.items():
                if not isinstance(iface_data, Mapping):
                    raise ShellRuntimeError(f"interface {name} must be a mapping")
                iface = interfaces_context.setdefault(str(name), {})
                if not isinstance(iface, dict):
                    raise ShellRuntimeError(f"interface {name} is not mutable")
                for key, value in iface_data.items():
                    iface[str(key)] = value

        os_release_updates = updates.get("os_release")
        if os_release_updates is not None:
            if not isinstance(os_release_updates, Mapping):
                raise ShellRuntimeError("system_context.os_release must be a mapping")
            os_release_context = self.system_context.setdefault("os_release", {})
            if not isinstance(os_release_context, dict):
                raise ShellRuntimeError("system_context.os_release is not mutable")
            for key, value in os_release_updates.items():
                os_release_context[str(key)] = str(value)

        identity_updates = updates.get("identity")
        if identity_updates is not None:
            if not isinstance(identity_updates, Mapping):
                raise ShellRuntimeError("system_context.identity must be a mapping")
            identity_context = self.system_context.setdefault("identity", {})
            if not isinstance(identity_context, dict):
                raise ShellRuntimeError("system_context.identity is not mutable")
            for key, value in identity_updates.items():
                identity_context[str(key)] = value

        runtime_updates = updates.get("runtime")
        if runtime_updates is not None:
            if not isinstance(runtime_updates, Mapping):
                raise ShellRuntimeError("system_context.runtime must be a mapping")
            runtime_context = self.system_context.setdefault("runtime", {})
            if not isinstance(runtime_context, dict):
                raise ShellRuntimeError("system_context.runtime is not mutable")
            for key, value in runtime_updates.items():
                runtime_context[str(key)] = value

        sessions_updates = updates.get("sessions")
        if sessions_updates is not None:
            if not isinstance(sessions_updates, Mapping):
                raise ShellRuntimeError("system_context.sessions must be a mapping")
            sessions_context = self.system_context.setdefault("sessions", {})
            if not isinstance(sessions_context, dict):
                raise ShellRuntimeError("system_context.sessions is not mutable")
            for key, value in sessions_updates.items():
                sessions_context[str(key)] = value

        load_updates = updates.get("load")
        if load_updates is not None:
            if not isinstance(load_updates, Mapping):
                raise ShellRuntimeError("system_context.load must be a mapping")
            load_context = self.system_context.setdefault("load", {})
            if not isinstance(load_context, dict):
                raise ShellRuntimeError("system_context.load is not mutable")
            for key, value in load_updates.items():
                load_context[str(key)] = value

    def set_uname(
        self,
        *,
        sysname: str | None = None,
        nodename: str | None = None,
        release: str | None = None,
        version: str | None = None,
        machine: str | None = None,
    ) -> None:
        updates: dict[str, str] = {}
        if sysname is not None:
            updates["sysname"] = sysname
        if nodename is not None:
            updates["nodename"] = nodename
        if release is not None:
            updates["release"] = release
        if version is not None:
            updates["version"] = version
        if machine is not None:
            updates["machine"] = machine
        if updates:
            self.update_system_context({"uname": updates})

    def set_interface(
        self,
        name: str,
        *,
        flags: str | None = None,
        mtu: int | None = None,
        inet: str | None = None,
        netmask: str | None = None,
        ether: str | None = None,
    ) -> None:
        if not name:
            raise ShellRuntimeError("interface name must not be empty")
        updates: dict[str, Any] = {}
        if flags is not None:
            updates["flags"] = flags
        if mtu is not None:
            updates["mtu"] = mtu
        if inet is not None:
            updates["inet"] = inet
        if netmask is not None:
            updates["netmask"] = netmask
        if ether is not None:
            updates["ether"] = ether
        self.update_system_context({"interfaces": {name: updates}})

    def remove_interface(self, name: str) -> None:
        interfaces = self.system_context.get("interfaces", {})
        if not isinstance(interfaces, dict):
            raise ShellRuntimeError("system_context.interfaces is not mutable")
        interfaces.pop(name, None)

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
        self.exit_code = status
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
        self.exit_code = code
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

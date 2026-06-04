from __future__ import annotations

from dataclasses import dataclass, field


class ShellRuntimeError(Exception):
    """Raised when a shell operation fails."""


@dataclass
class VFile:
    content: str = ""


@dataclass
class VDirectory:
    children: dict[str, VNode] = field(default_factory=dict)


VNode = VFile | VDirectory


class VirtualFileSystem:
    """Simple in-memory filesystem used by the shell."""

    def __init__(self) -> None:
        self.root = VDirectory()

    def normalize(self, cwd: str, path: str) -> str:
        if not path:
            return cwd
        candidate = path if path.startswith("/") else f"{cwd.rstrip('/')}/{path}" if cwd != "/" else f"/{path}"
        parts: list[str] = []
        for part in candidate.split("/"):
            if part in ("", "."):
                continue
            if part == "..":
                if parts:
                    parts.pop()
                continue
            parts.append(part)
        return "/" + "/".join(parts)

    def _get_node(self, abs_path: str) -> VNode:
        if abs_path == "/":
            return self.root
        node: VNode = self.root
        for part in abs_path.strip("/").split("/"):
            if not isinstance(node, VDirectory):
                raise ShellRuntimeError(f"not a directory: {abs_path}")
            if part not in node.children:
                raise ShellRuntimeError(f"no such file or directory: {abs_path}")
            node = node.children[part]
        return node

    def _get_parent_dir(self, abs_path: str) -> tuple[VDirectory, str]:
        if abs_path == "/":
            raise ShellRuntimeError("cannot operate on root")
        parts = abs_path.strip("/").split("/")
        name = parts[-1]
        parent_path = "/" + "/".join(parts[:-1]) if len(parts) > 1 else "/"
        parent = self._get_node(parent_path)
        if not isinstance(parent, VDirectory):
            raise ShellRuntimeError(f"not a directory: {parent_path}")
        return parent, name

    def exists(self, abs_path: str) -> bool:
        try:
            self._get_node(abs_path)
            return True
        except ShellRuntimeError:
            return False

    def is_dir(self, abs_path: str) -> bool:
        try:
            return isinstance(self._get_node(abs_path), VDirectory)
        except ShellRuntimeError:
            return False

    def is_file(self, abs_path: str) -> bool:
        try:
            return isinstance(self._get_node(abs_path), VFile)
        except ShellRuntimeError:
            return False

    def mkdir(self, abs_path: str) -> None:
        parent, name = self._get_parent_dir(abs_path)
        if name in parent.children:
            raise ShellRuntimeError(f"file exists: {abs_path}")
        parent.children[name] = VDirectory()

    def listdir(self, abs_path: str) -> list[str]:
        node = self._get_node(abs_path)
        if not isinstance(node, VDirectory):
            raise ShellRuntimeError(f"not a directory: {abs_path}")
        return sorted(node.children.keys())

    def read_file(self, abs_path: str) -> str:
        node = self._get_node(abs_path)
        if not isinstance(node, VFile):
            raise ShellRuntimeError(f"not a file: {abs_path}")
        return node.content

    def write_file(self, abs_path: str, content: str) -> None:
        parent, name = self._get_parent_dir(abs_path)
        existing = parent.children.get(name)
        if isinstance(existing, VDirectory):
            raise ShellRuntimeError(f"is a directory: {abs_path}")
        parent.children[name] = VFile(content=content)

    def append_file(self, abs_path: str, content: str) -> None:
        parent, name = self._get_parent_dir(abs_path)
        existing = parent.children.get(name)
        if existing is None:
            parent.children[name] = VFile(content=content)
            return
        if not isinstance(existing, VFile):
            raise ShellRuntimeError(f"is a directory: {abs_path}")
        existing.content += content

    def touch(self, abs_path: str) -> None:
        parent, name = self._get_parent_dir(abs_path)
        existing = parent.children.get(name)
        if existing is None:
            parent.children[name] = VFile(content="")
            return
        if isinstance(existing, VDirectory):
            raise ShellRuntimeError(f"is a directory: {abs_path}")

    def rm_file(self, abs_path: str) -> None:
        parent, name = self._get_parent_dir(abs_path)
        existing = parent.children.get(name)
        if existing is None:
            raise ShellRuntimeError(f"no such file: {abs_path}")
        if isinstance(existing, VDirectory):
            raise ShellRuntimeError(f"is a directory: {abs_path}")
        del parent.children[name]

    def rmdir(self, abs_path: str) -> None:
        if abs_path == "/":
            raise ShellRuntimeError("cannot remove root")
        parent, name = self._get_parent_dir(abs_path)
        existing = parent.children.get(name)
        if existing is None:
            raise ShellRuntimeError(f"no such directory: {abs_path}")
        if not isinstance(existing, VDirectory):
            raise ShellRuntimeError(f"not a directory: {abs_path}")
        if existing.children:
            raise ShellRuntimeError(f"directory not empty: {abs_path}")
        del parent.children[name]

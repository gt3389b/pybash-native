from .shell import PyBashShell


def main() -> int:
    shell = PyBashShell()
    shell.run()
    return shell.exit_code

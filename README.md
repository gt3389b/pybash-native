# pybash

`pybash` is a native Python implementation of a Bash-like shell.

## Features

- Interactive REPL shell
- Built-ins only (no external process execution)
- Built-ins: `help`, `exit`, `cd`, `pwd`, `echo`, `set`, `export`, `unset`, `history`, `ls`, `mkdir`, `touch`, `cat`, `write`, `append`, `rm`, `rmdir`, `whoami`, `true`, `false`
- Variable expansion (`$VAR`, `${VAR}`, `$?`, `$$`)
- Tilde expansion (`~`)
- Pipelines (`|`)
- Redirection (`<`, `>`, `>>`)
- In-memory virtual filesystem

## Run

```bash
PYTHONPATH=src python -m pybash
```

Or after install:

```bash
pybash
```

## Notes

This shell never shells out to the host OS and never runs host commands.
It intentionally focuses on a practical, readable core shell implementation.
It is Bash-like, not Bash-complete.

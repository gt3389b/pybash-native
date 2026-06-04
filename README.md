# pybash-native

`pybash` is a native Python implementation of a Bash-like shell.

## Features

- Interactive REPL shell
- Built-ins only (no external process execution)
- Built-ins: `help`, `exit`, `cd`, `pwd`, `echo`, `set`, `export`, `unset`, `history`, `ls`, `mkdir`, `touch`, `cat`, `write`, `append`, `rm`, `rmdir`, `whoami`, `true`, `false`, `uname`, `ifconfig`, `hostname`, `os-release`, `id`, `uptime`, `load`
- Variable expansion (`$VAR`, `${VAR}`, `$?`, `$$`)
- Tilde expansion (`~`)
- Pipelines (`|`)
- Redirection (`<`, `>`, `>>`)
- In-memory virtual filesystem
- Formal customization hooks at instantiation and post-instantiation

## Run

```bash
PYTHONPATH=src python -m pybash
```

Alias module (matches the PyPI distribution name style):

```bash
PYTHONPATH=src python -m pybash_native
```

Or after install:

```bash
pybash
```

## Imports

```python
from pybash import PyBashShell
```

Or via alias package:

```python
from pybash_native import PyBashShell
```

## Customizing "System" Context

You can customize shell identity (for `uname`) and virtual network interfaces (for `ifconfig`) both at construction time and at runtime.

```python
from pybash import PyBashShell

# 1) Customize at instantiation.
shell = PyBashShell(
	initial_env={"USER": "alice"},
	system_context={
		"uname": {
			"sysname": "DemoOS",
			"nodename": "demo-host",
			"release": "9.9",
			"version": "demo-v1",
			"machine": "arm64",
		},
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

# 2) Customize after instantiation.
shell.set_uname(sysname="AcmeOS", machine="x86_64")
shell.set_interface(
	"en9",
	inet="192.168.64.2",
	netmask="0xffffff00",
	ether="aa:bb:cc:dd:ee:ff",
)

# 3) Register user-defined built-ins at runtime.
def hello(args, _stdin_text):
	return 0, "hello " + " ".join(args), ""

shell.register_builtin("hello", hello)
```

## Template Loader

Built-in command templates are stored as `.tmpl` files under `src/pybash/templates/`.
By default, core utility templates are loaded from:

- `src/pybash/templates/uname.tmpl`
- `src/pybash/templates/ifconfig.tmpl`
- `src/pybash/templates/hostname.tmpl`
- `src/pybash/templates/os-release.tmpl`
- `src/pybash/templates/id.tmpl`
- `src/pybash/templates/uptime.tmpl`
- `src/pybash/templates/load.tmpl`

You can load your own file-backed template built-ins:

```python
from pybash import PyBashShell

shell = PyBashShell(template_dir="./templates")

# Loads ./templates/osinfo.tmpl
shell.load_template_builtin("osinfo", "osinfo.tmpl")
```

You can still pair templates with hooks for advanced logic:

```python
def osinfo_hook(context):
	return {"value": context["system"]["uname"]["release"]}

shell.load_template_builtin("osinfo", "osinfo.tmpl", hook=osinfo_hook, replace=True)
```

## Notes

This shell never shells out to the host OS and never runs host commands.
It intentionally focuses on a practical, readable core shell implementation.
It is Bash-like, not Bash-complete.

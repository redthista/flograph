# Running Headless

A `.flograph` project is also a batch job. `flograph run` executes the whole
graph with no window and exits non-zero if a node failed, so a scheduler
(cron, a Dataiku recipe, CI) can run a canvas project unattended.

## From a terminal

```bash
flograph run project.flograph                       # run to completion
flograph run project.flograph --var region=North    # override a Variables value
flograph run project.flograph --var a=1 --var b=2   # repeat per variable
python -m flograph run project.flograph             # equivalent
```

- Exit code **0** if every node ran clean, **1** otherwise.
- Each node's log lines and any failure go to stdout/stderr as the run
  proceeds.
- `--var name=value` rewrites what the project's [[Flow Variables|Variables]]
  node declares, so one flow runs per region or per date with nothing edited
  in between. A name the flow does not declare is **refused**, not ignored.

`flograph` with no `run` subcommand — or with a path, `--version`, or nothing
— opens the GUI exactly as before.

## From Python

```python
import flograph

flograph.run("project.flograph", variables={"region": "North"})
```

Runs the same way and raises `RuntimeError` if a node fails; returns `None`
on success. `import flograph` stays cheap and Qt-free — the Qt imports are
lazy.

## The one caveat

The engine runs on a Qt event loop, so **PySide6 must be installed** for a
headless run — but no display is needed. Only `flograph.core` is strictly
Qt-free.

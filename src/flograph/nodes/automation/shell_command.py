"""Shell Command

Run an OS command from inside a flow and branch on how it went. Kick off a
`pg_dump`, an `rsync`, a `dbt run`, a `git pull`; capture what it printed and
its exit code.

The command is passed to the shell, so pipes and redirects work. `${name}`
flow variables are substituted first. **Working directory** and extra
**Environment** (`KEY=value` per line) are optional. **Fail on non-zero**
raises if the exit code isn't 0, so the flow stops the way a failed node
does; turn it off to inspect `exit_code` yourself downstream.

A wired `stdin` (string or DataFrame-as-CSV) is fed to the process. Runs with
nothing else in flight — a subprocess owns the machine while it runs.
"""
NODE = {
    "label": "Shell Command",
    "category": "Automation",
    "version": "1.0",
    "exclusive": True,
    "inputs": [("stdin", "any", {"optional": True})],
    "outputs": [
        ("stdout", "string"),
        ("stderr", "string"),
        ("exit_code", "number"),
    ],
}
PARAMS = [
    {"name": "command", "type": "text", "label": "Command",
     "default": "", "placeholder": "pg_dump mydb | gzip > backup.sql.gz"},
    {"name": "cwd", "type": "folder_open", "label": "Working directory",
     "default": ""},
    {"name": "env", "type": "text", "label": "Environment",
     "default": "", "placeholder": "PGPASSWORD=${env:PG_PASSWORD}"},
    {"name": "timeout", "type": "float", "label": "Timeout (s)",
     "default": 300.0, "min": 1.0, "max": 86400.0},
    {"name": "fail_on_nonzero", "type": "bool", "label": "Fail on non-zero exit",
     "default": True},
]


def run(ctx, stdin=None):
    import os
    import subprocess

    p = ctx.params
    command = (p.get("command") or "").strip()
    if not command:
        raise ValueError("no command — set 'Command'")

    env = os.environ.copy()
    for lineno, line in enumerate((p.get("env") or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, val = line.partition("=")
        if not sep or not key.strip():
            raise ValueError(f"environment line {lineno}: expected KEY=value")
        env[key.strip()] = val.strip()

    text_in = None
    if stdin is not None:
        try:
            import pandas as pd
            if isinstance(stdin, pd.DataFrame):
                text_in = stdin.to_csv(index=False)
        except Exception:  # noqa: BLE001
            pass
        if text_in is None:
            text_in = str(stdin)

    cwd = (p.get("cwd") or "").strip() or None
    timeout = float(p.get("timeout", 300.0))
    ctx.log(f"$ {command}")
    try:
        proc = subprocess.run(
            command, shell=True, cwd=cwd, env=env, input=text_in,
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"command timed out after {timeout:g}s") from exc

    ctx.log(f"exit {proc.returncode}"
            + (f" — {proc.stderr.strip()[:200]}" if proc.returncode else ""))
    if proc.returncode != 0 and p.get("fail_on_nonzero", True):
        raise ValueError(
            f"command exited {proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()[:400]}")

    return {"stdout": proc.stdout, "stderr": proc.stderr,
            "exit_code": int(proc.returncode)}

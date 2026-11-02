"""Run Flow

Runs another `.flograph` project in a separate process and returns the value
from its named Flow Output node. A current saved result is reused unless
Always run child is on; a missing or stale result runs the child. Child flows
run with the directory containing their project as the working directory.
"""
NODE = {
    "label": "Run Flow",
    "category": "Scripting",
    "version": "1.0",
    "exclusive": True,
    "inputs": [],
    "outputs": [("value", "any")],
}
PARAMS = [
    {"name": "project", "type": "file_open", "label": "Project",
     "default": "", "placeholder": "A .flograph or .flowf project"},
    {"name": "output", "type": "string", "label": "Output name",
     "default": "result"},
    {"name": "timeout", "type": "int", "label": "Timeout (seconds)",
     "default": 3600, "min": 1, "max": 86400},
    {"name": "always_run", "type": "bool", "label": "Always run child",
     "default": False},
    {"name": "variables", "type": "text", "label": "Variables",
     "default": "", "placeholder": "one name=value per line"},
]


def run(ctx):
    import os
    import pickle
    import subprocess
    import sys
    import tempfile
    import time
    from pathlib import Path

    project_text = str(ctx.params.get("project", "")).strip()
    if not project_text:
        raise ValueError("choose a .flograph project")
    project = Path(project_text).expanduser().resolve()
    if not project.is_file():
        raise FileNotFoundError(f"child project does not exist: {project}")
    if project.suffix.lower() not in {".flograph", ".flowf"}:
        raise ValueError("choose a .flograph or .flowf project")
    output_name = str(ctx.params.get("output", "")).strip()
    if not output_name:
        raise ValueError("enter the name of a Flow Output in the child project")
    timeout = int(ctx.params.get("timeout", 3600))
    if timeout < 1:
        raise ValueError("timeout must be at least one second")

    overrides = []
    for line_number, line in enumerate(
            str(ctx.params.get("variables", "") or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or not name.isidentifier():
            raise ValueError(
                f"Variables line {line_number} must be name=value")
        overrides.extend(("--var", f"{name}={value.strip()}"))

    with tempfile.TemporaryDirectory(prefix="flograph-child-") as scratch:
        output_file = Path(scratch) / "output.pkl"
        log_file = Path(scratch) / "child.log"
        command = [
            sys.executable, "-m", "flograph", "run", str(project),
            "--capture-output", output_name,
            "--capture-file", str(output_file),
            *overrides,
        ]
        if ctx.params.get("always_run"):
            command.append("--always-run")
        started = time.monotonic()
        with log_file.open("w", encoding="utf-8", errors="replace") as log:
            process = subprocess.Popen(
                command, cwd=project.parent, stdout=log,
                stderr=subprocess.STDOUT, env=os.environ.copy())
            try:
                while process.poll() is None:
                    ctx.check_cancelled()
                    if time.monotonic() - started >= timeout:
                        raise TimeoutError(
                            f"child flow exceeded its {timeout}s timeout")
                    time.sleep(0.1)
            except BaseException:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                raise
            return_code = process.returncode

        try:
            with log_file.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                stream.seek(max(0, stream.tell() - 65536))
                tail = stream.read().decode("utf-8", errors="replace")
        except OSError:
            tail = ""
        for line in tail.splitlines():
            ctx.log(line)
        if return_code:
            raise RuntimeError(
                f"child flow exited with status {return_code}; see its log")
        if not output_file.is_file():
            raise RuntimeError("child flow finished without a captured output")
        try:
            with output_file.open("rb") as stream:
                value = pickle.load(stream)
        except Exception as exc:
            raise RuntimeError(f"couldn't read child flow output: {exc}") from exc
    return {"value": value}

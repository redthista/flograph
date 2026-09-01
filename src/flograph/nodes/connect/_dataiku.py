"""Shared plumbing for the Dataiku connector nodes.

Not a node (leading underscore — the registry skips it). Imported inside the
`run()` of `dataiku_source` / `dataiku_upload` / `dataiku_action` so one
connection-and-auth implementation covers all three, exactly as `ai/_llm.py`
serves the AI nodes.

Everything here talks to a remote DSS instance over the public REST API via
the external `dataikuapi` client (`pip install dataiku-api-client`). Nothing
in this module imports `dataikuapi` at module load — the callers import it
inside their own `run()` and hand the pieces in, or call `connect()` which
imports it lazily.
"""
from __future__ import annotations

# The four params every Dataiku node shares. Each script splices this in:
#     PARAMS = CONN_PARAMS + [ ... node-specific ... ]
# Kept as a plain list (not built from a helper) so a script can also just
# paste the dicts inline if it prefers — the registry execs scripts as text.
CONN_PARAMS = [
    {"name": "host", "type": "string", "label": "DSS URL",
     "default": "", "placeholder": "https://dss-host:11200"},
    {"name": "api_key", "type": "password", "label": "API key",
     "default": "",
     "placeholder": "blank = $DKU_API_KEY / ${env:DKU_API_KEY}"},
    {"name": "project_key", "type": "string", "label": "Project key",
     "default": "", "placeholder": "e.g. WORKFORCE_LOADING"},
    {"name": "insecure_tls", "type": "bool", "label": "Disable TLS verification",
     "default": False},
]


def resolve_key(raw: str) -> str:
    """The API key: the node's own field, else `$DKU_API_KEY`.

    A leftover `${...}` token means the engine could not resolve a `.env`
    reference — treat it as blank so the env-var fallback still gets a turn.
    """
    import os

    key = (raw or "").strip()
    if key and not key.startswith("${"):
        return key
    key = os.environ.get("DKU_API_KEY", "").strip()
    if key:
        return key
    raise ValueError(
        "no API key — type one into 'API key', set DKU_API_KEY in the "
        "environment, or add it to the project's .env file")


def connect(p, *, need_project=True):
    """Build a DSSClient (and, by default, resolve the project) from params.

    Returns `(client, project_or_None)`. Raises `ValueError` with an
    actionable message for every missing piece.
    """
    import dataikuapi

    host = (p.get("host") or "").strip().rstrip("/")
    if not host:
        raise ValueError("DSS URL is required — set 'DSS URL'")
    api_key = resolve_key(p.get("api_key"))
    insecure = bool(p.get("insecure_tls"))
    if insecure:
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    client = dataikuapi.DSSClient(host, api_key, no_check_certificate=insecure)

    project = None
    if need_project:
        project_key = (p.get("project_key") or "").strip()
        if not project_key:
            raise ValueError("project key is required — set 'Project key'")
        project = client.get_project(project_key)
    return client, project


def frame_from_dataset(dataset, ctx, *, columns=None, limit=0):
    """Pull a DSS dataset into a DataFrame via `iter_rows()`.

    `columns` (list or None) is passed to the server; `limit` (0 = all) is
    applied client-side — the public `iter_rows()` has no row cap of its own.
    """
    import pandas as pd

    schema = [c["name"] for c in dataset.get_schema()["columns"]]
    want = list(columns) if columns else None
    ctx.log(f"{len(want or schema)} columns, reading rows...")

    rows = []
    for i, row in enumerate(dataset.iter_rows(columns=want)):
        rows.append(list(row))
        if limit and len(rows) >= limit:
            break
        if i and i % 5000 == 0:
            ctx.check_cancelled()
            ctx.progress(min(0.95, i / (limit or 100_000)))
            ctx.log(f"  {i} rows...")

    return pd.DataFrame(data=rows, columns=(want or schema))


def serialise(df, fmt: str):
    """DataFrame -> (bytes, extension) in one of csv / parquet / json / xlsx."""
    import io

    import pandas as pd

    buf = io.BytesIO()
    if fmt == "csv":
        df.to_csv(buf, index=False)
        return buf.getvalue(), "csv"
    if fmt == "json":
        df.to_json(buf, orient="records", date_format="iso")
        return buf.getvalue(), "json"
    if fmt == "parquet":
        df.to_parquet(buf, index=False)  # needs pyarrow / fastparquet
        return buf.getvalue(), "parquet"
    if fmt == "xlsx":
        with pd.ExcelWriter(buf, engine="openpyxl") as xl:
            df.to_excel(xl, index=False)
        return buf.getvalue(), "xlsx"
    raise ValueError(f"unknown format {fmt!r}")


def report_frame(**cols):
    """A one-row DataFrame from keyword columns — the Action node's `report`."""
    import pandas as pd

    return pd.DataFrame([cols])

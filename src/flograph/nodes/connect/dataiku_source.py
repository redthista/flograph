"""Dataiku Source

Pull data out of a remote Dataiku DSS instance over the public API and emit it
as a dataframe. No inputs — it's a data origin. One node, four jobs; pick with
**Operation** and the panel shows only what that job needs:

  • **import dataset** — read a DSS dataset's rows (optionally a column subset
    and a row cap)
  • **SQL query** — run SQL against a DSS connection (or a dataset's own
    connection) and stream the result back
  • **list objects** — a tidy table of the project's datasets / managed
    folders / scenarios / recipes / jobs, for a "DSS health" dashboard or to
    drive downstream nodes by name
  • **download file** — read one file out of a managed folder and parse it as
    text / CSV / JSON / Parquet

Uses the external `dataikuapi` client (`pip install dataiku-api-client`).
Leave **API key** blank to fall back to `$DKU_API_KEY` so the secret never
lands in the saved graph; `${env:NAME}` works too.
"""
NODE = {
    "label": "Dataiku Source",
    "category": "Connect",
    "version": "1.0",
    "inputs": [],
    "outputs": [("table", "dataframe")],
}
PARAMS = [
    {"name": "host", "type": "string", "label": "DSS URL",
     "default": "", "placeholder": "https://dss-host:11200"},
    {"name": "api_key", "type": "password", "label": "API key",
     "default": "", "placeholder": "blank = $DKU_API_KEY / ${env:DKU_API_KEY}"},
    {"name": "project_key", "type": "string", "label": "Project key",
     "default": "", "placeholder": "e.g. WORKFORCE_LOADING"},
    {"name": "operation", "type": "choice", "label": "Operation",
     "options": ["import dataset", "SQL query", "list objects",
                 "download file"],
     "default": "import dataset"},

    # import dataset
    {"name": "dataset_name", "type": "string", "label": "Dataset name",
     "default": "",
     "visible_when": {"operation": ["import dataset"]}},
    {"name": "columns", "type": "string", "label": "Columns (comma-sep, blank = all)",
     "default": "",
     "visible_when": {"operation": ["import dataset"]}},
    {"name": "limit", "type": "int", "label": "Row limit (0 = all)",
     "default": 10000, "min": 0, "max": 100_000_000,
     "visible_when": {"operation": ["import dataset"]}},

    # SQL query
    {"name": "connection", "type": "string", "label": "Connection name",
     "default": "", "placeholder": "blank = use the dataset's connection",
     "visible_when": {"operation": ["SQL query"]}},
    {"name": "dataset_full_name", "type": "string", "label": "…or dataset (PROJECT.name)",
     "default": "",
     "visible_when": {"operation": ["SQL query"]}},
    {"name": "query", "type": "text", "label": "SQL",
     "default": "", "placeholder": "SELECT * FROM \"public\".\"orders\" LIMIT 1000",
     "visible_when": {"operation": ["SQL query"]}},

    # list objects
    {"name": "what", "type": "choice", "label": "List",
     "options": ["datasets", "managed folders", "scenarios", "recipes",
                 "jobs"],
     "default": "datasets",
     "visible_when": {"operation": ["list objects"]}},

    # download file
    {"name": "folder_id", "type": "string", "label": "Managed folder id",
     "default": "",
     "visible_when": {"operation": ["download file"]}},
    {"name": "path", "type": "string", "label": "File path in folder",
     "default": "", "placeholder": "/incoming/data.csv",
     "visible_when": {"operation": ["download file"]}},
    {"name": "parse", "type": "choice", "label": "Parse as",
     "options": ["text", "csv", "json", "parquet"], "default": "csv",
     "visible_when": {"operation": ["download file"]}},

    {"name": "insecure_tls", "type": "bool", "label": "Disable TLS verification",
     "default": False},
]


def run(ctx):
    import io

    import pandas as pd

    from flograph.nodes.connect import _dataiku

    p = ctx.params
    op = p.get("operation", "import dataset")

    # SQL query is the only op that can work without a project key.
    client, project = _dataiku.connect(p, need_project=(op != "SQL query"))

    if op == "import dataset":
        name = (p.get("dataset_name") or "").strip()
        if not name:
            raise ValueError("no dataset — set 'Dataset name'")
        cols = [c.strip() for c in (p.get("columns") or "").split(",")
                if c.strip()] or None
        ctx.log(f"reading dataset {name}")
        df = _dataiku.frame_from_dataset(
            project.get_dataset(name), ctx,
            columns=cols, limit=int(p.get("limit", 0) or 0))
        ctx.log(f"loaded {len(df)} rows x {len(df.columns)} cols")
        return df

    if op == "SQL query":
        sql = (p.get("query") or "").strip()
        if not sql:
            raise ValueError("no SQL — set 'SQL'")
        conn = (p.get("connection") or "").strip() or None
        dsname = (p.get("dataset_full_name") or "").strip() or None
        if not conn and not dsname:
            raise ValueError("set either 'Connection name' or 'dataset "
                             "(PROJECT.name)' so DSS knows which database to hit")
        pk = (p.get("project_key") or "").strip() or None
        ctx.log("running SQL query on DSS")
        q = client.sql_query(sql, connection=conn, dataset_full_name=dsname,
                             project_key=pk)
        names = [c["name"] for c in q.get_schema()]
        rows = [list(r) for r in q.iter_rows()]
        q.verify()
        df = pd.DataFrame(data=rows, columns=names)
        ctx.log(f"query returned {len(df)} rows x {len(df.columns)} cols")
        return df

    if op == "list objects":
        what = p.get("what", "datasets")
        ctx.log(f"listing {what} in {p.get('project_key')}")
        if what == "datasets":
            items = project.list_datasets()
            recs = [{"name": d.get("name"), "type": d.get("type"),
                     "tags": ", ".join(d.get("tags") or [])} for d in items]
        elif what == "managed folders":
            items = project.list_managed_folders()
            recs = [{"id": d.get("id"), "name": d.get("name"),
                     "type": d.get("type")} for d in items]
        elif what == "scenarios":
            items = project.list_scenarios()
            recs = [{"id": d.get("id"), "name": d.get("name"),
                     "type": d.get("type"),
                     "active": d.get("active")} for d in items]
        elif what == "recipes":
            items = project.list_recipes()
            recs = [{"name": d.get("name"), "type": d.get("type")}
                    for d in items]
        else:  # jobs
            items = project.list_jobs()
            recs = [{"id": (d.get("def") or {}).get("id"),
                     "state": d.get("state"),
                     "initiator": (d.get("def") or {}).get("initiator")}
                    for d in items]
        df = pd.DataFrame(recs)
        ctx.log(f"{len(df)} {what}")
        return df

    if op == "download file":
        fid = (p.get("folder_id") or "").strip()
        path = (p.get("path") or "").strip()
        if not fid or not path:
            raise ValueError("set both 'Managed folder id' and 'File path in "
                             "folder'")
        ctx.log(f"downloading {path} from folder {fid}")
        with project.get_managed_folder(fid).get_file(path) as resp:
            data = resp.raw.read() if hasattr(resp, "raw") else resp.content
        parse = p.get("parse", "csv")
        bio = io.BytesIO(data)
        if parse == "csv":
            df = pd.read_csv(bio)
        elif parse == "json":
            df = pd.read_json(bio)
        elif parse == "parquet":
            df = pd.read_parquet(bio)
        else:  # text — one row per line
            text = data.decode("utf-8", "replace")
            df = pd.DataFrame({"line": text.splitlines()})
        ctx.log(f"parsed {len(df)} rows x {len(df.columns)} cols")
        return df

    raise ValueError(f"unknown operation {op!r}")

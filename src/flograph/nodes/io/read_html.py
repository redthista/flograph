"""Read HTML Tables

Scrape every `<table>` off a web page (or a local `.html` file, or HTML piped
in on the `html` port) and hand back one of them as a DataFrame. The Wikipedia
list, the docs page with the pricing grid, the internal report that only
exists as a page — a table in one node.

**Match** keeps only tables containing that text (a plain string or a regex).
**Table** picks which of the surviving tables you want (0 = the first).
**Attributes** narrows by tag attribute — `class = wikitable`. **Header row**
says which row holds the column names.

`count` reports how many tables matched, so you can wire a check on it. Needs
`lxml` (or `beautifulsoup4` + `html5lib`).
"""
NODE = {
    "label": "Read HTML Tables",
    "category": "IO",
    "version": "1.0",
    "inputs": [("html", "any", {"optional": True})],
    "outputs": [("table", "dataframe"), ("count", "number")],
}
PARAMS = [
    {"name": "url", "type": "string", "label": "URL or file",
     "default": "", "placeholder": "https://en.wikipedia.org/wiki/... "},
    {"name": "match", "type": "string", "label": "Match",
     "default": "", "placeholder": "text a wanted table contains"},
    {"name": "table_index", "type": "int", "label": "Table",
     "default": 0, "min": 0, "max": 1000},
    {"name": "attrs", "type": "string", "label": "Attributes",
     "default": "", "placeholder": "class = wikitable"},
    {"name": "header_row", "type": "int", "label": "Header row",
     "default": 0, "min": -1, "max": 50},
    {"name": "flatten_columns", "type": "bool", "label": "Flatten column names",
     "default": True},
    {"name": "drop_na_rows", "type": "bool", "label": "Drop all-empty rows",
     "default": True},
]


def run(ctx, html=None):
    import io as _io

    import pandas as pd

    p = ctx.params
    url = (p.get("url") or "").strip()
    if html is None and not url:
        raise ValueError("set 'URL or file', or wire HTML into the 'html' port")

    kwargs = {}
    if p.get("match"):
        kwargs["match"] = p["match"]
    if p.get("attrs"):
        raw = p["attrs"]
        key, _, val = raw.partition("=")
        if not val:
            raise ValueError("'Attributes' wants 'name = value', e.g. "
                             "'class = wikitable'")
        kwargs["attrs"] = {key.strip(): val.strip()}
    header = int(p.get("header_row", 0))
    kwargs["header"] = None if header < 0 else header

    source = html if html is not None else url
    if isinstance(source, str) and "<" in source and ">" in source:
        source = _io.StringIO(source)

    try:
        tables = pd.read_html(source, **kwargs)
    except ValueError as exc:
        raise ValueError(f"no tables found — {exc}") from None

    if not tables:
        raise ValueError("no tables matched")
    idx = int(p.get("table_index", 0))
    if idx >= len(tables):
        raise ValueError(f"asked for table {idx} but only {len(tables)} "
                         f"matched (0–{len(tables) - 1})")

    df = tables[idx]
    if p.get("flatten_columns", True) and isinstance(df.columns, pd.MultiIndex):
        df.columns = [
            " ".join(str(x) for x in tup if str(x) and "Unnamed" not in str(x))
            or f"col_{i}"
            for i, tup in enumerate(df.columns)]
    if p.get("drop_na_rows", True):
        df = df.dropna(how="all").reset_index(drop=True)

    ctx.log(f"{len(tables)} table(s) matched, returning #{idx} "
            f"({len(df)} rows x {len(df.columns)} cols)")
    return {"table": df, "count": int(len(tables))}

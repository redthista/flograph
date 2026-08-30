"""REST Paginate

Pull every page from a paginated JSON API and stack the records into one
DataFrame. Handles the four schemes APIs actually use:

    page        — ?page=1, 2, 3 … until a page comes back empty
    offset      — ?offset=0, 100, 200 … stepping by the page size
    cursor      — read the next token from a field in the body and send it back
    link_header — follow the RFC 5988 `Link: <…>; rel="next"` header

Set **Records path** to where the array lives in each response
(`data.items`); blank means the body is the array. **Page size**, the param
names, and the cursor field are all configurable. Stops at **Max pages** or
**Max records** so a runaway API can't fill memory. Bearer token via
`${env:API_TOKEN}`. Needs the `httpx` package.
"""
NODE = {
    "label": "REST Paginate",
    "category": "Connect",
    "version": "1.0",
    "inputs": [],
    "outputs": [("table", "dataframe"), ("pages", "number")],
}
PARAMS = [
    {"name": "url", "type": "string", "label": "URL", "default": "",
     "placeholder": "https://api.example.com/v1/orders"},
    {"name": "strategy", "type": "choice", "label": "Pagination",
     "options": ["page", "offset", "cursor", "link_header"], "default": "page"},
    {"name": "records_path", "type": "string", "label": "Records path",
     "default": "", "placeholder": "data.items  (blank = body is the array)"},
    {"name": "headers", "type": "text", "label": "Headers", "default": "",
     "placeholder": "Accept: application/json"},
    {"name": "bearer_token", "type": "password", "label": "Bearer token",
     "default": "", "placeholder": "${env:API_TOKEN}"},
    {"name": "query_params", "type": "text", "label": "Query params",
     "default": "", "placeholder": "status = open"},
    {"name": "page_param", "type": "string", "label": "Page / offset param",
     "default": "page", "visible_when": {"strategy": ["page", "offset"]}},
    {"name": "start", "type": "int", "label": "Start at", "default": 1,
     "min": 0, "max": 1_000_000, "visible_when": {"strategy": ["page", "offset"]}},
    {"name": "size_param", "type": "string", "label": "Page-size param",
     "default": "per_page",
     "visible_when": {"strategy": ["page", "offset", "cursor"]}},
    {"name": "page_size", "type": "int", "label": "Page size", "default": 100,
     "min": 1, "max": 10000},
    {"name": "cursor_path", "type": "string", "label": "Next-cursor path",
     "default": "next_cursor", "visible_when": {"strategy": "cursor"}},
    {"name": "cursor_param", "type": "string", "label": "Cursor param",
     "default": "cursor", "visible_when": {"strategy": "cursor"}},
    {"name": "max_pages", "type": "int", "label": "Max pages", "default": 100,
     "min": 1, "max": 100000},
    {"name": "max_records", "type": "int", "label": "Max records (0 = no cap)",
     "default": 0, "min": 0, "max": 100_000_000},
    {"name": "throttle_ms", "type": "int", "label": "Delay between pages (ms)",
     "default": 0, "min": 0, "max": 60000},
    {"name": "timeout", "type": "float", "label": "Timeout (s)", "default": 30.0,
     "min": 0.1, "max": 600.0},
]


def _kv(raw, sep):
    out = {}
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for ch in sep:
            if ch in line:
                k, _, v = line.partition(ch)
                out[k.strip()] = v.strip()
                break
    return out


def _dig(obj, path):
    if not path:
        return obj
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def run(ctx):
    import time

    import httpx
    import pandas as pd

    p = ctx.params
    url = (p.get("url") or "").strip()
    if not url:
        raise ValueError("no URL — set 'URL'")
    strategy = p.get("strategy", "page")
    rec_path = (p.get("records_path") or "").strip()
    size = int(p.get("page_size", 100))
    max_pages = int(p.get("max_pages", 100))
    max_records = int(p.get("max_records", 0) or 0)
    throttle = int(p.get("throttle_ms", 0) or 0) / 1000.0

    headers = _kv(p.get("headers"), ":")
    token = (p.get("bearer_token") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    base_params = _kv(p.get("query_params"), "=:")

    frames = []
    total = 0
    pages = 0
    next_url = url
    cursor = None
    counter = int(p.get("start", 1))

    with httpx.Client(timeout=float(p.get("timeout", 30.0)),
                      follow_redirects=True, headers=headers) as client:
        while pages < max_pages:
            ctx.check_cancelled()
            params = dict(base_params)
            if strategy in ("page", "offset"):
                params[p.get("page_param", "page")] = counter
                params[p.get("size_param", "per_page")] = size
            elif strategy == "cursor":
                params[p.get("size_param", "per_page")] = size
                if cursor:
                    params[p.get("cursor_param", "cursor")] = cursor
            # link_header: after page 1, next_url already carries its own query

            resp = client.get(next_url, params=params if next_url == url or
                              strategy != "link_header" else None)
            if resp.is_error:
                snippet = resp.text[:300].replace("\n", " ")
                raise ValueError(f"page {pages + 1}: {resp.status_code} {snippet}")
            body = resp.json()
            records = _dig(body, rec_path)
            if records is None and not rec_path and isinstance(body, list):
                records = body
            if not isinstance(records, list):
                raise ValueError(
                    f"page {pages + 1}: no list of records at "
                    f"{rec_path or '(body root)'} — check 'Records path'")

            pages += 1
            if records:
                frames.append(pd.json_normalize(records))
                total += len(records)
            ctx.log(f"page {pages}: {len(records)} records ({total} total)")
            ctx.progress(min(pages / max_pages, 0.99))

            if not records:
                break
            if max_records and total >= max_records:
                break

            if strategy == "page":
                counter += 1
            elif strategy == "offset":
                counter += size
            elif strategy == "cursor":
                cursor = _dig(body, p.get("cursor_path", "next_cursor"))
                if not cursor:
                    break
            elif strategy == "link_header":
                link = resp.links.get("next", {}).get("url")
                if not link:
                    break
                next_url = link
            if throttle:
                time.sleep(throttle)

    ctx.progress(1.0)
    table = (pd.concat(frames, ignore_index=True) if frames
             else pd.DataFrame())
    if max_records and len(table) > max_records:
        table = table.head(max_records).copy()
    ctx.log(f"done — {len(table)} records over {pages} page(s)")
    return {"table": table, "pages": int(pages)}

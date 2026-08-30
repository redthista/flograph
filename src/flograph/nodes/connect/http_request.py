"""HTTP Request

Call a REST or JSON HTTP API and bring the response into the flow. One
request; for a paginated endpoint use **REST Paginate**.

Outputs: **json** (parsed body, or None if it isn't JSON), **text** (the raw
body), **status** (the code), and **table** — the response shaped into a
DataFrame when it's a list of objects, or the list found at **JSON path**
(`data.items`) inside the body.

**Auth** covers the common cases without a plugin: a bearer token, HTTP
basic, or a custom header (`X-API-Key`). Put secrets in a `.env` file and
reference them — `${env:API_TOKEN}` — so nothing sensitive is saved in the
project. Failed requests retry with exponential backoff up to **Retries**
times; a 4xx/5xx that survives that raises with the status and the first of
the body. Needs the `httpx` package.
"""
NODE = {
    "label": "HTTP Request",
    "category": "Connect",
    "version": "1.0",
    "inputs": [
        ("body", "any", {"optional": True}),
        ("query", "any", {"optional": True}),
    ],
    "outputs": [
        ("json", "any"),
        ("text", "string"),
        ("status", "number"),
        ("table", "dataframe"),
    ],
}
PARAMS = [
    {"name": "method", "type": "choice", "label": "Method",
     "options": ["GET", "POST", "PUT", "PATCH", "DELETE"], "default": "GET"},
    {"name": "url", "type": "string", "label": "URL",
     "default": "", "placeholder": "https://api.example.com/v1/orders"},
    {"name": "query_params", "type": "text", "label": "Query params",
     "default": "", "placeholder": "limit = 100\nsince = 2026-01-01"},
    {"name": "headers", "type": "text", "label": "Headers",
     "default": "", "placeholder": "Accept: application/json"},
    {"name": "auth", "type": "choice", "label": "Auth",
     "options": ["none", "bearer", "basic", "header"], "default": "none"},
    {"name": "auth_token", "type": "password", "label": "Bearer token",
     "default": "", "placeholder": "${env:API_TOKEN}",
     "visible_when": {"auth": "bearer"}},
    {"name": "auth_user", "type": "string", "label": "Username",
     "default": "", "visible_when": {"auth": "basic"}},
    {"name": "auth_pass", "type": "password", "label": "Password",
     "default": "", "placeholder": "${env:API_PASSWORD}",
     "visible_when": {"auth": "basic"}},
    {"name": "auth_header_name", "type": "string", "label": "Header name",
     "default": "X-API-Key", "visible_when": {"auth": "header"}},
    {"name": "auth_header_value", "type": "password", "label": "Header value",
     "default": "", "placeholder": "${env:API_KEY}",
     "visible_when": {"auth": "header"}},
    {"name": "body_mode", "type": "choice", "label": "Body",
     "options": ["none", "json", "form", "raw"], "default": "none"},
    {"name": "body", "type": "text", "label": "Body content",
     "default": "", "placeholder": '{"name": "widget"}  — or key=value lines for form',
     "visible_when": {"body_mode": ["json", "form", "raw"]}},
    {"name": "json_path", "type": "string", "label": "JSON path (for table)",
     "default": "", "placeholder": "data.items"},
    {"name": "timeout", "type": "float", "label": "Timeout (s)",
     "default": 30.0, "min": 0.1, "max": 600.0},
    {"name": "retries", "type": "int", "label": "Retries",
     "default": 2, "min": 0, "max": 10},
]


def _kv_lines(raw, sep_chars="=:"):
    out = {}
    for lineno, line in enumerate((raw or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for ch in sep_chars:
            if ch in line:
                k, _, v = line.partition(ch)
                out[k.strip()] = v.strip()
                break
        else:
            raise ValueError(f"line {lineno}: expected 'key = value', got {line!r}")
    return out


def _dig(obj, path):
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def run(ctx, body=None, query=None):
    import time

    import httpx
    import pandas as pd

    p = ctx.params
    url = (p.get("url") or "").strip()
    if not url:
        raise ValueError("no URL — set 'URL'")
    method = p.get("method", "GET")

    headers = _kv_lines(p.get("headers"), ":")
    params = _kv_lines(p.get("query_params"), "=:")
    if isinstance(query, dict):
        params.update({str(k): str(v) for k, v in query.items()})

    auth = p.get("auth", "none")
    httpx_auth = None
    if auth == "bearer":
        headers["Authorization"] = f"Bearer {p.get('auth_token', '').strip()}"
    elif auth == "basic":
        httpx_auth = (p.get("auth_user", ""), p.get("auth_pass", ""))
    elif auth == "header":
        name = (p.get("auth_header_name") or "X-API-Key").strip()
        headers[name] = p.get("auth_header_value", "").strip()

    req = {"headers": headers, "params": params}
    mode = p.get("body_mode", "none")
    if body is not None and mode == "none":
        mode = "json"
    if mode == "json":
        import json as _json
        payload = body
        if payload is None:
            text = (p.get("body") or "").strip()
            payload = _json.loads(text) if text else {}
        elif isinstance(payload, pd.DataFrame):
            payload = payload.to_dict("records")
        req["json"] = payload
    elif mode == "form":
        req["data"] = (body if isinstance(body, dict)
                       else _kv_lines(p.get("body"), "=:"))
    elif mode == "raw":
        req["content"] = (p.get("body") or "").encode()

    timeout = float(p.get("timeout", 30.0))
    retries = int(p.get("retries", 2))

    last_exc = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True,
                              auth=httpx_auth) as client:
                resp = client.request(method, url, **req)
            if resp.status_code < 500:
                break
            last_exc = httpx.HTTPStatusError(
                f"server returned {resp.status_code}", request=resp.request,
                response=resp)
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
        if attempt < retries:
            wait = 2 ** attempt
            ctx.log(f"attempt {attempt + 1} failed, retrying in {wait}s")
            time.sleep(wait)
    else:
        raise last_exc or RuntimeError("request failed")

    text = resp.text
    try:
        parsed = resp.json()
    except ValueError:
        parsed = None

    if resp.is_error:
        snippet = text[:300].replace("\n", " ")
        raise ValueError(f"{method} {url} → {resp.status_code}: {snippet}")

    records = None
    path = (p.get("json_path") or "").strip()
    if path:
        records = _dig(parsed, path)
    elif isinstance(parsed, list):
        records = parsed
    elif isinstance(parsed, dict):
        for v in parsed.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                records = v
                break

    if isinstance(records, list):
        table = pd.json_normalize(records)
    else:
        table = pd.DataFrame()

    ctx.log(f"{method} {url} → {resp.status_code}, {len(table)} rows")
    return {"json": parsed, "text": text, "status": int(resp.status_code),
            "table": table}

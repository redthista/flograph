"""Headless tests for the connector / AI / data-quality / weird-and-wonderful
node batch. Happy path plus an error path for each, per the node contract."""
import pandas as pd
import pytest

from flograph.core import compile_run
from tests.conftest import FakeContext


def run_node(registry, type_id, params=None, **inputs):
    spec = registry.get(type_id)
    defaults = spec.default_params()
    defaults.update(params or {})
    run = compile_run(spec.source, f"test-{type_id}")
    return run(FakeContext(params=defaults), **inputs)


# --------------------------------------------------------------------------
# Transform & data quality
# --------------------------------------------------------------------------
class TestDataQualityGate:
    def _t(self):
        return pd.DataFrame({
            "order_id": [1, 2, 3, 4],
            "status": ["open", "closed", "weird", "open"],
            "amount": [10.0, 20.0, -5.0, 30.0],
        })

    def test_all_pass(self, registry):
        out = run_node(registry, "flograph.transform.data_quality_gate", {
            "rules": "order_id not_null\norder_id unique\namount >= -100\n@rows >= 1",
        }, table=self._t())
        assert out["passed"] is True
        assert list(out["report"]["passed"]) == [True, True, True, True]
        assert len(out["clean"]) == 4

    def test_violations_reported_and_cleaned(self, registry):
        out = run_node(registry, "flograph.transform.data_quality_gate", {
            "rules": "status in open | closed\namount >= 0",
        }, table=self._t())
        assert out["passed"] is False
        assert set(out["report"]["violations"]) == {1}
        # row 3 breaks both row-level rules -> dropped from clean
        assert list(out["clean"]["order_id"]) == [1, 2, 4]

    def test_raise_on_fail(self, registry):
        with pytest.raises(ValueError, match="data quality gate failed"):
            run_node(registry, "flograph.transform.data_quality_gate", {
                "rules": "amount >= 0", "on_fail": "raise",
            }, table=self._t())

    def test_unknown_column(self, registry):
        with pytest.raises(ValueError, match="not in the table"):
            run_node(registry, "flograph.transform.data_quality_gate",
                     {"rules": "nope not_null"}, table=self._t())

    def test_no_rules(self, registry):
        with pytest.raises(ValueError, match="no rules"):
            run_node(registry, "flograph.transform.data_quality_gate",
                     {"rules": "   "}, table=self._t())


class TestDiffTables:
    def _old(self):
        return pd.DataFrame({"id": [1, 2, 3], "price": [10, 20, 30],
                             "name": ["a", "b", "c"]})

    def _new(self):
        return pd.DataFrame({"id": [2, 3, 4], "price": [20, 35, 40],
                             "name": ["b", "c", "d"]})

    def test_split(self, registry):
        out = run_node(registry, "flograph.transform.diff_tables",
                       {"keys": "id"}, old=self._old(), new=self._new())
        assert list(out["added"]["id"]) == [4]
        assert list(out["removed"]["id"]) == [1]
        assert list(out["changed"]["id"]) == [3]
        assert "price__old" in out["changed"].columns
        assert list(out["unchanged"]["id"]) == [2]
        assert out["summary"].iloc[0]["changed"] == 1

    def test_compare_subset(self, registry):
        out = run_node(registry, "flograph.transform.diff_tables",
                       {"keys": "id", "compare": "name"},
                       old=self._old(), new=self._new())
        # only 'name' compared -> id 3 unchanged now
        assert list(out["changed"]["id"]) == []

    def test_missing_key(self, registry):
        with pytest.raises(ValueError, match="no key columns"):
            run_node(registry, "flograph.transform.diff_tables", {},
                     old=self._old(), new=self._new())

    def test_non_unique_key(self, registry):
        dup = pd.DataFrame({"id": [1, 1], "price": [1, 2]})
        with pytest.raises(ValueError, match="not unique"):
            run_node(registry, "flograph.transform.diff_tables",
                     {"keys": "id"}, old=dup, new=dup)


class TestWindowFunction:
    def _t(self):
        return pd.DataFrame({
            "team": ["a", "a", "a", "b", "b"],
            "day": [1, 2, 3, 1, 2],
            "sales": [10, 30, 20, 5, 15],
        })

    def test_row_number_partitioned(self, registry):
        out = run_node(registry, "flograph.transform.window_function", {
            "function": "row_number", "partition_by": "team", "order_by": "day",
        }, table=self._t())
        assert list(out["row_number"]) == [1, 2, 3, 1, 2]

    def test_lag(self, registry):
        out = run_node(registry, "flograph.transform.window_function", {
            "function": "lag", "partition_by": "team", "order_by": "day",
            "value_column": "sales", "param_n": 1, "output_column": "prev",
        }, table=self._t())
        assert pd.isna(out["prev"].iloc[0])
        assert out["prev"].iloc[1] == 10

    def test_cumsum_keeps_input_order(self, registry):
        out = run_node(registry, "flograph.transform.window_function", {
            "function": "cumsum", "partition_by": "team", "order_by": "day",
            "value_column": "sales",
        }, table=self._t())
        assert list(out["team"]) == ["a", "a", "a", "b", "b"]
        assert list(out["cumsum"]) == [10, 40, 60, 5, 20]

    def test_pct_of_partition(self, registry):
        out = run_node(registry, "flograph.transform.window_function", {
            "function": "pct_of_partition", "partition_by": "team",
            "value_column": "sales",
        }, table=self._t())
        assert round(out["pct_of_partition"].iloc[0], 3) == round(10 / 60, 3)

    def test_missing_value_column(self, registry):
        with pytest.raises(ValueError, match="needs a value column"):
            run_node(registry, "flograph.transform.window_function",
                     {"function": "cumsum"}, table=self._t())

    def test_missing_order(self, registry):
        with pytest.raises(ValueError, match="needs an order"):
            run_node(registry, "flograph.transform.window_function",
                     {"function": "row_number"}, table=self._t())


class TestPiiScan:
    def _t(self):
        return pd.DataFrame({
            "note": [
                "call me at 555-123-4567 or a@b.com",
                "card 4111 1111 1111 1111 on file",
                "nothing here, order 999888777",
            ],
            "n": [1, 2, 3],
        })

    def test_flag(self, registry):
        out = run_node(registry, "flograph.transform.pii_scan",
                       {"action": "flag only"}, table=self._t())
        kinds = set(out["findings"]["kind"])
        assert {"email", "phone", "credit_card"} <= kinds
        # the plain order number is not a false-positive card hit
        assert out["table"].equals(self._t())

    def test_redact(self, registry):
        out = run_node(registry, "flograph.transform.pii_scan",
                       {"action": "redact", "kinds": "email"}, table=self._t())
        assert "a@b.com" not in out["table"]["note"].iloc[0]
        assert "REDACTED:email" in out["table"]["note"].iloc[0]
        # phone left alone since only email was requested
        assert "555-123-4567" in out["table"]["note"].iloc[0]

    def test_unknown_kind(self, registry):
        with pytest.raises(ValueError, match="unknown kind"):
            run_node(registry, "flograph.transform.pii_scan",
                     {"kinds": "passport"}, table=self._t())


class TestFuzzyJoin:
    def test_match(self, registry):
        pytest.importorskip("rapidfuzz")
        left = pd.DataFrame({"name": ["ACME Corp", "Globex Ltd", "Nobody Inc"]})
        right = pd.DataFrame({"company": ["acme corporation", "globex limited"],
                              "tier": ["gold", "silver"]})
        out = run_node(registry, "flograph.transform.fuzzy_join", {
            "left_on": "name", "right_on": "company", "threshold": 60,
        }, left=left, right=right)
        joined = out["joined"]
        assert joined.loc[joined["name"] == "ACME Corp", "tier"].iloc[0] == "gold"
        assert list(out["unmatched"]["name"]) == ["Nobody Inc"]

    def test_requires_columns(self, registry):
        pytest.importorskip("rapidfuzz")
        with pytest.raises(ValueError, match="Left column"):
            run_node(registry, "flograph.transform.fuzzy_join", {},
                     left=pd.DataFrame({"a": [1]}), right=pd.DataFrame({"b": [1]}))


# --------------------------------------------------------------------------
# Connectors
# --------------------------------------------------------------------------
class TestSqlQueryWrite:
    def _url(self, tmp_path):
        return f"sqlite:///{tmp_path / 'w.db'}"

    def test_write_then_query_round_trip(self, registry, tmp_path):
        pytest.importorskip("sqlalchemy")
        url = self._url(tmp_path)
        df = pd.DataFrame({"id": [1, 2, 3], "name": ["a", "b", "c"]})
        run_node(registry, "flograph.connect.sql_write",
                 {"url": url, "table": "people", "if_exists": "replace"},
                 table=df)
        out = run_node(registry, "flograph.connect.sql_query",
                       {"url": url, "mode": "table", "table": "people"})
        assert list(out["name"]) == ["a", "b", "c"]

    def test_query_mode(self, registry, tmp_path):
        pytest.importorskip("sqlalchemy")
        url = self._url(tmp_path)
        run_node(registry, "flograph.connect.sql_write",
                 {"url": url, "table": "t", "if_exists": "replace"},
                 table=pd.DataFrame({"x": [1, 2, 3, 4]}))
        out = run_node(registry, "flograph.connect.sql_query",
                       {"url": url, "query": "SELECT sum(x) AS s FROM t"})
        assert out["s"].iloc[0] == 10

    def test_upsert(self, registry, tmp_path):
        pytest.importorskip("sqlalchemy")
        url = self._url(tmp_path)
        run_node(registry, "flograph.connect.sql_write",
                 {"url": url, "table": "u", "if_exists": "replace"},
                 table=pd.DataFrame({"id": [1, 2], "v": [10, 20]}))
        run_node(registry, "flograph.connect.sql_write",
                 {"url": url, "table": "u", "if_exists": "upsert", "keys": "id"},
                 table=pd.DataFrame({"id": [2, 3], "v": [99, 30]}))
        out = run_node(registry, "flograph.connect.sql_query",
                       {"url": url, "mode": "table", "table": "u"})
        assert dict(zip(out["id"], out["v"])) == {1: 10, 2: 99, 3: 30}

    def test_no_url(self, registry):
        with pytest.raises(ValueError, match="no connection URL"):
            run_node(registry, "flograph.connect.sql_query", {"query": "SELECT 1"})


class TestDuckDbQuery:
    def test_join_two_frames(self, registry):
        pytest.importorskip("duckdb")
        a = pd.DataFrame({"id": [1, 2, 3], "region": ["n", "s", "n"]})
        b = pd.DataFrame({"id": [1, 2, 3], "amount": [10, 20, 30]})
        out = run_node(registry, "flograph.connect.duckdb_query", {
            "query": "SELECT a.region, sum(b.amount) AS spend "
                     "FROM a JOIN b USING (id) GROUP BY 1 ORDER BY 1",
        }, a=a, b=b)
        assert dict(zip(out["region"], out["spend"])) == {"n": 40, "s": 20}

    def test_reads_parquet_alias(self, registry, tmp_path):
        pytest.importorskip("duckdb")
        pytest.importorskip("pyarrow")
        path = tmp_path / "s.parquet"
        pd.DataFrame({"v": [1, 2, 3]}).to_parquet(path)
        out = run_node(registry, "flograph.connect.duckdb_query", {
            "query": "SELECT sum(v) AS s FROM sales",
            "files": f"sales = {path}",
        })
        assert out["s"].iloc[0] == 6

    def test_no_query(self, registry):
        pytest.importorskip("duckdb")
        with pytest.raises(ValueError, match="no SQL"):
            run_node(registry, "flograph.connect.duckdb_query", {"query": " "})


@pytest.fixture
def http_server():
    """A throwaway localhost JSON API for the HTTP node tests."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            from urllib.parse import parse_qs, urlparse
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/orders":
                self._send(200, [{"id": 1, "sku": "A"}, {"id": 2, "sku": "B"}])
            elif u.path == "/page":
                page = int(q.get("page", ["1"])[0])
                rows = [{"n": page * 10 + i} for i in range(2)] if page <= 3 else []
                self._send(200, {"data": {"items": rows}})
            elif u.path == "/secure":
                if self.headers.get("Authorization") == "Bearer sekret":
                    self._send(200, {"ok": True})
                else:
                    self._send(401, {"error": "nope"})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            self._send(201, {"echo": json.loads(raw or b"{}")})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


class TestHttpRequest:
    def test_get_to_table(self, registry, http_server):
        pytest.importorskip("httpx")
        out = run_node(registry, "flograph.connect.http_request",
                       {"url": f"{http_server}/orders"})
        assert out["status"] == 200
        assert list(out["table"]["sku"]) == ["A", "B"]
        assert out["json"] == [{"id": 1, "sku": "A"}, {"id": 2, "sku": "B"}]

    def test_post_json_body(self, registry, http_server):
        pytest.importorskip("httpx")
        out = run_node(registry, "flograph.connect.http_request", {
            "url": f"{http_server}/echo", "method": "POST",
            "body_mode": "json", "body": '{"hello": "world"}',
        })
        assert out["status"] == 201
        assert out["json"]["echo"] == {"hello": "world"}

    def test_bearer_auth_and_error(self, registry, http_server):
        pytest.importorskip("httpx")
        out = run_node(registry, "flograph.connect.http_request", {
            "url": f"{http_server}/secure", "auth": "bearer",
            "auth_token": "sekret",
        })
        assert out["json"] == {"ok": True}
        with pytest.raises(ValueError, match="401"):
            run_node(registry, "flograph.connect.http_request", {
                "url": f"{http_server}/secure", "auth": "bearer",
                "auth_token": "wrong", "retries": 0,
            })

    def test_no_url(self, registry):
        with pytest.raises(ValueError, match="no URL"):
            run_node(registry, "flograph.connect.http_request", {})


class TestRestPaginate:
    def test_page_strategy(self, registry, http_server):
        pytest.importorskip("httpx")
        out = run_node(registry, "flograph.connect.rest_paginate", {
            "url": f"{http_server}/page", "strategy": "page",
            "records_path": "data.items", "page_param": "page", "start": 1,
        })
        assert out["pages"] == 4  # 3 with data + 1 empty stop
        assert len(out["table"]) == 6
        assert list(out["table"]["n"])[:2] == [10, 11]

    def test_max_records_cap(self, registry, http_server):
        pytest.importorskip("httpx")
        out = run_node(registry, "flograph.connect.rest_paginate", {
            "url": f"{http_server}/page", "strategy": "page",
            "records_path": "data.items", "max_records": 3,
        })
        assert len(out["table"]) == 3

    def test_bad_records_path(self, registry, http_server):
        pytest.importorskip("httpx")
        with pytest.raises(ValueError, match="no list of records"):
            run_node(registry, "flograph.connect.rest_paginate", {
                "url": f"{http_server}/page", "records_path": "nope.here",
            })


# --------------------------------------------------------------------------
# AI / LLM
# --------------------------------------------------------------------------
def _source_ns(registry, type_id):
    ns = {}
    exec(compile(registry.get(type_id).source, type_id, "exec"), ns)
    return ns


@pytest.fixture
def llm_server():
    """A localhost server that answers both wire formats — Anthropic
    (`/v1/messages`) and OpenAI (`/v1/chat/completions`). `state["reply"]`
    maps the user message to the assistant text; `state["status"]` forces an
    error response."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    state = {"reply": lambda user: "ok", "status": None, "seen": []}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _json(self, code, payload):
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            req = json.loads(raw or b"{}")
            state["seen"].append({
                "path": self.path,
                "headers": {k.lower(): v for k, v in self.headers.items()},
                "body": req})
            if state["status"]:
                self._json(state["status"], {"error": {"message": "nope"}})
                return
            user = req["messages"][-1]["content"]
            text = state["reply"](user)
            if self.path.endswith("/messages"):
                self._json(200, {"content": [{"type": "text", "text": text}]})
            else:
                self._json(200, {"choices": [{"message": {"content": text}}]})

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()


class TestLlmEnrich:
    def _t(self):
        return pd.DataFrame({"text": ["alpha", "beta", "alpha"]})

    def test_dry_run_renders_prompt(self, registry):
        out = run_node(registry, "flograph.ai.llm_enrich", {
            "prompt": "Say hi to {text}", "dry_run": True,
        }, table=self._t())
        assert list(out["llm_output"]) == [
            "Say hi to alpha", "Say hi to beta", "Say hi to alpha"]

    def test_calls_model_and_dedupes(self, registry, llm_server):
        pytest.importorskip("httpx")
        llm_server["reply"] = lambda user: f"[{user}]"
        out = run_node(registry, "flograph.ai.llm_enrich", {
            "prompt": "x {text}", "api_key": "sk-test", "output_column": "y",
            "base_url": llm_server["url"],
        }, table=self._t())
        assert list(out["y"]) == ["[x alpha]", "[x beta]", "[x alpha]"]
        assert len(llm_server["seen"]) == 2  # 'alpha' sent once
        assert llm_server["seen"][0]["path"].endswith("/v1/messages")

    def test_openai_format(self, registry, llm_server):
        pytest.importorskip("httpx")
        llm_server["reply"] = lambda user: "SUMMARY"
        out = run_node(registry, "flograph.ai.llm_enrich", {
            "prompt": "x {text}", "provider": "openai", "model": "gpt-4o-mini",
            "base_url": llm_server["url"], "api_key": "sk-test",
        }, table=self._t())
        assert set(out["llm_output"]) == {"SUMMARY"}
        assert llm_server["seen"][0]["path"].endswith("/v1/chat/completions")
        assert llm_server["seen"][0]["headers"]["authorization"] == "Bearer sk-test"

    def test_api_error_surfaces(self, registry, llm_server):
        pytest.importorskip("httpx")
        llm_server["status"] = 429
        with pytest.raises(RuntimeError, match="429"):
            run_node(registry, "flograph.ai.llm_enrich", {
                "prompt": "x {text}", "base_url": llm_server["url"],
                "api_key": "k",
            }, table=self._t())

    def test_missing_column_in_template(self, registry):
        with pytest.raises(ValueError, match="not in the table"):
            run_node(registry, "flograph.ai.llm_enrich",
                     {"prompt": "{nope}", "dry_run": True}, table=self._t())

    def test_no_api_key_anthropic(self, registry, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(ValueError, match="no API key"):
            run_node(registry, "flograph.ai.llm_enrich",
                     {"prompt": "hi {text}"}, table=self._t())


class TestLlmClassify:
    def _t(self):
        return pd.DataFrame({"body": ["love it", "hate it", "love it"]})

    def test_classifies(self, registry, llm_server):
        pytest.importorskip("httpx")
        llm_server["reply"] = lambda user: (
            "positive" if "love" in user else "negative")
        out = run_node(registry, "flograph.ai.llm_classify", {
            "text_column": "body", "labels": "positive | negative",
            "api_key": "sk-test", "base_url": llm_server["url"],
        }, table=self._t())
        assert list(out["label"]) == ["positive", "negative", "positive"]

    def test_constrains_to_label_set(self, registry, llm_server):
        pytest.importorskip("httpx")
        llm_server["reply"] = lambda user: "I think it is quite POSITIVE overall"
        out = run_node(registry, "flograph.ai.llm_classify", {
            "text_column": "body", "labels": "positive | negative",
            "api_key": "sk-test", "base_url": llm_server["url"],
        }, table=self._t())
        assert set(out["label"]) == {"positive"}

    def test_needs_two_labels(self, registry):
        with pytest.raises(ValueError, match="at least two labels"):
            run_node(registry, "flograph.ai.llm_classify",
                     {"text_column": "body", "labels": "only", "dry_run": True},
                     table=self._t())

    def test_match_helper(self, registry):
        _match = _source_ns(registry, "flograph.ai.llm_classify")["_match"]
        assert _match("negative.", ["positive", "negative"], False, False) == "negative"
        assert _match("banana", ["positive", "negative"], False, True) == "other"


class TestLlmExtract:
    def _t(self):
        return pd.DataFrame({"blurb": ["ACME pays 50k", "no info"]})

    def test_extracts_fields(self, registry, llm_server):
        pytest.importorskip("httpx")
        llm_server["reply"] = lambda user: (
            '{"company": "ACME", "pay": 50000}' if "ACME" in user
            else '{"company": null, "pay": null}')
        out = run_node(registry, "flograph.ai.llm_extract", {
            "text_column": "blurb", "fields": "company: name\npay: salary",
            "api_key": "sk-test", "prefix": "x_", "base_url": llm_server["url"],
        }, table=self._t())
        assert out["x_company"].iloc[0] == "ACME" and pd.isna(out["x_company"].iloc[1])
        assert out["x_pay"].iloc[0] == 50000 and pd.isna(out["x_pay"].iloc[1])

    def test_endpoint_helper(self, registry):
        ns = _source_ns(registry, "flograph.ai.llm_enrich")
        # _llm is imported lazily inside run(); exercise it directly
        from flograph.nodes.ai import _llm
        assert _llm.endpoint("anthropic", "") == "https://api.anthropic.com/v1/messages"
        assert _llm.endpoint("openai", "") == "https://api.openai.com/v1/chat/completions"
        assert _llm.endpoint("openai", "http://localhost:11434/v1") == \
            "http://localhost:11434/v1/chat/completions"
        assert ns  # source compiled

    def test_parse_json_helper(self, registry):
        _pj = _source_ns(registry, "flograph.ai.llm_extract")["_parse_json"]
        assert _pj('```json\n{"a": 1}\n```') == {"a": 1}
        assert _pj('here you go: {"a": 2} thanks') == {"a": 2}
        with pytest.raises(ValueError, match="no JSON object"):
            _pj("sorry, cannot help")

    def test_bad_field_name(self, registry):
        with pytest.raises(ValueError, match="not a valid field name"):
            run_node(registry, "flograph.ai.llm_extract",
                     {"text_column": "blurb", "fields": "not a name: x",
                      "dry_run": True}, table=self._t())


# --------------------------------------------------------------------------
# Weird & wonderful
# --------------------------------------------------------------------------
class TestSvgTemplate:
    _SVG = ("<svg xmlns='http://www.w3.org/2000/svg'>"
            "<text>{{revenue:$,.0f}}</text><circle fill='{{status_color}}'/>"
            "<text>{{ghost}}</text></svg>")

    def test_binds_row_and_literal(self, registry):
        df = pd.DataFrame({"revenue": [1234567.0], "region": ["north"]})
        out = run_node(registry, "flograph.viz.svg_template", {
            "svg_source": self._SVG,
            "bindings": "status_color = #22c55e",
            "missing": "blank",
        }, data=df)
        assert "$1,234,567" in out["svg"]
        assert "fill='#22c55e'" in out["svg"]
        assert "{{ghost}}" not in out["svg"]  # blanked
        assert out["html"].startswith("<!doctype html>")

    def test_missing_token_error(self, registry):
        with pytest.raises(ValueError, match="unresolved token"):
            run_node(registry, "flograph.viz.svg_template",
                     {"svg_source": "<svg>{{nope}}</svg>", "missing": "error"})

    def test_no_svg(self, registry):
        with pytest.raises(ValueError, match="no SVG"):
            run_node(registry, "flograph.viz.svg_template", {})


class TestMermaid:
    def test_template_token_fill(self, registry):
        df = pd.DataFrame({"label": ["Ship it"]})
        out = run_node(registry, "flograph.viz.mermaid", {
            "mode": "template", "source": "flowchart TD\n  A[{{label}}] --> B",
        }, data=df)
        assert "A[Ship it]" in out["mermaid"]
        assert "mermaid.min.js" in out["html"]

    def test_flowchart_from_edges(self, registry):
        df = pd.DataFrame({"mgr": ["CEO", "CEO", "CTO"],
                           "report": ["CTO", "CFO", "Eng"],
                           "rel": ["", "", "leads"]})
        out = run_node(registry, "flograph.viz.mermaid", {
            "mode": "flowchart", "from_col": "mgr", "to_col": "report",
            "label_col": "rel", "direction": "LR",
        }, data=df)
        assert out["mermaid"].startswith("flowchart LR")
        assert '"CEO"' in out["mermaid"] and "|leads|" in out["mermaid"]

    def test_gantt_needs_end_or_duration(self, registry):
        df = pd.DataFrame({"task": ["a"], "start": ["2026-01-01"]})
        with pytest.raises(ValueError, match="End.*or.*Duration"):
            run_node(registry, "flograph.viz.mermaid",
                     {"mode": "gantt", "task_col": "task", "start_col": "start"},
                     data=df)

    def test_flowchart_needs_table(self, registry):
        with pytest.raises(ValueError, match="needs a table"):
            run_node(registry, "flograph.viz.mermaid",
                     {"mode": "flowchart", "from_col": "a", "to_col": "b"})


class TestReadHtml:
    _PAGE = """
    <html><body>
      <table><tr><th>x</th><th>y</th></tr><tr><td>1</td><td>2</td></tr></table>
      <table class="prices"><tr><th>item</th><th>cost</th></tr>
        <tr><td>widget</td><td>9.99</td></tr></table>
    </body></html>
    """

    def test_reads_from_html_port(self, registry):
        pytest.importorskip("lxml")
        out = run_node(registry, "flograph.io.read_html",
                       {"table_index": 0}, html=self._PAGE)
        assert list(out["table"].columns) == ["x", "y"]
        assert out["count"] == 2

    def test_match_and_attrs(self, registry):
        pytest.importorskip("lxml")
        out = run_node(registry, "flograph.io.read_html",
                       {"match": "widget"}, html=self._PAGE)
        assert list(out["table"]["item"]) == ["widget"]
        assert out["count"] == 1

    def test_index_out_of_range(self, registry):
        pytest.importorskip("lxml")
        with pytest.raises(ValueError, match="only 2"):
            run_node(registry, "flograph.io.read_html",
                     {"table_index": 5}, html=self._PAGE)

    def test_no_source(self, registry):
        with pytest.raises(ValueError, match="set 'URL or file'"):
            run_node(registry, "flograph.io.read_html", {})


# --------------------------------------------------------------------------
# Automation
# --------------------------------------------------------------------------
class TestNotify:
    def test_webhook_channel(self, registry, http_server):
        pytest.importorskip("httpx")
        out = run_node(registry, "flograph.automation.notify", {
            "channel": "webhook", "endpoint": f"{http_server}/hook",
            "subject": "nightly", "message": "12 rows loaded",
        })
        assert out["sent"] is True

    def test_slack_channel_and_data_preview(self, registry, http_server):
        pytest.importorskip("httpx")
        df = pd.DataFrame({"a": [1, 2]})
        out = run_node(registry, "flograph.automation.notify", {
            "channel": "slack", "endpoint": f"{http_server}/hook",
            "message": "done",
        }, data=df)
        assert out["sent"] is True

    def test_send_failure_warn(self, registry):
        pytest.importorskip("httpx")
        out = run_node(registry, "flograph.automation.notify", {
            "channel": "webhook", "endpoint": "http://127.0.0.1:9/nope",
            "message": "x", "on_error": "warn",
        })
        assert out["sent"] is False and out["detail"]

    def test_email_missing_config(self, registry):
        with pytest.raises(ValueError, match="SMTP host"):
            run_node(registry, "flograph.automation.notify",
                     {"channel": "email", "message": "hi"})

    def test_nothing_to_send(self, registry):
        with pytest.raises(ValueError, match="nothing to send"):
            run_node(registry, "flograph.automation.notify",
                     {"channel": "slack", "endpoint": "http://x"})


class TestShellCommand:
    def test_stdout_and_exit(self, registry):
        out = run_node(registry, "flograph.automation.shell_command",
                       {"command": "printf 'hello'"})
        assert out["stdout"] == "hello"
        assert out["exit_code"] == 0

    def test_stdin_piped(self, registry):
        out = run_node(registry, "flograph.automation.shell_command",
                       {"command": "cat"}, stdin="piped text")
        assert out["stdout"] == "piped text"

    def test_env_and_nonzero_fail(self, registry):
        with pytest.raises(ValueError, match="exited 3"):
            run_node(registry, "flograph.automation.shell_command",
                     {"command": "exit 3"})

    def test_nonzero_allowed(self, registry):
        out = run_node(registry, "flograph.automation.shell_command",
                       {"command": "exit 7", "fail_on_nonzero": False})
        assert out["exit_code"] == 7

    def test_timeout(self, registry):
        with pytest.raises(ValueError, match="timed out"):
            run_node(registry, "flograph.automation.shell_command",
                     {"command": "sleep 5", "timeout": 1.0})

    def test_no_command(self, registry):
        with pytest.raises(ValueError, match="no command"):
            run_node(registry, "flograph.automation.shell_command", {})


class TestWaitForFile:
    def test_ready_immediately(self, registry, tmp_path):
        f = tmp_path / "export.csv"
        f.write_text("a,b\n1,2\n")
        out = run_node(registry, "flograph.automation.wait_for_file", {
            "path": str(f), "stable_for": 0.0, "poll": 0.2,
        })
        assert out["ready"] is True
        assert out["path"] == str(f)
        assert out["size_bytes"] == f.stat().st_size

    def test_glob_newest(self, registry, tmp_path):
        import os
        import time
        (tmp_path / "a_1.csv").write_text("x")
        time.sleep(0.02)
        newer = tmp_path / "a_2.csv"
        newer.write_text("y")
        os.utime(newer, (time.time() + 5, time.time() + 5))
        out = run_node(registry, "flograph.automation.wait_for_file", {
            "path": str(tmp_path / "a_*.csv"), "stable_for": 0.0,
        })
        assert out["path"] == str(newer)

    def test_timeout_not_ready(self, registry, tmp_path):
        out = run_node(registry, "flograph.automation.wait_for_file", {
            "path": str(tmp_path / "never.csv"), "timeout": 1.0,
            "poll": 0.2, "on_timeout": "return not-ready",
        })
        assert out["ready"] is False

    def test_timeout_fail(self, registry, tmp_path):
        with pytest.raises(ValueError, match="timed out"):
            run_node(registry, "flograph.automation.wait_for_file", {
                "path": str(tmp_path / "never.csv"), "timeout": 1.0,
                "poll": 0.2,
            })


class TestListFiles:
    def _dir(self, tmp_path):
        (tmp_path / "one.csv").write_text("a")
        (tmp_path / "two.csv").write_text("bb")
        (tmp_path / "note.txt").write_text("ccc")
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "three.csv").write_text("dddd")
        return tmp_path

    def test_pattern_and_paths(self, registry, tmp_path):
        d = self._dir(tmp_path)
        out = run_node(registry, "flograph.io.list_files",
                       {"folder": str(d), "pattern": "*.csv"})
        assert out["count"] == 2
        assert set(out["files"]["name"]) == {"one.csv", "two.csv"}
        assert isinstance(out["paths"], list) and len(out["paths"]) == 2

    def test_recurse_and_sort_size(self, registry, tmp_path):
        d = self._dir(tmp_path)
        out = run_node(registry, "flograph.io.list_files", {
            "folder": str(d), "pattern": "*.csv", "recurse": True,
            "sort": "size", "newest_first": True,
        })
        assert out["count"] == 3
        assert list(out["files"]["name"])[0] == "three.csv"  # largest

    def test_modified_after(self, registry, tmp_path):
        import os
        import time
        d = self._dir(tmp_path)
        old = d / "one.csv"
        os.utime(old, (time.time() - 86400, time.time() - 86400))
        future = time.strftime("%Y-%m-%dT%H:%M",
                               time.localtime(time.time() - 3600))
        out = run_node(registry, "flograph.io.list_files", {
            "folder": str(d), "pattern": "*.csv", "modified_after": future,
        })
        assert "one.csv" not in set(out["files"]["name"])

    def test_bad_folder(self, registry, tmp_path):
        with pytest.raises(ValueError, match="not a folder"):
            run_node(registry, "flograph.io.list_files",
                     {"folder": str(tmp_path / "nope")})

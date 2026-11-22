"""Draft Emails (flograph issue #7): a table in, one draft per row opened in
the default email app through a mailto: link. Nothing here opens a real
window — the opener is swapped for a list."""
from urllib.parse import parse_qs, unquote, urlsplit

import pandas as pd
import pytest

from flograph.core.script import compile_run
from tests.conftest import FakeContext

TYPE = "flograph.automation.draft_emails"


@pytest.fixture
def drafts(registry):
    spec = registry.get(TYPE)
    run = compile_run(spec.source, "test-drafts")
    opened = []
    run.__globals__["_open"] = opened.append

    def go(table, **params):
        values = spec.default_params()
        values.update({"pause_s": 0.0})
        values.update(params)
        ctx = FakeContext(params=values)
        return run(ctx, table=table), ctx, opened
    go.mailto = run.__globals__["mailto"]
    return go


def parts(link):
    split = urlsplit(link)
    return unquote(split.path), {k: v[0] for k, v in parse_qs(split.query).items()}


class TestDraftEmails:
    def test_one_draft_per_row_in_order(self, drafts):
        table = pd.DataFrame({
            "To": ["a@x.com", "b@y.com"],
            "Subject": ["Hello A", "Hello B"],
            "Body": ["Line one\nLine two", "Hi"]})
        out, ctx, opened = drafts(table)
        assert out["count"] == 2
        assert len(opened) == 2
        to, query = parts(opened[0])
        assert to == "a@x.com"
        assert query["subject"] == "Hello A"
        assert query["body"] == "Line one\r\nLine two"     # CRLF per RFC 6068
        assert list(out["drafts"]["to"]) == ["a@x.com", "b@y.com"]
        assert out["drafts"]["opened"].all()

    def test_cc_bcc_and_several_addresses(self, drafts):
        table = pd.DataFrame({"to": ["a@x.com; b@x.com"], "cc": ["c@x.com"],
                              "bcc": ["d@x.com"]})
        _out, _ctx, opened = drafts(table)
        to, query = parts(opened[0])
        assert to == "a@x.com,b@x.com"
        assert query["cc"] == "c@x.com" and query["bcc"] == "d@x.com"

    def test_awkward_characters_survive(self, drafts):
        subject = "Q3 & Q4: 50% off? #1 = yes"
        link = drafts.mailto("a@x.com", subject=subject, body="a+b=c & d")
        _to, query = parts(link)
        assert query["subject"] == subject
        assert query["body"] == "a+b=c & d"

    def test_rows_without_an_address_are_skipped(self, drafts):
        table = pd.DataFrame({"to": ["a@x.com", "", None], "subject": ["s", "t", "u"]})
        out, ctx, opened = drafts(table)
        assert out["count"] == 1
        assert any("skipped 2" in line for line in ctx.logs)

    def test_preview_opens_nothing(self, drafts):
        out, ctx, opened = drafts(pd.DataFrame({"to": ["a@x.com"]}),
                                  mode="Preview only")
        assert opened == []
        assert out["count"] == 0
        assert out["drafts"]["link"][0].startswith("mailto:a@x.com")
        assert not out["drafts"]["opened"][0]

    def test_too_many_is_refused_before_anything_opens(self, drafts):
        table = pd.DataFrame({"to": [f"p{i}@x.com" for i in range(5)]})
        with pytest.raises(ValueError, match="Most emails"):
            drafts(table, max_emails=3)
        assert drafts(table, max_emails=5)[0]["count"] == 5

    def test_a_missing_to_column_says_what_it_needs(self, drafts):
        with pytest.raises(ValueError, match="needs a 'to' column"):
            drafts(pd.DataFrame({"email": ["a@x.com"]}))

    def test_a_long_draft_is_flagged(self, drafts):
        table = pd.DataFrame({"to": ["a@x.com"], "body": ["x" * 3000]})
        _out, ctx, _opened = drafts(table)
        assert any("cut the body short" in line for line in ctx.logs)


def test_the_example_opens_nothing_until_asked():
    """43_draft_emails runs when it is opened; a window per customer popping
    up from opening an example would be a nasty surprise."""
    import json
    from pathlib import Path

    path = (Path(__file__).resolve().parents[1] / "src" / "flograph" / "templates"
            / "43_draft_emails.flograph")
    nodes = json.loads(path.read_text())["graph"]["nodes"]
    [node] = [n for n in nodes if n["type"] == TYPE]
    assert node["params"]["mode"] == "Preview only"

"""The infographic builder: HTML Template and Visual Style.

Two nodes and two Qt-free core modules. `core.infographic` is the template
grammar — tokens, repeat blocks, conditions, bindings — and
`core.visual_style` is the design-token set the page is dressed in.

What is not here: whether the page *looks* right. That was checked by
rendering every layout through the report's own printToPdf path and looking
at the pictures, which is also where the sizing rule in the node's docstring
came from — a page being printed for a report reports **zero** for its own
width and height, so nothing on the page can size itself to the box.
"""
from __future__ import annotations

import re

import pandas as pd
import pytest

from flograph.core import NodeRegistry, compile_run
from flograph.core import infographic as ig
from flograph.core import visual_style as vs
from tests.conftest import FakeContext

TEMPLATE = "flograph.viz.html_template"
STYLE = "flograph.viz.visual_style"


@pytest.fixture(scope="module")
def registry():
    reg = NodeRegistry()
    reg.load_builtins()
    return reg


def run_node(registry, type_id, params=None, **inputs):
    spec = registry.get(type_id)
    defaults = spec.default_params()
    defaults.update(params or {})
    context = FakeContext(params=defaults)
    return context, compile_run(spec.source, f"test-{type_id}")(context,
                                                               **inputs)


@pytest.fixture
def sales():
    return pd.DataFrame({
        "region": ["North", "South", "East", "West"],
        "revenue": [412000, 288500, 195000, 96400],
        "growth": [12.4, -3.1, 8.8, 21.0],
        "status": ["ok", "fail", "ok", "ok"],
    })


ROWS = [{"region": "North", "revenue": 400, "growth": 10.0},
        {"region": "South", "revenue": 300, "growth": -2.0},
        {"region": "East", "revenue": 100, "growth": 0.0}]


# --------------------------------------------------------------- the grammar

class TestTokens:
    def test_a_bare_name_is_the_value(self):
        out, _ = ig.render("{{region}}", ROWS)
        assert out == "North"

    def test_a_format_spec_is_applied(self):
        out, _ = ig.render("{{revenue:$,.2f}}", ROWS)
        assert out == "$400.00"

    def test_a_value_is_escaped_by_default(self):
        out, _ = ig.render("{{name}}", [{"name": "<b>&</b>"}])
        assert out == "&lt;b&gt;&amp;&lt;/b&gt;"

    def test_triple_braces_insert_raw_markup(self):
        out, _ = ig.render("{{{name}}}", [{"name": "<b>bold</b>"}])
        assert out == "<b>bold</b>"

    def test_an_unknown_name_is_left_alone_and_reported(self):
        out, missing = ig.render("{{nope}}", ROWS)
        assert out == "{{nope}}" and missing == ["nope"]

    def test_blank_mode_removes_it(self):
        out, missing = ig.render("[{{nope}}]", ROWS, missing="blank")
        assert out == "[]" and missing == ["nope"]

    def test_error_mode_says_which_one(self):
        with pytest.raises(ig.TemplateError, match="nope"):
            ig.render("{{nope}}", ROWS, missing="error")

    def test_the_grammar_matches_svg_templates(self, registry):
        """Both template nodes must format a value identically — the whole
        claim that learning one teaches the other rests on it."""
        source = registry.get("flograph.viz.svg_template").source
        namespace: dict = {}
        exec(compile(source, "svg_template", "exec"), namespace)
        sibling = namespace["_format"]
        for value, spec in [(1234.5, ",.0f"), (1234.5, "$,.2f"),
                            (0.256, ".1%"), ("text", ""), (None, ",.0f"),
                            ("12", "£,.0f"), (7, "03d"), ("x", ",.0f")]:
            assert ig.format_value(value, spec) == sibling(value, spec), (
                f"{value!r} with {spec!r}")


class TestEach:
    def test_it_repeats_once_per_row(self):
        out, _ = ig.render("{{#each}}[{{region}}]{{/each}}", ROWS)
        assert out == "[North][South][East]"

    def test_the_counters_describe_the_run(self):
        out, _ = ig.render("{{#each}}{{_n}}/{{_count}} {{/each}}", ROWS)
        assert out == "1/3 2/3 3/3 "

    def test_the_colour_cycles_through_the_palette(self):
        out, _ = ig.render("{{#each}}{{_color}},{{/each}}", ROWS,
                           palette=["#a", "#b"])
        assert out == "#a,#b,#a,"

    def test_outside_a_block_a_name_is_one_row(self):
        out, _ = ig.render("{{region}}", ROWS, row=2)
        assert out == "East"

    def test_a_row_past_the_end_is_clamped(self):
        out, _ = ig.render("{{region}}", ROWS, row=99)
        assert out == "East"

    def test_a_limit_cuts_the_run(self):
        out, _ = ig.render("{{#each}}{{region}} {{/each}}", ROWS, limit=2)
        assert out == "North South "

    def test_no_rows_leaves_the_block_empty(self):
        out, _ = ig.render("a{{#each}}{{region}}{{/each}}b", [])
        assert out == "ab"


class TestConditions:
    def test_it_keeps_the_body_when_there_is_something(self):
        out, _ = ig.render("{{#if growth}}yes{{/if}}", ROWS)
        assert out == "yes"

    @pytest.mark.parametrize("value", [0, "", None, False, "   "])
    def test_nothing_is_dropped(self, value):
        out, _ = ig.render("{{#if v}}yes{{/if}}", [{"v": value}])
        assert out == ""

    def test_else_is_the_other_half(self):
        out, _ = ig.render("{{#each}}{{#if growth > 0}}up{{#else}}down"
                           "{{/if}} {{/each}}", ROWS)
        assert out == "up down down "

    def test_conditions_nest(self):
        template = "{{#if a}}A{{#if b}}B{{/if}}{{/if}}"
        assert ig.render(template, [{"a": 1, "b": 1}])[0] == "AB"
        assert ig.render(template, [{"a": 1, "b": 0}])[0] == "A"
        assert ig.render(template, [{"a": 0, "b": 1}])[0] == ""

    @pytest.mark.parametrize("value,op,other,want", [
        (5, ">", "0", True), (-3, ">", "0", False), (0, ">", "0", False),
        (5, ">=", "5", True), (4, "<", "5", True), (5, "<=", "4", False),
        ("fail", "=", "fail", True), ("Fail", "=", "fail", True),
        ("ok", "!=", "fail", True), ("Acme Ltd", "contains", "ltd", True),
        ("Acme", "contains", "ltd", False),
        # text nobody can order is a template mistake, not a blank page
        ("abc", ">", "0", False), (None, ">", "0", False),
    ])
    def test_the_operators(self, value, op, other, want):
        assert ig.compare(value, op, other) is want


class TestBindings:
    def test_an_aggregate_is_one_value_for_the_page(self):
        out, _ = ig.render("{{total:,.0f}}", ROWS,
                           bindings="total = sum(revenue)")
        assert out == "800"

    @pytest.mark.parametrize("fn,want", [
        ("sum", "800"), ("mean", "267"), ("min", "100"), ("max", "400"),
        ("median", "300"), ("count", "3"),
    ])
    def test_the_aggregates(self, fn, want):
        out, _ = ig.render("{{v:,.0f}}", ROWS, bindings=f"v = {fn}(revenue)")
        assert out == want

    def test_share_is_a_percentage_of_the_total(self):
        out, _ = ig.render("{{#each}}{{s:.1f}} {{/each}}", ROWS,
                           bindings="s = share(revenue)")
        assert out == "50.0 37.5 12.5 "

    def test_pct_is_against_the_biggest_row(self):
        out, _ = ig.render("{{#each}}{{p:.0f}} {{/each}}", ROWS,
                           bindings="p = pct(revenue)")
        assert out == "100 75 25 "

    def test_rank_puts_the_largest_first(self):
        out, _ = ig.render("{{#each}}{{r}} {{/each}}", ROWS,
                           bindings="r = rank(revenue)")
        assert out == "1 2 3 "

    def test_a_literal_is_itself(self):
        out, _ = ig.render("{{t}}", ROWS, bindings="t = Q3 results")
        assert out == "Q3 results"

    def test_a_column_can_be_renamed(self):
        out, _ = ig.render("{{money:,.0f}}", ROWS, bindings="money = revenue")
        assert out == "400"

    def test_a_missing_column_says_so(self):
        with pytest.raises(ig.TemplateError, match="nope"):
            ig.render("{{v}}", ROWS, bindings="v = sum(nope)")

    def test_a_line_without_an_equals_says_which_line(self):
        with pytest.raises(ig.TemplateError, match="line 2"):
            ig.render("", ROWS, bindings="a = 1\nbroken")

    def test_comments_and_blanks_are_skipped(self):
        out, _ = ig.render("{{a}}", ROWS, bindings="# note\n\na = one")
        assert out == "one"

    def test_an_empty_table_does_not_refuse_every_binding(self):
        """With no rows there are no column names to check against, and a
        wall of errors is worse than an empty page."""
        out, _ = ig.render("{{#each}}{{s}}{{/each}}", [],
                           bindings="s = share(revenue)")
        assert out == ""


class TestNumbers:
    @pytest.mark.parametrize("text,want", [
        ("1,234", 1234), ("$1,234.5", 1234.5), ("12%", 12), ("  7 ", 7),
        ("abc", None), ("", None), (None, None), (True, None),
    ])
    def test_reading_a_number(self, text, want):
        assert ig.to_number(text) == want

    def test_a_nan_reads_as_nothing(self):
        assert ig.to_number(float("nan")) is None
        assert ig.format_value(float("nan"), ",.0f") == ""
        assert ig.truthy(float("nan")) is False

    def test_a_spec_that_does_not_fit_falls_back(self):
        """A template is drawn live while it is being typed; a half-written
        format must not blank the card."""
        assert ig.format_value("text", ",.0f") == "text"


# ------------------------------------------------------------- visual style

class TestStyleTokens:
    def test_a_blank_setting_is_left_out(self):
        payload = vs.style_payload({"accent": "", "theme": "", "size": ""})
        assert payload["tokens"] == {}

    def test_only_what_was_set_is_carried(self):
        payload = vs.style_payload({"accent": "red", "size": "18"})
        assert payload["tokens"] == {"accent": "#ef4444", "size": 18}

    def test_defaults_arrive_only_when_resolved(self):
        tok = vs.tokens(vs.style_payload({"accent": "red"}))
        assert tok["accent"] == "#ef4444"
        assert tok["bg"] == vs.DEFAULTS["bg"]

    def test_the_theme_moves_the_colour_base(self):
        tok = vs.tokens(vs.style_payload({"theme": "light"}))
        assert tok["bg"] == vs.LIGHT["bg"] and tok["fg"] == vs.LIGHT["fg"]

    def test_a_colour_lands_on_top_of_the_theme(self):
        tok = vs.tokens(vs.style_payload({"theme": "light",
                                          "accent": "#123456"}))
        assert tok["bg"] == vs.LIGHT["bg"] and tok["accent"] == "#123456"

    def test_a_later_style_wins(self):
        base = vs.style_payload({"accent": "red", "size": "20"})
        own = vs.style_payload({"accent": "blue"})
        tok = vs.tokens(vs.merge_styles(base, own))
        assert tok["accent"] == "#2563eb" and tok["size"] == 20

    def test_a_bad_colour_is_reported_not_passed_through(self):
        """An unrecognised colour reaching CSS is invisible: the browser
        drops the line and the element inherits something plausible."""
        payload = vs.style_payload({"accent": "burnt sienna"})
        assert payload["tokens"] == {}
        assert "accent" in payload["errors"][0]

    def test_sizes_are_clamped(self):
        payload = vs.style_payload({"size": "9999", "radius": "-4"})
        assert payload["tokens"]["size"] == 96
        assert payload["tokens"]["radius"] == 0

    def test_a_size_that_is_not_a_number_is_reported(self):
        payload = vs.style_payload({"size": "big"})
        assert payload["tokens"] == {} and payload["errors"]

    def test_a_hand_written_palette_beats_the_preset(self):
        payload = vs.style_payload({"palette": "warm",
                                    "colors": "#111111, red"})
        assert payload["tokens"]["palette"] == ["#111111", "#ef4444"]

    def test_a_named_palette(self):
        payload = vs.style_payload({"palette": "cool"})
        assert payload["tokens"]["palette"] == vs.PALETTES["cool"]

    def test_an_unknown_palette_is_reported(self):
        payload = vs.style_payload({"palette": "neon"})
        assert "neon" in payload["errors"][0]

    def test_a_payload_survives_a_round_trip_as_json(self):
        """It rides the style port and lands in the run cache."""
        import json
        payload = vs.style_payload({"theme": "light", "accent": "red"})
        assert vs.tokens(json.loads(json.dumps(payload))) == vs.tokens(payload)


class TestStylesheet:
    def test_every_token_reaches_css(self):
        css = vs.css_variables(vs.tokens(None))
        for name in ("--bg", "--surface", "--fg", "--muted", "--accent",
                     "--border", "--font", "--size", "--radius", "--gap",
                     "--pad", "--shadow", "--cols"):
            assert name + ":" in css

    def test_the_palette_becomes_numbered_variables(self):
        css = vs.stylesheet(vs.tokens(vs.style_payload({"colors": "red, blue"})))
        assert "--c1:#ef4444" in css and "--c2:#2563eb" in css
        assert ".c2{color:var(--c2)}" in css

    def test_shadow_off_is_none_not_a_missing_variable(self):
        css = vs.css_variables(vs.tokens({"tokens": {"shadow": False}}))
        assert "--shadow:none" in css

    def test_the_page_fetches_nothing(self):
        page = vs.page("<p>hi</p>", vs.tokens(None))
        assert not re.search(r'(?:src|href)\s*=\s*"?https?://', page)
        assert "<script" not in page

    def test_backgrounds_are_told_to_print(self):
        """Without this a printed report drops every filled block."""
        assert "print-color-adjust:exact" in vs.stylesheet(vs.tokens(None))

    def test_the_page_has_a_margin(self):
        """The gap around a visual. It sits on `body`, not on `.sheet`, so a
        template written without a wrapper still gets it — and it must not
        be stripped for print, which left a report embed hard against its
        own edge while the card looked right."""
        css = vs.stylesheet(vs.tokens(None))
        body_rule = css.split("body{background")[1].split("}")[0]
        assert "padding:var(--pad)" in body_rule
        assert "padding" not in css.split(".sheet{")[1].split("}")[0]
        assert "@media print" not in css or ".sheet{padding:0}" not in css

    def test_the_semantic_fills_ignore_the_palette(self):
        """"At risk" has to be red whichever accent run somebody picked."""
        loud = vs.stylesheet(vs.tokens(vs.style_payload({"palette": "grey"})))
        assert ".bad{background:#ef4444" in loud
        assert ".good{background:#10b981" in loud

    def test_extra_css_is_last_so_it_wins(self):
        page = vs.page("", vs.tokens(None), extra_css=".card{color:red}")
        assert page.index(".card{color:red}") > page.index("--accent")


# ------------------------------------------------------------------ the nodes

class TestVisualStyleNode:
    def test_it_emits_a_style(self, registry):
        _, out = run_node(registry, STYLE, {"theme": "light"})
        assert out["style"]["tokens"]["theme"] == "light"

    def test_inherit_means_nothing_set(self, registry):
        _, out = run_node(registry, STYLE)
        assert out["style"]["tokens"] == {}

    def test_it_layers_over_the_style_it_is_given(self, registry):
        _, base = run_node(registry, STYLE, {"theme": "light",
                                             "accent": "red"})
        _, out = run_node(registry, STYLE, {"accent": "blue"},
                          style=base["style"])
        tok = vs.tokens(out["style"])
        assert tok["theme"] == "light" and tok["accent"] == "#2563eb"

    def test_a_bad_setting_is_logged_not_raised(self, registry):
        ctx, out = run_node(registry, STYLE, {"accent": "burnt sienna"})
        assert out["style"]["tokens"] == {}
        assert any("ignored" in line for line in ctx.logs)


class TestHtmlTemplateNode:
    @pytest.mark.parametrize("layout",
                             ["cards", "bars", "kpi strip", "big number"])
    def test_every_layout_renders_without_leftovers(self, registry, sales,
                                                    layout):
        _, out = run_node(registry, TEMPLATE,
                          {"layout": layout, "title": "T", "subtitle": "S"},
                          data=sales)
        body = out["html"].split("<body>", 1)[1]
        assert "{{" not in body and "{{/" not in body
        # "big number" shows one row by design; the rest repeat.
        wanted = (sales["region"][:1] if layout == "big number"
                  else sales["region"])
        for region in wanted:
            assert region in body

    @pytest.mark.parametrize("layout",
                             ["cards", "bars", "kpi strip", "big number"])
    def test_every_layout_sits_in_a_sheet(self, registry, sales, layout):
        """A built-in that ran hard against the edge of its card while a
        hand-written template breathed is what started this."""
        _, out = run_node(registry, TEMPLATE, {"layout": layout}, data=sales)
        body = out["html"].split("<body>", 1)[1]
        assert body.startswith('<div class="sheet">')

    def test_it_draws_with_no_style_wired_in(self, registry, sales):
        _, out = run_node(registry, TEMPLATE, data=sales)
        assert vs.DEFAULTS["bg"] in out["html"]

    def test_it_draws_with_no_data_at_all(self, registry):
        """The card must show something the moment it is dropped."""
        ctx, out = run_node(registry, TEMPLATE, {"title": "Nothing yet"})
        assert "Nothing yet" in out["html"] and len(out["table"]) == 0

    def test_the_style_input_dresses_the_page(self, registry, sales):
        _, style = run_node(registry, STYLE, {"theme": "light"})
        _, out = run_node(registry, TEMPLATE, data=sales,
                          style=style["style"])
        assert vs.LIGHT["bg"] in out["html"]

    def test_the_style_is_passed_on_so_it_can_chain(self, registry, sales):
        _, style = run_node(registry, STYLE, {"accent": "red"})
        _, out = run_node(registry, TEMPLATE, data=sales,
                          style=style["style"])
        assert out["style"]["tokens"]["accent"] == "#ef4444"

    def test_columns_are_detected_when_not_named(self, registry, sales):
        ctx, out = run_node(registry, TEMPLATE, data=sales)
        assert "region" in ctx.logs[0] and "revenue" in ctx.logs[0]

    def test_a_named_column_wins(self, registry, sales):
        ctx, _ = run_node(registry, TEMPLATE,
                          {"label_column": "status",
                           "value_column": "growth"}, data=sales)
        assert "status" in ctx.logs[0] and "growth" in ctx.logs[0]

    def test_a_column_that_is_not_there_says_what_is(self, registry, sales):
        with pytest.raises(ValueError, match="revenue"):
            run_node(registry, TEMPLATE, {"label_column": "nope"},
                     data=sales)

    def test_the_template_box_beats_the_layout(self, registry, sales):
        ctx, out = run_node(registry, TEMPLATE,
                            {"layout": "bars",
                             "template": "<p>{{#each}}{{region}} {{/each}}</p>"},
                            data=sales)
        assert "<p>North South East West </p>" in out["html"]
        assert any("Layout setting is ignored" in line for line in ctx.logs)

    def test_bindings_reach_the_template(self, registry, sales):
        _, out = run_node(registry, TEMPLATE,
                          {"template": "{{total:$,.0f}}",
                           "bindings": "total = sum(revenue)"}, data=sales)
        assert "$991,900" in out["html"]

    def test_the_value_format_is_applied(self, registry, sales):
        _, out = run_node(registry, TEMPLATE, {"value_format": "$,.0f"},
                          data=sales)
        assert "$412,000" in out["html"]

    def test_columns_across_reaches_the_grid(self, registry, sales):
        _, out = run_node(registry, TEMPLATE, {"columns": 5}, data=sales)
        assert "--cols:5" in out["html"]

    def test_extra_css_is_appended(self, registry, sales):
        _, out = run_node(registry, TEMPLATE,
                          {"css": ".card{outline:1px solid lime}"},
                          data=sales)
        assert ".card{outline:1px solid lime}" in out["html"]

    def test_a_parameter_is_data_and_the_template_is_markup(self, registry,
                                                            sales):
        """The distinction that catches people out: an entity typed into
        Title prints as its own characters, the same entity in the Template
        box is markup."""
        _, out = run_node(registry, TEMPLATE,
                          {"title": "A &middot; B",
                           "template": "<p>C &middot; D</p>"}, data=sales)
        assert "A &amp;middot; B" in out["html"]
        assert "<p>C &middot; D</p>" in out["html"]

    def test_rows_shown_caps_the_run(self, registry, sales):
        _, out = run_node(registry, TEMPLATE, {"rows": 2}, data=sales)
        assert "North" in out["html"] and "West" not in out["html"]


class TestClicking:
    def test_no_click_means_no_javascript(self, registry, sales):
        """A static infographic should carry nothing that can run."""
        _, out = run_node(registry, TEMPLATE, data=sales)
        assert "<script" not in out["html"]
        assert "onclick" not in out["html"]

    def test_a_click_handler_is_added_when_asked(self, registry, sales):
        _, out = run_node(registry, TEMPLATE, {"on_click": "select one"},
                          data=sales)
        assert "onclick=" in out["html"] and "flograph.select" in out["html"]

    def test_the_page_survives_having_no_flograph(self, registry, sales):
        """The same file is meant to open somewhere with nothing behind it."""
        _, out = run_node(registry, TEMPLATE, {"on_click": "select one"},
                          data=sales)
        assert "window.flograph && flograph.select" in out["html"]

    def test_a_selection_filters_the_table(self, registry, sales):
        _, out = run_node(registry, TEMPLATE,
                          {"on_click": "select one",
                           "selected": '["South"]'}, data=sales)
        assert out["table"]["region"].tolist() == ["South"]
        assert out["selected"] == ["South"]

    def test_the_picked_block_is_marked_and_the_rest_dimmed(self, registry,
                                                            sales):
        _, out = run_node(registry, TEMPLATE,
                          {"on_click": "select one",
                           "selected": '["South"]'}, data=sales)
        assert "card stack pick picked" in out["html"]
        assert "card stack pick dim" in out["html"]

    def test_nothing_selected_leaves_every_block_plain(self, registry, sales):
        _, out = run_node(registry, TEMPLATE, {"on_click": "select one"},
                          data=sales)
        assert "dim" not in out["html"].split("<body>", 1)[1]

    def test_a_selection_is_ignored_when_clicking_is_off(self, registry,
                                                         sales):
        _, out = run_node(registry, TEMPLATE, {"selected": '["South"]'},
                          data=sales)
        assert len(out["table"]) == len(sales) and out["selected"] == []


class TestItTravels:
    """Every one of these is a way a page that looks right on the card can
    still fail once it leaves it."""

    @pytest.mark.parametrize("layout",
                             ["cards", "bars", "kpi strip", "big number"])
    def test_nothing_is_fetched(self, registry, sales, layout):
        _, out = run_node(registry, TEMPLATE, {"layout": layout}, data=sales)
        assert not re.search(r'(?:src|href)\s*=\s*"?https?://', out["html"])

    def test_no_cdn_hostname_appears(self, registry, sales):
        _, out = run_node(registry, TEMPLATE, data=sales)
        for host in ("cdnjs", "unpkg", "jsdelivr", "fonts.googleapis"):
            assert host not in out["html"]

    def test_there_is_no_canvas_to_lose_in_a_report(self, registry, sales):
        """printToPdf drops a canvas; this page is HTML and CSS only."""
        _, out = run_node(registry, TEMPLATE, data=sales)
        assert "<canvas" not in out["html"]

    def test_nothing_animates_into_a_snapshot(self, registry, sales):
        """A report settles for 350ms; an entry animation is caught
        half-drawn."""
        _, out = run_node(registry, TEMPLATE, data=sales)
        assert "@keyframes" not in out["html"]
        assert "animation:" not in out["html"]

    def test_the_page_does_not_size_itself_to_a_box(self, registry, sales):
        """The snapshot view reports zero for its own width and height, so a
        page that measures the viewport draws nothing there."""
        _, out = run_node(registry, TEMPLATE, {"on_click": "select one"},
                          data=sales)
        for measure in ("innerHeight", "innerWidth", "clientHeight",
                        "clientWidth"):
            assert measure not in out["html"]

    def test_run_never_reads_the_cosmetic_size(self, registry, sales):
        """Width, height and scale are the card's, not the page's — reading
        them would re-run the node on every resize."""
        _, wide = run_node(registry, TEMPLATE,
                           {"width": 1600, "height": 2000, "scale": 400},
                           data=sales)
        _, small = run_node(registry, TEMPLATE,
                            {"width": 260, "height": 200, "scale": 25},
                            data=sales)
        assert wide["html"] == small["html"]

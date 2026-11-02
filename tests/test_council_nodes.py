"""The node-council batch (board cards "Node idea N"): cohorts, lookups, the
ml category, status cards, file operations and multi-sheet Excel — each run
headless through the contract, error paths included."""
import pandas as pd
import pytest

from tests.test_stdlib_nodes import run_node


class TestCohortAnalysis:
    T = "flograph.transform.cohort_analysis"

    @pytest.fixture
    def events(self):
        return pd.DataFrame({
            "user": ["a", "a", "b", "b", "c", "d", "d", None],
            "when": ["2026-01-05", "2026-02-10", "2026-01-20", "2026-03-01",
                     "2026-02-02", "2026-02-15", "2026-03-15", "2026-01-01"],
        })

    def test_labels_rows_and_builds_the_matrix(self, registry, events):
        out = run_node(registry, self.T, {"user_id": "user",
                                          "date_column": "when"}, table=events)
        rows, matrix = out["table"], out["retention"]
        assert len(rows) == 7  # the row without a person is left out
        a = rows[rows.user == "a"]
        assert a["cohort"].tolist() == ["2026-01", "2026-01"]
        assert a["period"].tolist() == [0, 1]
        assert matrix["cohort"].tolist() == ["2026-01", "2026-02"]
        assert matrix["cohort_size"].tolist() == [2, 2]
        jan = matrix.iloc[0]
        assert (jan["0"], jan["1"], jan["2"]) == (2, 1, 1)

    def test_percent_and_minimum(self, registry, events):
        out = run_node(registry, self.T, {
            "user_id": "user", "date_column": "when",
            "retention_as": "percent"}, table=events)
        assert out["retention"]["0"].tolist() == [1.0, 1.0]
        assert out["retention"].iloc[0]["1"] == 0.5
        weekly = run_node(registry, self.T, {
            "user_id": "user", "date_column": "when", "cohort_unit": "year",
            "period_unit": "month"}, table=events)
        assert weekly["retention"]["cohort_size"].tolist() == [4]
        with pytest.raises(ValueError, match="Smallest cohort"):
            run_node(registry, self.T, {"user_id": "user", "date_column": "when",
                                        "min_count": 5}, table=events)

    def test_errors(self, registry, events):
        with pytest.raises(ValueError, match="Person column"):
            run_node(registry, self.T, {"date_column": "when"}, table=events)
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, self.T, {"user_id": "user", "date_column": "x"},
                     table=events)


class TestReplaceValuesLookup:
    T = "flograph.transform.replace_values"

    def test_lookup_table_maps_without_chaining(self, registry):
        df = pd.DataFrame({"code": ["GB", "FR", "XX", None]})
        lookup = pd.DataFrame({"k": ["GB", "FR", "France"],
                               "v": ["United Kingdom", "France", "Nope"]})
        out = run_node(registry, self.T, {"columns": "code"}, table=df,
                       lookup=lookup)
        assert out["code"].tolist()[:3] == ["United Kingdom", "France", "XX"]

    def test_unmatched_default_and_missing(self, registry):
        df = pd.DataFrame({"code": ["GB", "zz", None]})
        out = run_node(registry, self.T, {
            "pairs": "GB = United Kingdom", "unmatched": "use default",
            "default": "Unknown"}, table=df)
        assert out["code"].tolist()[:2] == ["United Kingdom", "Unknown"]
        assert pd.isna(out["code"].iloc[2])  # empty stays empty
        gone = run_node(registry, self.T, {
            "pairs": "gb = UK", "case_insensitive": True,
            "unmatched": "make missing"}, table=df, lookup={"ZZ": "Zed"})
        assert gone["code"].tolist()[:2] == ["UK", "Zed"]

    def test_bad_lookup(self, registry):
        df = pd.DataFrame({"code": ["GB"]})
        with pytest.raises(ValueError, match="two columns"):
            run_node(registry, self.T, {}, table=df,
                     lookup=pd.DataFrame({"k": ["GB"]}))
        with pytest.raises(ValueError, match="no replacements"):
            run_node(registry, self.T, {}, table=df)


@pytest.fixture
def houses():
    import numpy as np
    rng = np.random.default_rng(1)
    n = 120
    size = rng.uniform(40, 200, n)
    rooms = rng.integers(1, 6, n)
    city = rng.choice(["Leeds", "York", "Hull"], n)
    price = size * 3 + rooms * 20 + rng.normal(0, 5, n)
    return pd.DataFrame({"size": size, "rooms": rooms, "city": city,
                         "price": price,
                         "dear": (price > price.mean())})


def test_a_figure_card_leads_with_what_it_draws(registry):
    """The canvas card and the dashboard tile draw a node's *first* output.
    Model Evaluation and K-Means once led with a table and showed a blank
    card while their figure sat unused in a later port."""
    drawable = {"figure": {"figure", "any", "object"},
                "webview": {"string", "any", "object"}}
    wrong = [(s.type_id, s.outputs[0].type.value)
             for s in registry.all()
             if s.card in drawable and s.outputs
             and s.outputs[0].type.value not in drawable[s.card]]
    assert not wrong


def test_scikit_learn_first_import_survives_parallel_nodes():
    """Nodes run at the same time. Four ML nodes starting together each
    imported scikit-learn for the first time on their own thread, and some
    got a half-initialised module ("cannot import name 'clone' from
    partially initialized module 'sklearn.base'"). Only a fresh process
    races the first import, and a bare threaded import script doesn't
    reproduce it — the engine's own timing does, every time (4 of 44 nodes
    failed on each of three runs with `mlkit._SKLEARN_IMPORT` disabled). So
    this runs the ML example headless, as a user's Run All would."""
    import importlib.resources
    import os
    import subprocess
    import sys
    pytest.importorskip("sklearn")
    pytest.importorskip("plotly")
    flow = importlib.resources.files("flograph.templates") \
        / "38_machine_learning.flograph"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    done = subprocess.run(
        [sys.executable, "-m", "flograph.engine.headless", str(flow)],
        capture_output=True, text=True, timeout=300, env=env)
    assert "FAILED" not in done.stdout + done.stderr, done.stdout[-2000:]
    assert done.returncode == 0, done.stderr[-2000:]


class TestMlPreparation:
    def test_split_sizes_seed_and_order(self, registry, houses):
        t = "flograph.ml.train_test_split"
        out = run_node(registry, t, {"test_size": 0.25, "seed": 3},
                       table=houses)
        assert (len(out["train"]), len(out["test"])) == (90, 30)
        assert out["test"].index.is_monotonic_increasing
        again = run_node(registry, t, {"test_size": 0.25, "seed": 3},
                         table=houses)
        assert out["test"].index.equals(again["test"].index)
        tail = run_node(registry, t, {"shuffle": False}, table=houses)
        assert tail["test"].index.tolist() == list(range(96, 120))

    def test_split_stratified_keeps_the_mix(self, registry, houses):
        out = run_node(registry, "flograph.ml.train_test_split",
                       {"stratify": "city", "test_size": 0.5}, table=houses)
        whole = houses.city.value_counts()
        test = out["test"].city.value_counts()
        for city in whole.index:
            assert abs(test[city] - whole[city] / 2) <= 1
        with pytest.raises(ValueError, match="Shuffle"):
            run_node(registry, "flograph.ml.train_test_split",
                     {"stratify": "city", "shuffle": False}, table=houses)

    def test_scaler_fits_then_reuses(self, registry, houses):
        t = "flograph.ml.feature_scaler"
        fit = run_node(registry, t, {"columns": "size, rooms"}, table=houses)
        assert abs(fit["scaled"]["size"].mean()) < 1e-9
        assert abs(fit["scaled"]["size"].std(ddof=0) - 1) < 1e-9
        assert fit["scaled"]["price"].equals(houses["price"])
        other = houses.head(10)
        again = run_node(registry, t, {"method": "min-max"}, table=other,
                         scaler=fit["scaler"])
        assert again["scaled"]["size"].tolist() == \
            fit["scaled"]["size"].head(10).tolist()
        mm = run_node(registry, t, {"method": "min-max"}, table=houses)
        assert mm["scaled"]["size"].min() == 0 and mm["scaled"]["size"].max() == 1
        with pytest.raises(ValueError, match="doesn't have"):
            run_node(registry, t, {}, table=houses[["price"]],
                     scaler=fit["scaler"])

    def test_one_hot_and_reuse(self, registry):
        t = "flograph.ml.one_hot_encode"
        df = pd.DataFrame({"city": ["York", "Leeds", "York"], "n": [1, 2, 3]})
        out = run_node(registry, t, {}, table=df)
        assert list(out["table"].columns) == ["n", "city_Leeds", "city_York"]
        assert out["table"]["city_York"].tolist() == [1, 0, 1]
        drop = run_node(registry, t, {"drop_first": True}, table=df)
        assert list(drop["table"].columns) == ["n", "city_York"]
        new = pd.DataFrame({"city": ["Hull", "Leeds"], "n": [4, 5]})
        same = run_node(registry, t, {}, table=new, encoder=out["encoder"])
        assert list(same["table"].columns) == ["n", "city_Leeds", "city_York"]
        assert same["table"].iloc[0, 1:].tolist() == [0, 0]
        with pytest.raises(ValueError, match="never saw"):
            run_node(registry, t, {"handle_unknown": "error"}, table=new,
                     encoder=out["encoder"])

    def test_label_encode_round_trip(self, registry):
        t = "flograph.ml.label_encode"
        df = pd.DataFrame({"tier": ["gold", "bronze", None, "silver"]})
        out = run_node(registry, t, {}, table=df)
        assert out["encoded"]["tier"].tolist() == [1, 0, -1, 2]
        back = run_node(registry, t, {"direction": "decode"},
                        table=pd.DataFrame({"tier": [2, 0, 7]}),
                        mappings=out["mappings"])
        assert back["encoded"]["tier"].tolist()[:2] == ["silver", "bronze"]
        assert pd.isna(back["encoded"]["tier"].iloc[2])
        with pytest.raises(ValueError, match="needs the key"):
            run_node(registry, t, {"direction": "decode"}, table=df)

    def test_correlation_matrix(self, registry, houses):
        pytest.importorskip("plotly")
        out = run_node(registry, "flograph.ml.correlation_matrix",
                       {"columns": "size, price, rooms"}, table=houses)
        m = out["matrix"].set_index("column")
        assert m.loc["size", "price"] > 0.9
        assert m.loc["size", "size"] == pytest.approx(1.0)
        heat = out["figure"].data[0]
        assert heat.type == "heatmap" and list(heat.x) == ["size", "price", "rooms"]
        with pytest.raises(ValueError, match="two number columns"):
            run_node(registry, "flograph.ml.correlation_matrix", {},
                     table=houses[["city", "size"]])


class TestMlModelling:
    @pytest.fixture(autouse=True)
    def _sklearn(self):
        pytest.importorskip("sklearn")

    def test_train_predict_evaluate_regression(self, registry, houses):
        trained = run_node(registry, "flograph.ml.train_model", {
            "target_column": "price", "feature_columns": "size, rooms",
            "algorithm": "linear"}, table=houses)
        metrics = trained["metrics"].set_index("metric")["value"]
        assert metrics["R2"] > 0.95
        assert trained["importances"]["feature"].iloc[0] in ("size", "rooms")
        pred = run_node(registry, "flograph.ml.predict", {"round": 1},
                        model=trained["model"], table=houses.head(5))
        assert pred["table"]["prediction"].tolist() == \
            pred["predictions"].tolist()
        assert pred["probabilities"].empty
        pytest.importorskip("plotly")
        ev = run_node(registry, "flograph.ml.model_evaluation", {
            "actual_column": "price"}, table=pred["table"])
        names = ev["metrics"]["metric"].tolist()
        assert names == ["MAE", "MSE", "RMSE", "R2"]

    def test_classification_with_probabilities(self, registry, houses):
        trained = run_node(registry, "flograph.ml.train_model", {
            "target_column": "city", "feature_columns": "size, rooms",
            "trees": 10}, table=houses)
        assert hasattr(trained["model"], "classes_")
        pred = run_node(registry, "flograph.ml.predict", {"probability": True},
                        model=trained["model"], table=houses)
        probs = pred["probabilities"]
        assert list(probs.columns) == ["p_Hull", "p_Leeds", "p_York"]
        assert "p_York" in pred["table"].columns
        pytest.importorskip("plotly")
        ev = run_node(registry, "flograph.ml.model_evaluation",
                      {"normalize": True}, actual=houses["city"],
                      predicted=pred["predictions"])
        assert ev["metrics"]["metric"].tolist()[0] == "accuracy"
        counts = ev["counts"].set_index("actual")
        assert counts.sum(axis=1).round(6).eq(1).all()
        assert ev["figure"].data[0].type == "heatmap"

    def test_train_model_errors(self, registry, houses):
        t = "flograph.ml.train_model"
        with pytest.raises(ValueError, match="aren't numbers"):
            run_node(registry, t, {"target_column": "price",
                                   "feature_columns": "city"}, table=houses)
        with pytest.raises(ValueError, match="isn't a regression"):
            run_node(registry, t, {"target_column": "price",
                                   "algorithm": "logistic"}, table=houses)
        gappy = houses.copy()
        gappy.loc[3, "size"] = None
        with pytest.raises(ValueError, match="missing values"):
            run_node(registry, t, {"target_column": "price"}, table=gappy)
        trained = run_node(registry, t, {"target_column": "price",
                                         "algorithm": "ridge"}, table=houses)
        with pytest.raises(ValueError, match="lacks columns"):
            run_node(registry, "flograph.ml.predict", {},
                     model=trained["model"], table=houses[["size"]])

    def test_cross_validation(self, registry, houses):
        t = "flograph.ml.cross_validation"
        out = run_node(registry, t, {"target_column": "price",
                                     "feature_columns": "size, rooms",
                                     "algorithm": "ridge", "folds": 4},
                       table=houses)
        assert out["scores"]["fold"].tolist() == [1, 2, 3, 4]
        assert out["summary"]["metric"].iloc[0] == "R2"
        assert out["summary"]["mean"].iloc[0] > 0.9
        cls = run_node(registry, t, {"target_column": "dear", "folds": 3,
                                     "algorithm": "logistic",
                                     "feature_columns": "size, rooms",
                                     "scoring": "F1"}, table=houses)
        assert cls["summary"]["metric"].iloc[0] == "F1"
        with pytest.raises(ValueError, match="isn't a regression score"):
            run_node(registry, t, {"target_column": "price",
                                   "scoring": "accuracy"}, table=houses)

    def test_kmeans(self, registry):
        pytest.importorskip("plotly")
        df = pd.DataFrame({"x": [0, 0.1, 0.2, 10, 10.1, 10.2],
                           "y": [0, 0.1, 0.0, 5, 5.1, 5.0]})
        out = run_node(registry, "flograph.ml.kmeans_clustering",
                       {"k": 2}, table=df)
        labels = out["clusters"].tolist()
        assert len(set(labels[:3])) == 1 and len(set(labels[3:])) == 1
        assert labels[0] != labels[3]
        centers = out["centers"].sort_values("x")
        assert centers["x"].round(1).tolist() == [0.1, 10.1]
        assert centers["rows"].tolist() == [3, 3]
        assert [t.name for t in out["figure"].data] == \
            ["cluster 0 (3)", "cluster 1 (3)"]
        with pytest.raises(ValueError, match="can't make"):
            run_node(registry, "flograph.ml.kmeans_clustering", {"k": 9},
                     table=df)

    def test_outliers(self, registry):
        df = pd.DataFrame({"v": [10, 11, 9, 10, 12, 11, 500.0],
                           "w": [1, 1, 1, 1, 1, 1, 1]})
        t = "flograph.ml.outlier_detection"
        out = run_node(registry, t, {}, table=df)
        assert out["flags"].tolist() == [False] * 6 + [True]
        assert out["cleaned"]["outlier"].iloc[-1]
        dropped = run_node(registry, t, {"action": "drop"}, table=df)
        assert len(dropped["cleaned"]) == 6
        clipped = run_node(registry, t, {"action": "clip"}, table=df)
        assert clipped["cleaned"]["v"].max() < 20
        z = run_node(registry, t, {"method": "z-score", "threshold": 2},
                     table=df)
        assert z["flags"].sum() == 1
        forest = run_node(registry, t, {"method": "isolation forest",
                                        "contamination": 0.15}, table=df)
        assert forest["flags"].iloc[-1]
        with pytest.raises(ValueError, match="no range to clip"):
            run_node(registry, t, {"method": "isolation forest",
                                   "action": "clip"}, table=df)


class TestTopBottomRules:
    """Best & Worst as Show Table rules: `units top 5 => row green`."""

    @pytest.fixture
    def sales(self):
        return pd.DataFrame({"sku": list("abcdefghij"),
                             "units": [5, 90, 40, 70, 10, 90, 1, 60, 30, 20]})

    def test_parse(self):
        from flograph.core.table_format import parse_rules
        top, bottom, share, named = parse_rules(
            "units top 3 => row green\nunits bottom 2 => bg red\n"
            "units top 10% => bold\nsku if units top 1 => icon ★ amber")
        assert (top.op, top.value, top.scope) == ("top", 3, "row")
        assert (bottom.op, bottom.value) == ("bottom", 2)
        assert share.value == "10%"
        assert (named.source, named.op) == ("units", "top")
        with pytest.raises(ValueError, match="count like 5"):
            parse_rules("units top lots => bg red")

    def test_ties_and_share(self, sales):
        from flograph.core.table_format import (
            column_stats, evaluate_column, parse_rules)
        rule, = parse_rules("units top 2 => bg green")
        styles = evaluate_column(sales["units"], [rule],
                                 column_stats(sales["units"]))
        # two 90s share first place, so top 2 is exactly those two
        assert [i for i, s in enumerate(styles) if s] == [1, 5]
        rule, = parse_rules("units bottom 20% => bg red")
        styles = evaluate_column(sales["units"], [rule],
                                 column_stats(sales["units"]))
        assert [i for i, s in enumerate(styles) if s] == [0, 6]

    def test_a_block_is_judged_against_the_whole_column(self, sales):
        from flograph.core.table_format import (
            column_stats, evaluate_column, evaluate_rows, parse_rules)
        block = sales.iloc[6:]          # 1, 60, 30, 20 — no 90 in sight
        cell, = parse_rules("units top 2 => bg green")
        styles = evaluate_column(block["units"], [cell],
                                 column_stats(sales["units"]), frame=block,
                                 pool_frame=sales)
        assert not any(styles)
        row, = parse_rules("units bottom 1 => row red")
        marked = evaluate_rows(block, [row], pool_frame=sales)
        assert [s is not None for s in marked] == [True, False, False, False]
        # without the whole table the block would rank itself
        alone = evaluate_column(block["units"], [cell],
                                column_stats(block["units"]))
        assert [i for i, s in enumerate(alone) if s] == [1, 2]


class TestStatusCards:
    GREEN, RED, AMBER = "#10b981", "#ef4444", "#f59e0b"

    def test_sparkline_card(self, registry):
        df = pd.DataFrame({"day": [3, 1, 2], "sales": [30.0, 10.0, 20.0]})
        out = run_node(registry, "flograph.viz.sparkline_card", {
            "column": "sales", "aggregation": "Last", "order_by": "day",
            "format": ",.0f"}, table=df)
        assert out["value"] == 30.0
        assert out["trend"] == pytest.approx(2.0)   # 10 -> 30
        assert out["html"].startswith("<!doctype html>")
        assert "<svg" in out["html"] and "200.0%" in out["html"]
        assert self.GREEN in out["html"]
        costs = run_node(registry, "flograph.viz.sparkline_card", {
            "column": "sales", "order_by": "day",
            "higher_is_better": False}, table=df)
        assert costs["value"] == 60 and self.RED in costs["html"]
        with pytest.raises(ValueError, match="not in table"):
            run_node(registry, "flograph.viz.sparkline_card",
                     {"column": "nope"}, table=df)

    def test_goal_card_change_and_progress(self, registry):
        t = "flograph.viz.goal_card"
        up = run_node(registry, t, {"comparison_label": "last year"},
                      value=112, comparison=pd.DataFrame({"v": [100]}))
        assert (up["delta"], up["pct"]) == (12, pytest.approx(0.12))
        assert "▲" in up["html"] and "12.0%" in up["html"]
        assert self.GREEN in up["html"]
        prog = run_node(registry, t, {"mode": "progress", "target": 100.0},
                        value=78)
        assert prog["pct"] == pytest.approx(0.78) and self.RED in prog["html"]
        near = run_node(registry, t, {"mode": "progress", "target": 100.0},
                        value=85)
        assert self.AMBER in near["html"]
        budget = run_node(registry, t, {"mode": "progress", "target": 100.0,
                                        "higher_is_better": False}, value=60)
        assert self.GREEN in budget["html"]
        with pytest.raises(ValueError, match="isn't 0"):
            run_node(registry, t, {"mode": "progress"}, value=5)
        with pytest.raises(ValueError, match="single number"):
            run_node(registry, t, {}, value=pd.Series([1, 2]))

    def test_status_light(self, registry):
        t = "flograph.viz.status_light"
        assert run_node(registry, t, {}, value=10)["status"] == "green"
        assert run_node(registry, t, {}, value=50)["status"] == "amber"
        assert run_node(registry, t, {}, value=95)["status"] == "red"
        runway = {"direction": "lower is worse", "amber": 90.0, "red": 30.0}
        assert run_node(registry, t, runway, value=20)["status"] == "red"
        assert run_node(registry, t, runway, value=200)["status"] == "green"
        with pytest.raises(ValueError, match="swap them"):
            run_node(registry, t, {"amber": 90.0, "red": 10.0}, value=1)

    def test_alert_list(self, registry):
        t = "flograph.viz.alert_list"
        df = pd.DataFrame({"inv": ["A1", "B2", "C3"], "days": [45, 31, None],
                           "amount": [1200.5, 80.0, 5.0]})
        out = run_node(registry, t, {
            "message": "{inv} is {days} days overdue ({amount:$,.0f})",
            "max_rows": 2}, table=df)
        assert out["count"] == 3
        assert "A1 is 45.0 days overdue ($1,200)" in out["html"]
        assert "and 1 more" in out["html"]
        clear = run_node(registry, t, {}, table=df.iloc[0:0])
        assert clear["count"] == 0 and "All clear" in clear["html"]
        plain = run_node(registry, t, {"message": "{inv}: {nope}"}, table=df)
        assert "<li>A1: </li>" in plain["html"]   # unknown column: blank

    def test_plain_english_summary(self, registry):
        t = "flograph.viz.plain_english_summary"
        out = run_node(registry, t, {
            "template": "Revenue {value}, {direction} {change} on last month",
            "value_format": "$,.0f"}, value=1090, previous=1000)
        assert out["text"] == "Revenue $1,090, up 9% on last month"
        assert self.GREEN in out["html"]
        flat = run_node(registry, t, {"flat_band": 0.05,
                                      "template": "{direction} {delta}"},
                        value=1010, previous=1000)
        assert flat["text"] == "flat +10"
        down = run_node(registry, t, {"higher_is_better": False},
                        value=90, previous=100)
        assert "down 10%" in down["text"] and self.GREEN in down["html"]
        alone = run_node(registry, t, {"template": "Now {value}"}, value=5)
        assert alone["text"] == "Now 5"

    def test_as_of_stamp(self, registry):
        import datetime as dt
        t = "flograph.util.as_of_stamp"
        out = run_node(registry, t, {}, trigger=pd.DataFrame())
        assert out["text"].startswith("As of ") and out["text"].endswith("today")
        when = dt.datetime.fromisoformat(out["timestamp"])
        assert abs((dt.datetime.now() - when).total_seconds()) < 60
        assert "' yesterday'" in out["html"]          # the card's own clock
        dated = run_node(registry, t, {"format": "%d %b %Y %H:%M",
                                       "stale_minutes": 30})
        assert not dated["text"].endswith("today")
        assert "lim=1800000" in dated["html"]


class TestFileNodes:
    def test_multi_sheet_excel(self, registry, tmp_path):
        openpyxl = pytest.importorskip("openpyxl")
        target = tmp_path / "out" / "pack.xlsx"
        a = pd.DataFrame({"x": [1, 2]})
        b = pd.DataFrame({"long column name": ["a" * 30]})
        c = pd.DataFrame({"z": [True]})
        out = run_node(registry, "flograph.io.write_excel_sheets", {
            "path": str(target), "add_summary": True,
            "sheet_names": "P&L\nBy: region / area"},
            sheet1=a, sheet2=b, in3=c)
        assert out["path"] == str(target)
        book = openpyxl.load_workbook(target)
        assert book.sheetnames == ["Summary", "P&L", "By region  area",
                                   "Sheet3"]
        sheet = book["By region  area"]
        assert sheet["A1"].font.bold and sheet.freeze_panes == "A2"
        assert sheet.column_dimensions["A"].width >= 30
        summary = pd.read_excel(target, sheet_name="Summary")
        assert summary["rows"].tolist() == [2, 1, 1]
        with pytest.raises(ValueError, match=".xlsx"):
            run_node(registry, "flograph.io.write_excel_sheets",
                     {"path": str(tmp_path / "x.csv")}, sheet1=a)

    def test_file_operations(self, registry, tmp_path):
        t = "flograph.automation.file_operations"
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        for name in ("a.csv", "b.csv", "c.txt"):
            (inbox / name).write_text(name)
        archive = tmp_path / "archive"

        dry = run_node(registry, t, {"operation": "move", "dry_run": True,
                                     "source": str(inbox / "*.csv"),
                                     "destination": str(archive)})
        assert dry["count"] == 2 and not archive.exists()

        moved = run_node(registry, t, {"operation": "move",
                                       "source": str(inbox / "*.csv"),
                                       "destination": str(archive)})
        assert sorted(p.name for p in archive.iterdir()) == ["a.csv", "b.csv"]
        assert moved["bytes"] == 10

        with pytest.raises(FileExistsError, match="Overwrite"):
            run_node(registry, t, {"operation": "copy",
                                   "destination": str(archive / "a.csv")},
                     source=str(inbox / "c.txt"))
        run_node(registry, t, {"operation": "rename", "destination": "d.txt"},
                 source=str(inbox / "c.txt"))
        assert (inbox / "d.txt").exists()

        zipped = run_node(registry, t, {"operation": "zip",
                                        "destination": str(tmp_path / "old")},
                          source=[str(archive)])
        import zipfile
        names = zipfile.ZipFile(zipped["path"]).namelist()
        assert sorted(names) == ["archive/a.csv", "archive/b.csv"]

        with pytest.raises(IsADirectoryError, match="Delete folders"):
            run_node(registry, t, {"operation": "delete"},
                     source=str(archive))
        gone = run_node(registry, t, {"operation": "delete",
                                      "delete_folders": True},
                        source=pd.DataFrame({"path": [str(archive)]}))
        assert gone["count"] == 1 and not archive.exists()
        with pytest.raises(FileNotFoundError):
            run_node(registry, t, {"operation": "delete"},
                     source=str(tmp_path / "nope.csv"))

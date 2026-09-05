"""The three `Read … (Folder)` nodes and the folder service behind them.

Their whole job is turning a directory into one table, so the interesting
cases are the directory ones: which files get picked up, in what order, and
whether swapping the engine or reading them in parallel changes the answer.
"""
import pandas as pd
import pytest

from flograph import folders
from flograph.core import compile_run
from tests.conftest import FakeContext

EXCEL_FOLDER = "flograph.io.read_excel_folder"
CSV_FOLDER = "flograph.io.read_csv_folder"
PARQUET_FOLDER = "flograph.io.read_parquet_folder"
CSV_DICT = "flograph.io.read_csv_dict"


def run_folder(registry, type_id, params=None, path_input=None):
    spec = registry.get(type_id)
    defaults = spec.default_params()
    defaults.update(params or {})
    run = compile_run(spec.source, f"test-{type_id}")
    ctx = FakeContext(params=defaults)
    return run(ctx, path_input=path_input), "\n".join(ctx.logs)


@pytest.fixture
def parts():
    """Three frames that stack to nine rows, distinguishable by value."""
    return [pd.DataFrame({"region": ["n", "s", "e"], "units": [i, i + 1, i + 2]})
            for i in (0, 10, 20)]


@pytest.fixture
def csv_dir(tmp_path, parts):
    for name, frame in zip(["a.csv", "b.csv", "c.csv"], parts):
        frame.to_csv(tmp_path / name, index=False)
    return tmp_path


@pytest.fixture
def excel_dir(tmp_path, parts):
    pytest.importorskip("openpyxl")
    for name, frame in zip(["a.xlsx", "b.xlsx", "c.xlsx"], parts):
        frame.to_excel(tmp_path / name, index=False)
    return tmp_path


@pytest.fixture
def nested_excel_dir(tmp_path, parts):
    """One workbook at the top and two more down two different branches."""
    pytest.importorskip("openpyxl")
    for rel, frame in zip(["a.xlsx", "2023/q1/b.xlsx", "archive/c.xlsx"], parts):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_excel(target, index=False)
    return tmp_path


@pytest.fixture
def nested_csv_dir(tmp_path):
    """Same shape as `nested_excel_dir`, cheap enough for service tests."""
    for rel in ["a.csv", "2023/q1/b.csv", "archive/c.csv"]:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x\n1\n")
    return tmp_path


@pytest.fixture
def nested_csv_frames(tmp_path, parts):
    """`nested_csv_dir`'s shape, but with rows in it the readers can stack."""
    for rel, frame in zip(["a.csv", "2023/q1/b.csv", "archive/c.csv"], parts):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(target, index=False)
    return tmp_path


@pytest.fixture
def nested_parquet_dir(tmp_path, parts):
    """A partition layout, the shape Parquet folders usually arrive in."""
    pytest.importorskip("pyarrow")
    for rel, frame in zip(["part-0.parquet", "year=2023/part-1.parquet",
                           "_temporary/part-2.parquet"], parts):
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(target, index=False)
    return tmp_path


@pytest.fixture
def parquet_dir(tmp_path, parts):
    pytest.importorskip("pyarrow")
    for name, frame in zip(["a.parquet", "b.parquet", "c.parquet"], parts):
        frame.to_parquet(tmp_path / name, index=False)
    return tmp_path


class TestFolderService:
    def test_files_come_back_sorted(self, tmp_path):
        for name in ["c.csv", "a.csv", "b.csv"]:
            (tmp_path / name).write_text("x\n1\n")
        found = folders.discover(str(tmp_path), (".csv",))
        assert [f.rsplit("/", 1)[-1] for f in found] == ["a.csv", "b.csv", "c.csv"]

    def test_compression_suffix_is_seen_through(self, tmp_path):
        (tmp_path / "a.csv.gz").write_bytes(b"")
        (tmp_path / "b.csv").write_text("")
        assert len(folders.discover(str(tmp_path), (".csv",))) == 2

    def test_excel_lock_files_are_skipped(self, tmp_path):
        (tmp_path / "real.xlsx").write_bytes(b"")
        (tmp_path / "~$real.xlsx").write_bytes(b"")
        found = folders.discover(str(tmp_path), (".xlsx",))
        assert [f.rsplit("/", 1)[-1] for f in found] == ["real.xlsx"]

    def test_include_then_exclude(self, tmp_path):
        for name in ["sales_1.csv", "sales_tmp.csv", "other.csv"]:
            (tmp_path / name).write_text("")
        found = folders.discover(str(tmp_path), (".csv",),
                                 include="sales_*", exclude="*tmp*")
        assert [f.rsplit("/", 1)[-1] for f in found] == ["sales_1.csv"]

    def test_a_missing_folder_says_so(self, tmp_path):
        with pytest.raises(ValueError, match="is not a folder"):
            folders.discover(str(tmp_path / "nope"), (".csv",))

    def test_gil_bound_engines_are_not_parallelised_by_auto(self):
        assert folders.worker_count(0, "openpyxl", 8) == 1
        assert folders.worker_count(0, "fastparquet", 8) == 1
        assert folders.worker_count(0, "calamine", 8) > 1

    def test_an_explicit_count_overrides_the_engine(self):
        assert folders.worker_count(3, "openpyxl", 8) == 3

    def test_never_more_workers_than_files(self):
        assert folders.worker_count(16, "polars", 2) == 2

    @pytest.mark.parametrize("spec,expected", [
        ("A:A", "A"), ("A:C", "A:C"), ("A:A,F", "A,F"), ("a:a", "a"),
    ])
    def test_degenerate_letter_ranges_collapse(self, spec, expected):
        assert folders.normalise_letter_range(spec) == expected

    def test_a_flat_read_stops_at_the_top_level(self, nested_csv_dir):
        found = folders.discover(str(nested_csv_dir), (".csv",))
        assert [f.rsplit("/", 1)[-1] for f in found] == ["a.csv"]

    def test_recursive_finds_every_branch_in_path_order(self, nested_csv_dir):
        found = folders.discover(str(nested_csv_dir), (".csv",), recursive=True)
        rel = [f[len(str(nested_csv_dir)) + 1:] for f in found]
        assert rel == ["2023/q1/b.csv", "a.csv", "archive/c.csv"]

    def test_excluding_a_folder_takes_its_subtree_with_it(self, nested_csv_dir):
        found = folders.discover(str(nested_csv_dir), (".csv",), recursive=True,
                                 exclude_dirs="2023*")
        rel = [f[len(str(nested_csv_dir)) + 1:] for f in found]
        assert rel == ["a.csv", "archive/c.csv"]

    def test_including_folders_drops_the_root_too(self, nested_csv_dir):
        found = folders.discover(str(nested_csv_dir), (".csv",), recursive=True,
                                 include_dirs="2023*")
        rel = [f[len(str(nested_csv_dir)) + 1:] for f in found]
        assert rel == ["2023/q1/b.csv"]

    def test_a_folder_pattern_also_matches_a_bare_name(self, nested_csv_dir):
        found = folders.discover(str(nested_csv_dir), (".csv",), recursive=True,
                                 include_dirs="q1")
        rel = [f[len(str(nested_csv_dir)) + 1:] for f in found]
        assert rel == ["2023/q1/b.csv"]

    def test_a_file_pattern_with_a_slash_is_about_the_path(self, nested_csv_dir):
        found = folders.discover(str(nested_csv_dir), (".csv",), recursive=True,
                                 include="2023/*")
        rel = [f[len(str(nested_csv_dir)) + 1:] for f in found]
        assert rel == ["2023/q1/b.csv"]

    def test_a_file_pattern_without_one_is_still_about_the_name(self, nested_csv_dir):
        found = folders.discover(str(nested_csv_dir), (".csv",), recursive=True,
                                 include="b.csv")
        rel = [f[len(str(nested_csv_dir)) + 1:] for f in found]
        assert rel == ["2023/q1/b.csv"]

    def test_relative_folder_names_the_branch(self, nested_csv_dir):
        root = str(nested_csv_dir)
        assert folders.relative_folder(f"{root}/a.csv", root) == "."
        assert folders.relative_folder(f"{root}/2023/q1/b.csv", root) == "2023/q1"


class TestReadCsvFolder:
    def test_stacks_every_file_in_name_order(self, registry, csv_dir):
        out, log = run_folder(registry, CSV_FOLDER, {"path": str(csv_dir)})
        assert len(out) == 9
        assert list(out["units"]) == [0, 1, 2, 10, 11, 12, 20, 21, 22]
        assert "3 file(s)" in log

    def test_source_file_column(self, registry, csv_dir):
        out, _ = run_folder(registry, CSV_FOLDER,
                            {"path": str(csv_dir), "add_source_file": True})
        assert list(out.columns)[0] == "source_file"
        assert set(out["source_file"]) == {"a.csv", "b.csv", "c.csv"}

    def test_include_and_exclude(self, registry, csv_dir):
        out, _ = run_folder(registry, CSV_FOLDER,
                            {"path": str(csv_dir), "exclude_pattern": "c.csv"})
        assert len(out) == 6

    def test_subfolders_are_left_alone_unless_asked_for(self, registry,
                                                       nested_csv_frames):
        out, _ = run_folder(registry, CSV_FOLDER,
                            {"path": str(nested_csv_frames)})
        assert len(out) == 3

    def test_recursive_stacks_the_whole_tree(self, registry, nested_csv_frames):
        out, log = run_folder(registry, CSV_FOLDER,
                              {"path": str(nested_csv_frames), "recursive": True})
        assert len(out) == 9
        assert "subfolders included" in log

    def test_folder_column_and_file_column_sit_in_a_fixed_order(
            self, registry, nested_csv_frames):
        out, _ = run_folder(registry, CSV_FOLDER,
                            {"path": str(nested_csv_frames), "recursive": True,
                             "add_folder_column": True, "add_source_file": True})
        assert list(out.columns[:2]) == ["source_folder", "source_file"]
        assert set(out["source_folder"]) == {".", "2023/q1", "archive"}

    def test_folder_patterns_narrow_the_walk(self, registry, nested_csv_frames):
        out, _ = run_folder(registry, CSV_FOLDER,
                            {"path": str(nested_csv_frames), "recursive": True,
                             "exclude_dirs": "archive"})
        assert len(out) == 6

    def test_folder_patterns_are_inert_on_a_flat_read(self, registry,
                                                     nested_csv_frames):
        out, _ = run_folder(registry, CSV_FOLDER,
                            {"path": str(nested_csv_frames),
                             "include_dirs": "2023*", "exclude_dirs": "archive"})
        assert len(out) == 3

    def test_filters_matching_nothing_say_why(self, registry, csv_dir):
        with pytest.raises(ValueError, match="include/exclude"):
            run_folder(registry, CSV_FOLDER,
                       {"path": str(csv_dir), "include_pattern": "zzz*"})

    def test_empty_folder_says_what_it_wanted(self, registry, tmp_path):
        with pytest.raises(ValueError, match=r"\.csv"):
            run_folder(registry, CSV_FOLDER, {"path": str(tmp_path)})

    def test_requires_a_folder(self, registry):
        with pytest.raises(ValueError, match="no folder selected"):
            run_folder(registry, CSV_FOLDER, {})

    def test_path_input_overrides_the_param(self, registry, csv_dir):
        out, _ = run_folder(registry, CSV_FOLDER, {"path": ""},
                            path_input=str(csv_dir))
        assert len(out) == 9

    def test_blank_path_input_falls_back_to_the_param(self, registry, csv_dir):
        out, _ = run_folder(registry, CSV_FOLDER, {"path": str(csv_dir)},
                            path_input="   ")
        assert len(out) == 9

    def test_gzipped_files_are_read_too(self, registry, tmp_path, parts):
        parts[0].to_csv(tmp_path / "a.csv", index=False)
        parts[1].to_csv(tmp_path / "b.csv.gz", index=False, compression="gzip")
        out, _ = run_folder(registry, CSV_FOLDER, {"path": str(tmp_path)})
        assert len(out) == 6

    def test_nrows_caps_each_file_not_the_stack(self, registry, csv_dir):
        """A row cap on a folder read is a sample of every file. Capping the
        stack instead gave the whole of the first file and none of the rest,
        which is the one answer nobody wants from a folder of exports."""
        out, _ = run_folder(registry, CSV_FOLDER,
                            {"path": str(csv_dir), "nrows": 2})
        assert list(out["units"]) == [0, 1, 10, 11, 20, 21]

    def test_a_cap_above_the_file_size_changes_nothing(self, registry, csv_dir):
        out, _ = run_folder(registry, CSV_FOLDER,
                            {"path": str(csv_dir), "nrows": 50})
        assert len(out) == 9

    def test_both_engines_cap_the_same_way(self, registry, csv_dir):
        pytest.importorskip("polars")
        pandas_out, _ = run_folder(registry, CSV_FOLDER,
                                   {"path": str(csv_dir), "nrows": 2})
        polars_out, _ = run_folder(registry, CSV_FOLDER,
                                   {"path": str(csv_dir), "nrows": 2,
                                    "engine": "polars"})
        assert list(polars_out["units"]) == list(pandas_out["units"])

    def test_dtypes_reach_the_parser(self, registry, tmp_path):
        (tmp_path / "codes.csv").write_text("code,n\n01234,1\n")
        out, _ = run_folder(registry, CSV_FOLDER,
                            {"path": str(tmp_path), "dtypes": "code = string"})
        assert list(out["code"]) == ["01234"]

    def test_polars_matches_the_pandas_result(self, registry, csv_dir):
        pytest.importorskip("polars")
        pandas_out, _ = run_folder(registry, CSV_FOLDER, {"path": str(csv_dir)})
        polars_out, log = run_folder(registry, CSV_FOLDER,
                                     {"path": str(csv_dir), "engine": "polars"})
        assert "via polars" in log
        pd.testing.assert_frame_equal(pandas_out, polars_out)

    def test_polars_refuses_what_it_cannot_do(self, registry, csv_dir):
        pytest.importorskip("polars")
        with pytest.raises(ValueError, match="Thousands mark"):
            run_folder(registry, CSV_FOLDER,
                       {"path": str(csv_dir), "engine": "polars",
                        "thousands": ","})

    def test_parallel_reads_give_the_same_table(self, registry, csv_dir):
        one, _ = run_folder(registry, CSV_FOLDER,
                            {"path": str(csv_dir), "parallel_files": 1})
        many, log = run_folder(registry, CSV_FOLDER,
                               {"path": str(csv_dir), "parallel_files": 3})
        assert "3 at a time" in log
        pd.testing.assert_frame_equal(one, many)


class TestReadExcelFolder:
    def test_stacks_every_workbook(self, registry, excel_dir):
        out, _ = run_folder(registry, EXCEL_FOLDER, {"path": str(excel_dir)})
        assert len(out) == 9
        assert list(out["units"]) == [0, 1, 2, 10, 11, 12, 20, 21, 22]

    @pytest.mark.parametrize("engine", ["openpyxl", "calamine", "polars"])
    def test_every_engine_reads_the_same_folder(self, registry, excel_dir, engine):
        pytest.importorskip({"openpyxl": "openpyxl", "calamine": "python_calamine",
                             "polars": "polars"}[engine])
        if engine == "polars":
            pytest.importorskip("fastexcel")
        out, log = run_folder(registry, EXCEL_FOLDER,
                              {"path": str(excel_dir), "engine": engine})
        assert len(out) == 9
        assert engine in log

    def test_auto_skips_an_engine_whose_package_is_missing(self, registry,
                                                           excel_dir,
                                                           monkeypatch):
        """Probing pandas' shim instead of the real package reported every
        engine as installed — `pandas.io.excel._calamine` imports fine
        without python-calamine — so auto chose calamine on a machine that
        did not have it and failed halfway through the read."""
        pytest.importorskip("openpyxl")
        import importlib.util

        real = importlib.util.find_spec

        def hide_the_fast_ones(name, *args, **kwargs):
            if name in ("python_calamine", "polars"):
                return None
            return real(name, *args, **kwargs)

        monkeypatch.setattr(importlib.util, "find_spec", hide_the_fast_ones)
        out, log = run_folder(registry, EXCEL_FOLDER, {"path": str(excel_dir)})
        assert len(out) == 9
        assert "openpyxl" in log      # fell back rather than picking calamine
        assert "calamine" not in log

    def test_an_uninstalled_engine_fails_before_reading(self, registry, excel_dir):
        with pytest.raises(RuntimeError, match="Manage Packages"):
            run_folder(registry, EXCEL_FOLDER,
                       {"path": str(excel_dir), "engine": "pyxlsb"})

    def test_all_sheets_stack_with_both_columns(self, registry, tmp_path, parts):
        pytest.importorskip("openpyxl")
        with pd.ExcelWriter(tmp_path / "book.xlsx") as writer:
            parts[0].to_excel(writer, sheet_name="one", index=False)
            parts[1].to_excel(writer, sheet_name="two", index=False)
        out, _ = run_folder(registry, EXCEL_FOLDER,
                            {"path": str(tmp_path), "sheet_name": "*",
                             "add_source_file": True})
        assert list(out.columns[:2]) == ["sheet", "source_file"]
        assert set(out["sheet"]) == {"one", "two"}
        assert len(out) == 6

    def test_nrows_caps_each_workbook(self, registry, excel_dir):
        out, _ = run_folder(registry, EXCEL_FOLDER,
                            {"path": str(excel_dir), "nrows": 2})
        assert list(out["units"]) == [0, 1, 10, 11, 20, 21]

    def test_nrows_caps_each_sheet_of_a_workbook(self, registry, tmp_path,
                                                 parts):
        """With Sheet set to `*` the unit is the sheet, not the workbook —
        it is what becomes a table here, and what the read is limited by."""
        pytest.importorskip("openpyxl")
        with pd.ExcelWriter(tmp_path / "book.xlsx") as writer:
            parts[0].to_excel(writer, sheet_name="one", index=False)
            parts[1].to_excel(writer, sheet_name="two", index=False)
        out, _ = run_folder(registry, EXCEL_FOLDER,
                            {"path": str(tmp_path), "sheet_name": "*",
                             "nrows": 2})
        assert list(out["units"]) == [0, 1, 10, 11]

    def test_lock_files_are_not_read(self, registry, excel_dir, parts):
        pytest.importorskip("openpyxl")
        parts[0].to_excel(excel_dir / "~$a.xlsx", index=False)
        out, _ = run_folder(registry, EXCEL_FOLDER, {"path": str(excel_dir)})
        assert len(out) == 9   # not 12

    @pytest.mark.parametrize("engine", ["calamine", "polars"])
    def test_header_row_picks_a_later_row(self, registry, tmp_path, engine):
        pytest.importorskip({"calamine": "python_calamine",
                             "polars": "polars"}[engine])
        if engine == "polars":
            pytest.importorskip("fastexcel")
        pd.DataFrame([["junk", "junk"], ["region", "units"], ["n", 5]]).to_excel(
            tmp_path / "h.xlsx", index=False, header=False)
        out, _ = run_folder(registry, EXCEL_FOLDER,
                            {"path": str(tmp_path), "engine": engine,
                             "header": False, "header_row": "1"})
        assert list(out.columns) == ["region", "units"]
        assert len(out) == 1

    def test_a_bad_header_row_is_rejected(self, registry, excel_dir):
        with pytest.raises(ValueError, match="0-based row number"):
            run_folder(registry, EXCEL_FOLDER,
                       {"path": str(excel_dir), "header": False,
                        "header_row": "abc"})

    def test_subfolders_are_left_alone_unless_asked_for(self, registry,
                                                       nested_excel_dir):
        out, _ = run_folder(registry, EXCEL_FOLDER,
                            {"path": str(nested_excel_dir)})
        assert len(out) == 3

    def test_recursive_stacks_the_whole_tree(self, registry, nested_excel_dir):
        out, log = run_folder(registry, EXCEL_FOLDER,
                              {"path": str(nested_excel_dir), "recursive": True})
        assert len(out) == 9
        assert "subfolders included" in log

    def test_folder_column_says_which_branch_each_row_came_from(
            self, registry, nested_excel_dir):
        out, _ = run_folder(registry, EXCEL_FOLDER,
                            {"path": str(nested_excel_dir), "recursive": True,
                             "add_folder_column": True})
        assert list(out.columns)[0] == "source_folder"
        assert set(out["source_folder"]) == {".", "2023/q1", "archive"}

    def test_folder_and_file_columns_sit_in_a_fixed_order(
            self, registry, nested_excel_dir):
        out, _ = run_folder(registry, EXCEL_FOLDER,
                            {"path": str(nested_excel_dir), "recursive": True,
                             "sheet_name": "*", "add_folder_column": True,
                             "add_source_file": True})
        assert list(out.columns[:3]) == ["sheet", "source_folder", "source_file"]

    def test_excluding_a_folder_skips_its_workbooks(self, registry,
                                                    nested_excel_dir):
        out, _ = run_folder(registry, EXCEL_FOLDER,
                            {"path": str(nested_excel_dir), "recursive": True,
                             "exclude_dirs": "archive"})
        assert len(out) == 6

    def test_including_folders_keeps_only_those(self, registry, nested_excel_dir):
        out, _ = run_folder(registry, EXCEL_FOLDER,
                            {"path": str(nested_excel_dir), "recursive": True,
                             "include_dirs": "2023*"})
        assert len(out) == 3

    def test_folder_patterns_are_inert_on_a_flat_read(self, registry,
                                                     nested_excel_dir):
        # left over from a recursive run, they must not empty a flat one
        out, _ = run_folder(registry, EXCEL_FOLDER,
                            {"path": str(nested_excel_dir),
                             "include_dirs": "2023*", "exclude_dirs": "archive"})
        assert len(out) == 3

    def test_folder_patterns_matching_nothing_say_why(self, registry,
                                                      nested_excel_dir):
        with pytest.raises(ValueError, match="include/exclude"):
            run_folder(registry, EXCEL_FOLDER,
                       {"path": str(nested_excel_dir), "recursive": True,
                        "include_dirs": "zzz*"})

    def test_polars_refuses_what_it_cannot_do(self, registry, excel_dir):
        pytest.importorskip("polars")
        pytest.importorskip("fastexcel")
        with pytest.raises(ValueError, match="Decimal mark"):
            run_folder(registry, EXCEL_FOLDER,
                       {"path": str(excel_dir), "engine": "polars",
                        "decimal": ","})


class TestReadParquetFolder:
    def test_stacks_every_part(self, registry, parquet_dir):
        out, _ = run_folder(registry, PARQUET_FOLDER, {"path": str(parquet_dir)})
        assert len(out) == 9
        assert list(out["units"]) == [0, 1, 2, 10, 11, 12, 20, 21, 22]

    def test_nrows_caps_each_part(self, registry, parquet_dir):
        """The path that had no cap at all once the total one went: pandas
        takes no row limit for Parquet, so the trim happens after the read."""
        out, _ = run_folder(registry, PARQUET_FOLDER,
                            {"path": str(parquet_dir), "nrows": 2})
        assert list(out["units"]) == [0, 1, 10, 11, 20, 21]

    def test_polars_caps_each_part_the_same_way(self, registry, parquet_dir):
        pytest.importorskip("polars")
        out, _ = run_folder(registry, PARQUET_FOLDER,
                            {"path": str(parquet_dir), "nrows": 2,
                             "engine": "polars"})
        assert list(out["units"]) == [0, 1, 10, 11, 20, 21]

    def test_source_file_keeps_partition_identity(self, registry, parquet_dir):
        out, _ = run_folder(registry, PARQUET_FOLDER,
                            {"path": str(parquet_dir), "add_source_file": True})
        assert set(out["source_file"]) == {"a.parquet", "b.parquet", "c.parquet"}

    def test_partitions_below_the_folder_need_asking_for(
            self, registry, nested_parquet_dir):
        out, _ = run_folder(registry, PARQUET_FOLDER,
                            {"path": str(nested_parquet_dir)})
        assert len(out) == 3
        out, _ = run_folder(registry, PARQUET_FOLDER,
                            {"path": str(nested_parquet_dir), "recursive": True})
        assert len(out) == 9

    def test_a_partition_folder_can_be_excluded_and_recorded(
            self, registry, nested_parquet_dir):
        out, _ = run_folder(registry, PARQUET_FOLDER,
                            {"path": str(nested_parquet_dir), "recursive": True,
                             "exclude_dirs": "_temporary",
                             "add_folder_column": True})
        assert len(out) == 6
        assert set(out["source_folder"]) == {".", "year=2023"}

    def test_columns_push_down(self, registry, parquet_dir):
        out, _ = run_folder(registry, PARQUET_FOLDER,
                            {"path": str(parquet_dir), "columns": "units"})
        assert list(out.columns) == ["units"]

    def test_row_filters_push_down(self, registry, parquet_dir):
        out, _ = run_folder(registry, PARQUET_FOLDER,
                            {"path": str(parquet_dir), "filters": "units >= 10"})
        assert out["units"].min() >= 10

    def test_a_malformed_filter_names_the_line(self, registry, parquet_dir):
        with pytest.raises(ValueError, match="row filters line 1"):
            run_folder(registry, PARQUET_FOLDER,
                       {"path": str(parquet_dir), "filters": "nonsense"})

    def test_polars_matches_pyarrow(self, registry, parquet_dir):
        pytest.importorskip("polars")
        pyarrow_out, _ = run_folder(registry, PARQUET_FOLDER,
                                    {"path": str(parquet_dir)})
        polars_out, log = run_folder(registry, PARQUET_FOLDER,
                                     {"path": str(parquet_dir), "engine": "polars"})
        assert "via polars" in log
        pd.testing.assert_frame_equal(pyarrow_out, polars_out)

    def test_polars_refuses_row_filters(self, registry, parquet_dir):
        pytest.importorskip("polars")
        with pytest.raises(ValueError, match="Row filters"):
            run_folder(registry, PARQUET_FOLDER,
                       {"path": str(parquet_dir), "engine": "polars",
                        "filters": "units >= 10"})

    def test_parallel_reads_give_the_same_table(self, registry, parquet_dir):
        one, _ = run_folder(registry, PARQUET_FOLDER,
                            {"path": str(parquet_dir), "parallel_files": 1})
        many, _ = run_folder(registry, PARQUET_FOLDER,
                             {"path": str(parquet_dir), "parallel_files": 3})
        pd.testing.assert_frame_equal(one, many)


def run_dict(registry, params=None, path_input=None):
    """The dict reader, unwrapped to the `tables` payload."""
    out, log = run_folder(registry, CSV_DICT, params, path_input)
    return out["tables"], log


def normalise(registry, type_id, result):
    """Put a run() result through the engine's port mapping.

    The helpers above call run() directly, which is the wrong altitude for
    the one question a dict-valued output raises — whether the engine reads
    the returned dict as the payload or as the port mapping.
    """
    from flograph.engine.worker import NodeRunnable

    spec = registry.get(type_id)
    runnable = NodeRunnable("test", spec.source, {}, {}, list(spec.outputs),
                            None, None)
    return runnable._normalize(result)


class TestReadCsvDict:
    def test_one_entry_per_file_keyed_by_name(self, registry, csv_dir, parts):
        tables, log = run_dict(registry, {"path": str(csv_dir)})
        assert list(tables) == ["a.csv", "b.csv", "c.csv"]
        for name, expected in zip(["a.csv", "b.csv", "c.csv"], parts):
            pd.testing.assert_frame_equal(tables[name], expected)
        assert "3 table(s), 9 rows in total" in log

    def test_frames_are_not_stacked(self, registry, csv_dir):
        """The whole point: three frames of three rows, not one of nine."""
        tables, _ = run_dict(registry, {"path": str(csv_dir)})
        assert [len(frame) for frame in tables.values()] == [3, 3, 3]

    def test_key_without_extension(self, registry, csv_dir):
        tables, _ = run_dict(registry, {"path": str(csv_dir),
                                        "key": "name without extension"})
        assert list(tables) == ["a", "b", "c"]

    def test_key_full_path(self, registry, csv_dir):
        tables, _ = run_dict(registry, {"path": str(csv_dir), "key": "full path"})
        assert list(tables) == [str(csv_dir / n) for n in ["a.csv", "b.csv", "c.csv"]]

    def test_colliding_stems_are_reported_not_silently_dropped(self, registry,
                                                               tmp_path, parts):
        parts[0].to_csv(tmp_path / "sales.csv", index=False)
        parts[1].to_csv(tmp_path / "sales.tsv", index=False)
        with pytest.raises(ValueError, match="share a key"):
            run_dict(registry, {"path": str(tmp_path),
                                "key": "name without extension"})

    def test_colliding_stems_are_fine_when_keyed_by_name(self, registry, tmp_path,
                                                         parts):
        parts[0].to_csv(tmp_path / "sales.csv", index=False)
        parts[1].to_csv(tmp_path / "sales.tsv", index=False)
        tables, _ = run_dict(registry, {"path": str(tmp_path), "sep": ","})
        assert set(tables) == {"sales.csv", "sales.tsv"}

    def test_include_and_exclude(self, registry, csv_dir):
        tables, _ = run_dict(registry, {"path": str(csv_dir),
                                        "exclude_pattern": "b.csv"})
        assert list(tables) == ["a.csv", "c.csv"]

    def test_nrows_caps_each_file_not_the_total(self, registry, csv_dir):
        """Where Read CSV (Folder) caps the stack, here each file is a result."""
        tables, _ = run_dict(registry, {"path": str(csv_dir), "nrows": 2})
        assert [len(frame) for frame in tables.values()] == [2, 2, 2]

    def test_a_bad_file_is_named_in_the_error(self, registry, csv_dir):
        (csv_dir / "broken.csv").write_text("")
        with pytest.raises(ValueError, match="broken.csv"):
            run_dict(registry, {"path": str(csv_dir)})

    def test_path_input_overrides_the_param(self, registry, csv_dir, tmp_path):
        tables, _ = run_dict(registry, {"path": str(tmp_path / "nowhere")},
                             path_input=str(csv_dir))
        assert list(tables) == ["a.csv", "b.csv", "c.csv"]

    def test_requires_a_folder(self, registry):
        with pytest.raises(ValueError, match="no folder selected"):
            run_dict(registry, {"path": ""})

    def test_empty_folder_says_what_it_wanted(self, registry, tmp_path):
        with pytest.raises(ValueError, match="no .csv"):
            run_dict(registry, {"path": str(tmp_path)})

    def test_dtypes_reach_the_parser(self, registry, tmp_path):
        (tmp_path / "codes.csv").write_text("code,n\n01234,1\n")
        tables, _ = run_dict(registry, {"path": str(tmp_path),
                                        "dtypes": "code = string"})
        assert list(tables["codes.csv"]["code"]) == ["01234"]

    def test_parallel_reads_give_the_same_dict(self, registry, csv_dir):
        one, _ = run_dict(registry, {"path": str(csv_dir), "parallel_files": 1})
        many, _ = run_dict(registry, {"path": str(csv_dir), "parallel_files": 3})
        assert list(one) == list(many)
        for name in one:
            pd.testing.assert_frame_equal(one[name], many[name])

    def test_polars_matches_the_pandas_result(self, registry, csv_dir):
        pytest.importorskip("polars")
        pandas_out, _ = run_dict(registry, {"path": str(csv_dir)})
        polars_out, log = run_dict(registry, {"path": str(csv_dir),
                                              "engine": "polars"})
        assert "via polars" in log
        assert list(pandas_out) == list(polars_out)
        for name in pandas_out:
            pd.testing.assert_frame_equal(pandas_out[name], polars_out[name])

    def test_polars_refuses_what_it_cannot_do(self, registry, csv_dir):
        pytest.importorskip("polars")
        with pytest.raises(ValueError, match="Thousands mark"):
            run_dict(registry, {"path": str(csv_dir), "engine": "polars",
                                "thousands": ","})

    def test_the_engine_hands_on_the_dict_itself(self, registry, csv_dir):
        """Not the port mapping — a single output takes a bare return, and a
        bare dict keyed like the ports would be read as the mapping."""
        spec = registry.get(CSV_DICT)
        run = compile_run(spec.source, "test-dict")
        params = spec.default_params() | {"path": str(csv_dir)}
        result = run(FakeContext(params=params), path_input=None)
        outputs = normalise(registry, CSV_DICT, result)
        assert list(outputs) == ["tables"]
        assert list(outputs["tables"]) == ["a.csv", "b.csv", "c.csv"]

    def test_a_lone_file_named_after_the_port_is_still_a_dict(self, registry,
                                                              tmp_path, parts):
        """The trap the named return exists for: one file whose stem is
        'tables' makes the payload's keys equal the port names."""
        parts[0].to_csv(tmp_path / "tables.csv", index=False)
        spec = registry.get(CSV_DICT)
        run = compile_run(spec.source, "test-dict")
        params = spec.default_params() | {"path": str(tmp_path),
                                          "key": "name without extension"}
        outputs = normalise(registry, CSV_DICT,
                            run(FakeContext(params=params), path_input=None))
        assert isinstance(outputs["tables"], dict)
        assert list(outputs["tables"]) == ["tables"]

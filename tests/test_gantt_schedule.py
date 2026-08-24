"""Gantt scheduling: the arithmetic behind the chart, without the chart."""
import pandas as pd
import pytest

from flograph.core.gantt import CALENDAR_DAYS, WORKING_DAYS, schedule


def plan(**columns):
    return pd.DataFrame(columns)


def dates(result, column="start"):
    return [d.strftime("%Y-%m-%d") for d in result[column]]


class TestForwardPass:
    def test_a_task_starts_when_its_predecessor_ends(self):
        out = schedule(plan(task=["A", "B"], days=[3, 2], after=["", "A"]),
                       task="task", duration="days", depends_on="after",
                       project_start="2026-03-02")
        assert dates(out) == ["2026-03-02", "2026-03-05"]
        assert dates(out, "finish") == ["2026-03-05", "2026-03-07"]

    def test_a_slipped_task_pushes_everything_after_it(self):
        tasks = plan(task=["A", "B", "C"], days=[3, 2, 1],
                     after=["", "A", "B"])
        before = schedule(tasks, task="task", duration="days",
                          depends_on="after", project_start="2026-03-02")
        tasks.loc[0, "days"] = 6
        after = schedule(tasks, task="task", duration="days",
                         depends_on="after", project_start="2026-03-02")
        assert dates(before, "finish")[-1] == "2026-03-08"
        assert dates(after, "finish")[-1] == "2026-03-11"

    def test_a_task_waits_for_the_last_of_several_predecessors(self):
        out = schedule(
            plan(id=["A", "B", "C"], task=["A", "B", "C"], days=[2, 5, 1],
                 after=["", "", "A,B"]),
            task="task", id="id", duration="days", depends_on="after",
            project_start="2026-03-02")
        assert dates(out)[2] == "2026-03-07"

    def test_an_explicit_start_pins_a_task_predecessors_or_not(self):
        out = schedule(
            plan(task=["A", "B"], days=[3, 2], after=["", "A"],
                 begins=["2026-03-02", "2026-03-20"]),
            task="task", duration="days", depends_on="after", start="begins")
        assert dates(out) == ["2026-03-02", "2026-03-20"]

    def test_tasks_with_no_start_and_no_predecessor_use_project_start(self):
        out = schedule(plan(task=["A", "B"], days=[1, 1], after=["", ""]),
                       task="task", duration="days", depends_on="after",
                       project_start="2026-07-01")
        assert dates(out) == ["2026-07-01", "2026-07-01"]

    def test_project_start_defaults_to_the_earliest_pinned_date(self):
        out = schedule(
            plan(task=["A", "B"], days=[1, 1], begins=["", "2026-05-04"]),
            task="task", duration="days", start="begins")
        assert dates(out) == ["2026-05-04", "2026-05-04"]

    def test_rows_come_back_in_input_order_not_dependency_order(self):
        out = schedule(
            plan(id=["C", "B", "A"], task=["last", "middle", "first"],
                 days=[1, 1, 1], after=["B", "A", ""]),
            task="task", id="id", duration="days", depends_on="after",
            project_start="2026-03-02")
        assert list(out["task"]) == ["last", "middle", "first"]
        assert dates(out) == ["2026-03-04", "2026-03-03", "2026-03-02"]


class TestDurations:
    def test_a_finish_column_gives_the_duration_when_there_is_none(self):
        out = schedule(
            plan(task=["A"], begins=["2026-03-02"], ends=["2026-03-06"]),
            task="task", start="begins", finish="ends")
        assert list(out["duration"]) == [4.0]

    def test_hours_and_weeks_are_understood(self):
        hours = schedule(plan(task=["A"], n=[36]), task="task", duration="n",
                         unit="hours", project_start="2026-03-02")
        weeks = schedule(plan(task=["A"], n=[2]), task="task", duration="n",
                         unit="weeks", project_start="2026-03-02")
        assert str(hours["finish"].iloc[0]) == "2026-03-03 12:00:00"
        assert dates(weeks, "finish") == ["2026-03-16"]

    def test_zero_duration_is_a_milestone(self):
        out = schedule(plan(task=["A", "Signed off"], days=[3, 0],
                            after=["", ""]),
                       task="task", duration="days", depends_on="after",
                       project_start="2026-03-02")
        assert list(out["is_milestone"]) == [False, True]
        assert out["start"].iloc[1] == out["finish"].iloc[1]

    def test_a_blank_duration_cell_is_a_milestone_not_an_error(self):
        out = schedule(plan(task=["A", "B"], days=[3, None], after=["", "A"]),
                       task="task", duration="days", depends_on="after",
                       project_start="2026-03-02")
        assert list(out["is_milestone"]) == [False, True]


class TestWorkingDays:
    def test_a_span_over_a_weekend_skips_it(self):
        tasks = plan(task=["A"], days=[3], begins=["2026-03-05"])  # Thursday
        calendar = schedule(tasks, task="task", duration="days",
                            start="begins", calendar=CALENDAR_DAYS)
        working = schedule(tasks, task="task", duration="days",
                           start="begins", calendar=WORKING_DAYS)
        assert dates(calendar, "finish") == ["2026-03-08"]
        assert dates(working, "finish") == ["2026-03-10"]

    def test_a_task_landing_on_a_weekend_rolls_to_monday(self):
        out = schedule(plan(task=["A"], days=[1], begins=["2026-03-07"]),
                       task="task", duration="days", start="begins",
                       calendar=WORKING_DAYS)
        assert dates(out) == ["2026-03-09"]

    def test_a_week_is_five_working_days(self):
        out = schedule(plan(task=["A"], n=[1], begins=["2026-03-02"]),
                       task="task", duration="n", start="begins",
                       unit="weeks", calendar=WORKING_DAYS)
        assert dates(out, "finish") == ["2026-03-09"]

    def test_hours_are_refused_rather_than_quietly_rounded(self):
        with pytest.raises(ValueError, match="whole days"):
            schedule(plan(task=["A"], n=[4]), task="task", duration="n",
                     unit="hours", calendar=WORKING_DAYS)


class TestProgress:
    def test_a_fraction_column_is_left_alone(self):
        out = schedule(plan(task=["A", "B"], days=[1, 1], pct=[0.25, 1.0]),
                       task="task", duration="days", progress="pct",
                       project_start="2026-03-02")
        assert list(out["progress"]) == [0.25, 1.0]

    def test_a_percentage_column_is_divided_down(self):
        out = schedule(plan(task=["A", "B"], days=[1, 1], pct=[25, 100]),
                       task="task", duration="days", progress="pct",
                       project_start="2026-03-02")
        assert list(out["progress"]) == [0.25, 1.0]

    def test_out_of_range_values_clamp(self):
        out = schedule(plan(task=["A", "B"], days=[1, 1], pct=[-20, 150]),
                       task="task", duration="days", progress="pct",
                       project_start="2026-03-02")
        assert list(out["progress"]) == [0.0, 1.0]

    def test_no_progress_column_leaves_the_column_empty(self):
        out = schedule(plan(task=["A"], days=[1]), task="task",
                       duration="days", project_start="2026-03-02")
        assert out["progress"].iloc[0] is None


class TestOptionalColumns:
    def test_baselines_come_through_as_dates_when_asked_for(self):
        out = schedule(
            plan(task=["A"], days=[3], bs=["2026-03-02"], bf=["2026-03-04"]),
            task="task", duration="days", baseline_start="bs",
            baseline_finish="bf", project_start="2026-03-02")
        assert dates(out, "baseline_finish") == ["2026-03-04"]

    def test_no_baseline_columns_means_no_baseline_columns_out(self):
        out = schedule(plan(task=["A"], days=[3]), task="task",
                       duration="days", project_start="2026-03-02")
        assert "baseline_start" not in out.columns

    def test_ids_fall_back_to_task_names(self):
        out = schedule(
            plan(task=["Design", "Build"], days=[1, 1], after=["", "Design"]),
            task="task", duration="days", depends_on="after",
            project_start="2026-03-02")
        assert list(out["id"]) == ["Design", "Build"]
        assert dates(out) == ["2026-03-02", "2026-03-03"]

    def test_pandas_na_reads_as_an_empty_cell(self):
        # What the Table node hands out for a blank cell of a typed column:
        # pandas' NA, which refuses to be turned into a bool at all.
        tasks = pd.DataFrame({
            "task": pd.array(["A", "B"], dtype="string"),
            "days": pd.array([2, None], dtype="Int64"),
            "after": pd.array([None, "A"], dtype="string"),
        })
        out = schedule(tasks, task="task", duration="days",
                       depends_on="after", project_start="2026-03-02")
        assert dates(out) == ["2026-03-02", "2026-03-04"]
        assert list(out["is_milestone"]) == [False, True]

    def test_a_numeric_id_column_still_matches_its_dependencies(self):
        out = schedule(
            plan(id=[1, 2], task=["A", "B"], days=[2, 1], after=["", "1"]),
            task="task", id="id", duration="days", depends_on="after",
            project_start="2026-03-02")
        assert dates(out) == ["2026-03-02", "2026-03-04"]


class TestErrors:
    def test_a_circle_of_dependencies_names_the_tasks_in_it(self):
        with pytest.raises(ValueError, match="circle.*A.*B"):
            schedule(plan(id=["A", "B"], task=["A", "B"], days=[1, 1],
                          after=["B", "A"]),
                     task="task", id="id", duration="days",
                     depends_on="after")

    def test_an_unknown_predecessor_names_the_task_that_wanted_it(self):
        with pytest.raises(ValueError, match="'B'.*'nope'"):
            schedule(plan(id=["A", "B"], task=["A", "B"], days=[1, 1],
                          after=["", "nope"]),
                     task="task", id="id", duration="days",
                     depends_on="after")

    def test_two_tasks_sharing_an_id_is_refused(self):
        with pytest.raises(ValueError, match="share the id"):
            schedule(plan(id=["A", "A"], task=["one", "two"], days=[1, 1]),
                     task="task", id="id", duration="days")

    def test_a_missing_task_column_says_so(self):
        with pytest.raises(ValueError, match="needs a Task column"):
            schedule(plan(task=["A"], days=[1]), task="", duration="days")

    def test_a_task_column_that_is_not_there_names_it(self):
        with pytest.raises(ValueError, match="Task column 'nope'"):
            schedule(plan(task=["A"], days=[1]), task="nope", duration="days")

    def test_nothing_to_measure_length_with_says_so(self):
        with pytest.raises(ValueError, match="Duration column or a Finish"):
            schedule(plan(task=["A"]), task="task")

    def test_a_pinned_finish_before_its_predecessor_ends_is_a_conflict(self):
        with pytest.raises(ValueError, match="cannot start until"):
            schedule(plan(id=["A", "B"], task=["A", "B"],
                          days=[10, None], after=["", "A"],
                          ends=["", "2026-03-04"]),
                     task="task", id="id", duration="days",
                     depends_on="after", finish="ends",
                     project_start="2026-03-02")

    def test_a_negative_duration_is_refused(self):
        with pytest.raises(ValueError, match="negative duration"):
            schedule(plan(task=["A"], days=[-2]), task="task",
                     duration="days", project_start="2026-03-02")

    def test_an_unreadable_date_names_the_value(self):
        with pytest.raises(ValueError, match="Start is not a date"):
            schedule(plan(task=["A"], days=[1], begins=["last tuesday-ish"]),
                     task="task", duration="days", start="begins")

    def test_an_unknown_calendar_or_unit_is_refused(self):
        with pytest.raises(ValueError, match="duration unit"):
            schedule(plan(task=["A"], days=[1]), task="task",
                     duration="days", unit="fortnights")
        with pytest.raises(ValueError, match="calendar must be"):
            schedule(plan(task=["A"], days=[1]), task="task",
                     duration="days", calendar="lunar")

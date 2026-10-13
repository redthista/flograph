"""Browse… dialogs open on the field's own file, else the last folder
browsed to, else home — never the working directory flograph ran from."""
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings

from flograph.ui import file_start
from flograph.ui.file_start import remember, start_path


@pytest.fixture(autouse=True)
def _no_last_folder():
    QSettings("flograph", "flograph").remove(file_start.LAST_FOLDER_SETTING)
    yield
    QSettings("flograph", "flograph").remove(file_start.LAST_FOLDER_SETTING)


def test_existing_file_opens_on_itself(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("a\n1\n")
    assert start_path(str(f)) == str(f)


def test_save_name_in_an_existing_folder_is_prefilled(tmp_path):
    assert start_path(str(tmp_path / "out.csv")) == str(tmp_path / "out.csv")


def test_missing_folders_climb_to_the_nearest_that_exists(tmp_path):
    gone = tmp_path / "gone" / "deeper" / "x.csv"
    assert start_path(str(gone)) == str(tmp_path)
    assert start_path(str(tmp_path / "gone"), folder=True) == str(tmp_path)


def test_folder_field_on_a_file_opens_its_folder(tmp_path):
    f = tmp_path / "data.csv"
    f.write_text("")
    assert start_path(str(f), folder=True) == str(tmp_path)


def test_empty_field_uses_last_folder_then_home(tmp_path):
    assert start_path("") == str(Path.home())
    f = tmp_path / "picked.csv"
    f.write_text("")
    remember(str(f))
    assert start_path("") == str(tmp_path)
    assert start_path("", folder=True) == str(tmp_path)


def test_bare_relative_name_does_not_open_the_working_directory(tmp_path,
                                                               monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert start_path("nowhere.csv") == str(Path.home())
    assert start_path("no/such/file.csv") == str(Path.home())


def test_a_vanished_last_folder_falls_back_to_home(tmp_path):
    gone = tmp_path / "was_here"
    gone.mkdir()
    remember(str(gone))
    gone.rmdir()
    assert start_path("") == str(Path.home())

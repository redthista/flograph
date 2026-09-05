"""Web libraries: install once from a CDN, render from disk forever after.

The rule this file exists to hold: **nothing renders from the internet.**
`markup()` either produces a local path or raises — it must never fall back
to a remote URL, because a visual that works online and breaks offline is
the failure the whole store was built to prevent.

No test here reaches the network. `install()` is exercised against a local
HTTP server and a `file://` URL; everything downstream of a download is
exercised against libraries planted by tests.conftest.install_fake_weblib.
"""
from __future__ import annotations

import hashlib
import json

import pytest

from PySide6.QtCore import Qt

from flograph import weblibs
from tests.conftest import install_fake_weblib


@pytest.fixture
def store(monkeypatch, tmp_path):
    """An empty store nothing else can see."""
    monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path))
    return tmp_path / "weblibs"


class TestCatalogue:
    def test_it_is_not_empty(self):
        assert len(weblibs.CATALOGUE) >= 5

    def test_every_entry_is_pinned_and_checksummed(self):
        """A version and a hash per file — this is executable code that will
        run in the user's browser, so "it downloaded something" is not
        enough."""
        for name, library in weblibs.CATALOGUE.items():
            assert library.version, name
            assert library.assets, name
            for asset in library.assets:
                assert len(asset.sha256) == 64, (name, asset.filename)
                assert asset.size > 0, (name, asset.filename)

    def test_every_url_is_https(self):
        for library in weblibs.CATALOGUE.values():
            for asset in library.assets:
                assert asset.url.startswith("https://"), asset.url

    def test_the_key_matches_the_library_name(self):
        for key, library in weblibs.CATALOGUE.items():
            assert key == library.name

    def test_leaflet_brings_its_stylesheet(self):
        """A map library that arrives without its CSS renders as a heap of
        unpositioned tiles — the case that makes assets a list."""
        files = {a.filename for a in weblibs.CATALOGUE["leaflet"].assets}
        assert files == {"leaflet.js", "leaflet.css"}


class TestNothingRendersFromTheInternet:
    """The load-bearing rule, asserted from several directions."""

    def test_markup_of_an_installed_library_is_a_local_file(
            self, monkeypatch, tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        tags = weblibs.markup("d3")
        assert tags.startswith("<script src=\"file://")
        assert "http://" not in tags and "https://" not in tags

    def test_markup_raises_rather_than_reaching_for_a_cdn(self, store):
        with pytest.raises(weblibs.MissingLibrary) as caught:
            weblibs.markup("d3")
        assert "not installed" in str(caught.value)
        assert caught.value.name == "d3"

    def test_the_message_says_where_to_install_it(self, store):
        with pytest.raises(weblibs.MissingLibrary, match="Web Libraries"):
            weblibs.markup("d3")

    def test_an_unknown_library_says_it_is_not_in_the_catalogue(self, store):
        with pytest.raises(weblibs.MissingLibrary, match="catalogue"):
            weblibs.markup("nosuchlib")

    def test_no_node_in_the_library_references_a_cdn(self):
        """The regression guard for the whole feature: a node that hard-codes
        a CDN URL is exactly what this replaced, and one slipping back in
        would be invisible until someone opened it offline."""
        from flograph.core import NodeRegistry
        registry = NodeRegistry()
        registry.load_builtins()
        offenders = [spec.type_id for spec in registry.all()
                     if "cdnjs" in spec.source or "unpkg.com" in spec.source
                     or "cdn.jsdelivr" in spec.source]
        assert offenders == []


class TestResolution:
    def test_not_installed_by_default(self, store):
        assert not weblibs.is_installed("d3")
        assert weblibs.installed_version("d3") is None

    def test_installed_after_planting(self, monkeypatch, tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        assert weblibs.is_installed("d3")
        assert weblibs.installed_version("d3") == weblibs.CATALOGUE["d3"].version

    def test_a_missing_file_means_not_installed(self, monkeypatch, tmp_path):
        """A half-finished install must not read as a working one, or the
        node fails later and further from the cause."""
        directory = install_fake_weblib(monkeypatch, tmp_path, "d3")
        (directory / "d3.min.js").unlink()
        assert not weblibs.is_installed("d3")

    def test_deleting_the_directory_uninstalls_it(self, monkeypatch, tmp_path):
        """Answering from disk rather than a record: someone who deletes the
        folder has uninstalled it, and we should agree with them."""
        import shutil
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        shutil.rmtree(tmp_path / "weblibs" / "d3")
        assert not weblibs.is_installed("d3")

    def test_installed_lists_what_is_there(self, monkeypatch, tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        install_fake_weblib(monkeypatch, tmp_path, "mermaid")
        assert {lib.name for lib in weblibs.installed()} == {"d3", "mermaid"}

    def test_remove_deletes_it(self, monkeypatch, tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        assert weblibs.remove("d3")
        assert not weblibs.is_installed("d3")

    def test_removing_what_is_not_there_is_not_an_error(self, store):
        assert weblibs.remove("d3") is False

    def test_asset_path_points_into_the_store(self, monkeypatch, tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        path = weblibs.asset_path("d3", "d3.min.js")
        assert path.is_file() and tmp_path in path.parents


class TestMarkup:
    def test_inline_embeds_the_source(self, monkeypatch, tmp_path):
        """What an export needs: one file that opens anywhere, with no
        second file to lose."""
        install_fake_weblib(monkeypatch, tmp_path, "d3",
                            source="window.D3_STUB = 1;")
        tags = weblibs.markup("d3", mode=weblibs.INLINE)
        assert "window.D3_STUB = 1;" in tags
        assert "file://" not in tags

    def test_css_becomes_a_stylesheet_not_a_script(self, monkeypatch,
                                                   tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "leaflet")
        tags = weblibs.markup("leaflet")
        assert '<link rel="stylesheet"' in tags and "leaflet.css" in tags
        assert "<script src=" in tags and "leaflet.js" in tags

    def test_the_stylesheet_comes_before_the_script(self, monkeypatch,
                                                    tmp_path):
        """A script that draws on load would otherwise paint before its CSS
        arrives — a map of unpositioned tiles."""
        install_fake_weblib(monkeypatch, tmp_path, "leaflet")
        tags = weblibs.markup("leaflet")
        assert tags.index("leaflet.css") < tags.index("leaflet.js")

    def test_inline_css_becomes_a_style_block(self, monkeypatch, tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "leaflet",
                            source=".x{color:red}")
        tags = weblibs.markup("leaflet", mode=weblibs.INLINE)
        assert tags.startswith("<style>.x{color:red}</style>")

    def test_several_libraries_keep_their_order(self, monkeypatch, tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        install_fake_weblib(monkeypatch, tmp_path, "echarts")
        tags = weblibs.markup("d3", "echarts")
        assert tags.index("d3.min.js") < tags.index("echarts.min.js")

    def test_an_unknown_mode_is_refused(self, monkeypatch, tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        with pytest.raises(weblibs.WebLibError, match="unknown mode"):
            weblibs.markup("d3", mode="carrier pigeon")

    def test_require_raises_before_any_work(self, store):
        with pytest.raises(weblibs.MissingLibrary):
            weblibs.require("d3")

    def test_require_passes_when_installed(self, monkeypatch, tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        weblibs.require("d3")          # must not raise


class TestInstall:
    """Driven against local URLs — the download path is exercised, the
    network is not."""

    def _serve(self, tmp_path, body: bytes, name: str = "lib.js") -> str:
        source = tmp_path / "served"
        source.mkdir(exist_ok=True)
        (source / name).write_bytes(body)
        return (source / name).as_uri()

    def test_it_fetches_verifies_and_stores(self, monkeypatch, tmp_path):
        body = b"window.OK = 1;"
        url = self._serve(tmp_path, body)
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "profile"))
        monkeypatch.setitem(weblibs.CATALOGUE, "probe", weblibs.Library(
            name="probe", title="Probe", version="1.0",
            assets=(weblibs.Asset(filename="lib.js", url=url,
                                  sha256=hashlib.sha256(body).hexdigest(),
                                  size=len(body)),)))
        weblibs.install("probe")
        assert weblibs.is_installed("probe")
        assert weblibs.asset_path("probe", "lib.js").read_bytes() == body

    def test_a_checksum_mismatch_installs_nothing(self, monkeypatch,
                                                  tmp_path):
        """The point of pinning: tampered or wrong bytes are discarded, and
        nothing is left that would read as installed."""
        url = self._serve(tmp_path, b"not what was pinned")
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "profile"))
        monkeypatch.setitem(weblibs.CATALOGUE, "probe", weblibs.Library(
            name="probe", title="Probe", version="1.0",
            assets=(weblibs.Asset(filename="lib.js", url=url,
                                  sha256="0" * 64, size=1),)))
        with pytest.raises(weblibs.WebLibError, match="checksum"):
            weblibs.install("probe")
        assert not weblibs.is_installed("probe")

    def test_a_failed_download_leaves_nothing_behind(self, monkeypatch,
                                                     tmp_path):
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "profile"))
        monkeypatch.setitem(weblibs.CATALOGUE, "probe", weblibs.Library(
            name="probe", title="Probe", version="1.0",
            assets=(weblibs.Asset(filename="lib.js",
                                  url=(tmp_path / "nope.js").as_uri()),)))
        with pytest.raises(weblibs.WebLibError, match="could not fetch"):
            weblibs.install("probe")
        assert not weblibs.is_installed("probe")
        assert not list((tmp_path / "profile" / "weblibs").glob("probe/*/*.js"))

    def test_progress_is_reported_per_file(self, monkeypatch, tmp_path):
        body = b"x"
        url = self._serve(tmp_path, body)
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "profile"))
        monkeypatch.setitem(weblibs.CATALOGUE, "probe", weblibs.Library(
            name="probe", title="Probe", version="1.0",
            assets=(weblibs.Asset(filename="lib.js", url=url,
                                  sha256=hashlib.sha256(body).hexdigest()),)))
        seen = []
        weblibs.install("probe", progress=lambda *a: seen.append(a))
        assert seen == [(1, 1, "lib.js")]

    def test_it_writes_a_manifest(self, monkeypatch, tmp_path):
        body = b"x"
        url = self._serve(tmp_path, body)
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "profile"))
        monkeypatch.setitem(weblibs.CATALOGUE, "probe", weblibs.Library(
            name="probe", title="Probe", version="1.0",
            assets=(weblibs.Asset(filename="lib.js", url=url,
                                  sha256=hashlib.sha256(body).hexdigest()),)))
        weblibs.install("probe")
        manifest = (weblibs.library_dir("probe", "1.0")
                    / "flograph-weblib.json")
        assert json.loads(manifest.read_text())["name"] == "probe"

    def test_an_unknown_name_is_refused(self, store):
        with pytest.raises(weblibs.WebLibError, match="unknown web library"):
            weblibs.install("nosuchlib")


class TestAddFromUrl:
    def test_a_hand_added_library_behaves_like_a_catalogue_one(
            self, monkeypatch, tmp_path):
        """The escape hatch has to be first-class, or the catalogue has to be
        exhaustive to be useful."""
        source = tmp_path / "served"
        source.mkdir()
        (source / "vis.js").write_bytes(b"window.VIS = 1;")
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "profile"))

        weblibs.add_from_url("vis", [(source / "vis.js").as_uri()])
        assert weblibs.is_installed("vis")
        assert "window.VIS = 1;" in weblibs.markup("vis", mode=weblibs.INLINE)

    def test_it_survives_a_fresh_process(self, monkeypatch, tmp_path):
        """Read back from its manifest rather than the catalogue it was
        never in — otherwise it would vanish on restart."""
        source = tmp_path / "served"
        source.mkdir()
        (source / "vis.js").write_bytes(b"1;")
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "profile"))
        weblibs.add_from_url("vis", [(source / "vis.js").as_uri()])

        weblibs.CATALOGUE.pop("vis", None)      # as a restart would leave it
        assert weblibs.is_installed("vis")
        assert weblibs.known("vis").name == "vis"

    def test_it_does_not_pollute_the_catalogue(self, monkeypatch, tmp_path):
        source = tmp_path / "served"
        source.mkdir()
        (source / "vis.js").write_bytes(b"1;")
        monkeypatch.setenv("FLOGRAPH_USER_DIR", str(tmp_path / "profile"))
        weblibs.add_from_url("vis", [(source / "vis.js").as_uri()])
        assert "vis" not in weblibs.CATALOGUE

    @pytest.mark.parametrize("url", [
        "https://example.com/",          # a bare host, not a file
        "https://example.com/lib/",      # a directory
        "https://example.com/nodots",    # nothing saying what kind of file
    ])
    def test_a_url_that_names_no_file_is_refused(self, store, url):
        """Otherwise a trailing slash quietly produces a library whose one
        file is named after the domain."""
        with pytest.raises(weblibs.WebLibError, match="filename"):
            weblibs.add_from_url("vis", [url])

    def test_no_urls_is_refused(self, store):
        with pytest.raises(weblibs.WebLibError, match="no URLs"):
            weblibs.add_from_url("vis", [])


class TestPrivateMirror:
    """An environment with no route to cdnjs still has to be installable —
    the same courtesy the update check already extends."""

    def test_the_base_url_redirects_the_fetch(self, monkeypatch, tmp_path):
        mirror = tmp_path / "mirror" / "d3" / weblibs.CATALOGUE["d3"].version
        mirror.mkdir(parents=True)
        body = weblibs.CATALOGUE["d3"].assets[0].sha256  # any bytes will do
        (mirror / "d3.min.js").write_text(body)
        monkeypatch.setenv(weblibs.BASE_URL_ENV,
                           (tmp_path / "mirror").as_uri())
        library = weblibs.CATALOGUE["d3"]
        url = weblibs._asset_url(library, library.assets[0])
        assert url.startswith("file://") and url.endswith("/d3.min.js")

    def test_without_it_the_catalogue_url_is_used(self, monkeypatch):
        monkeypatch.delenv(weblibs.BASE_URL_ENV, raising=False)
        library = weblibs.CATALOGUE["d3"]
        assert (weblibs._asset_url(library, library.assets[0])
                == library.assets[0].url)


class TestExport:
    """Two ways a finished page leaves flograph, both starting from the
    file:// references the card uses."""

    def _page(self, monkeypatch, tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "d3",
                            source="window.D3_STUB = 1;")
        return f"<html><head>{weblibs.markup('d3')}</head><body>x</body></html>"

    def test_inline_makes_one_self_contained_file(self, monkeypatch,
                                                  tmp_path):
        page = weblibs.inline_page(self._page(monkeypatch, tmp_path))
        assert "window.D3_STUB = 1;" in page
        assert "file://" not in page

    def test_inline_leaves_a_page_with_no_libraries_alone(self, store):
        page = "<html><body>plain</body></html>"
        assert weblibs.inline_page(page) == page

    def test_inline_ignores_file_urls_outside_the_store(self, monkeypatch,
                                                        tmp_path):
        """An export rewrites what flograph installed, and leaves whatever
        else a node chose to reference exactly as the node wrote it."""
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        elsewhere = tmp_path / "mine.js"
        elsewhere.write_text("mine")
        page = f'<script src="{elsewhere.as_uri()}"></script>'
        assert weblibs.inline_page(page) == page

    def test_bundle_writes_assets_and_relative_hrefs(self, monkeypatch,
                                                     tmp_path):
        page = self._page(monkeypatch, tmp_path)
        out = tmp_path / "site"
        rewritten, written = weblibs.bundle_page(page, out)
        assert (out / "assets" / "d3.min.js").is_file()
        assert 'src="assets/d3.min.js"' in rewritten
        assert "file://" not in rewritten
        assert len(written) == 1

    def test_bundle_carries_a_stylesheet_as_a_stylesheet(self, monkeypatch,
                                                         tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "leaflet", source="x")
        page = weblibs.markup("leaflet")
        rewritten, _ = weblibs.bundle_page(page, tmp_path / "site")
        assert 'rel="stylesheet" href="assets/leaflet.css"' in rewritten
        assert 'src="assets/leaflet.js"' in rewritten

    def test_bundle_does_not_copy_the_same_file_twice(self, monkeypatch,
                                                      tmp_path):
        page = self._page(monkeypatch, tmp_path)
        out = tmp_path / "site"
        weblibs.bundle_page(page, out)
        _, written = weblibs.bundle_page(page, out)
        assert written == []


class TestDialog:
    def test_it_lists_the_catalogue(self, qtbot, store):
        from flograph.ui.weblibs_dialog import WebLibrariesDialog
        dialog = WebLibrariesDialog()
        qtbot.addWidget(dialog)
        assert dialog._table.rowCount() == len(weblibs.CATALOGUE)

    def test_it_shows_what_is_installed(self, qtbot, monkeypatch, tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        from flograph.ui.weblibs_dialog import WebLibrariesDialog
        dialog = WebLibrariesDialog()
        qtbot.addWidget(dialog)
        states = {}
        for row in range(dialog._table.rowCount()):
            name = dialog._table.item(row, dialog.NAME).data(Qt.UserRole)
            states[name] = dialog._table.item(row, dialog.STATUS).text()
        assert states["d3"] == "Installed"
        assert states["echarts"] == "Not installed"

    def test_a_hand_added_library_still_appears(self, qtbot, monkeypatch,
                                                tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "homegrown")
        from flograph.ui.weblibs_dialog import WebLibrariesDialog
        dialog = WebLibrariesDialog()
        qtbot.addWidget(dialog)
        listed = {dialog._table.item(r, dialog.NAME).data(Qt.UserRole)
                  for r in range(dialog._table.rowCount())}
        assert "homegrown" in listed

    def test_remove_takes_it_out_of_the_store(self, qtbot, monkeypatch,
                                              tmp_path):
        install_fake_weblib(monkeypatch, tmp_path, "d3")
        from flograph.ui.weblibs_dialog import WebLibrariesDialog
        dialog = WebLibrariesDialog()
        qtbot.addWidget(dialog)
        monkeypatch.setattr(
            "flograph.ui.weblibs_dialog.QMessageBox.question",
            lambda *a, **k: __import__(
                "PySide6.QtWidgets", fromlist=["QMessageBox"]
            ).QMessageBox.Yes)
        dialog._table.selectRow(
            [dialog._table.item(r, dialog.NAME).data(Qt.UserRole)
             for r in range(dialog._table.rowCount())].index("d3"))
        dialog._remove_selected()
        assert not weblibs.is_installed("d3")

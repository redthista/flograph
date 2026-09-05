"""Web libraries — the JavaScript and CSS a visual node draws with,
installed once and then used from disk. Qt-free, stdlib only.

flograph's Python side already works this way: a node needs plotly, you
install plotly, and from then on the node runs offline. Its *browser* side
did not. The Mermaid node reached out to a CDN every time it rendered, which
meant a visual that worked at your desk was a white box on a train, on a
locked-down network, or in three years when that URL moved. A `.flograph`
you hand to someone is supposed to work when they open it.

So a CDN is where a library is **installed from**, and nothing else. There
is deliberately no fallback to a remote URL at render time:

* **Install writes; render reads.** `install()` is the only function here
  that touches the network, and it only ever runs because someone pressed a
  button in Tools ▸ Web Libraries.
* **A missing library is an error, not a silent CDN hit.** `markup()` raises
  MissingLibrary naming the fix. A visual that quietly worked online and
  broke offline is the exact failure this design exists to prevent.
* **What is installed is pinned and checked.** Every asset carries the
  sha256 of the bytes this catalogue was built against; a download that
  doesn't match is discarded. This is executable code that will run in the
  user's browser, so "it downloaded something" is not good enough.

Two ways to put a library into a page, which is what makes the same visual
work on a card and in a file you email someone:

* `LINK` — a `file://` URL into the store. What the card uses: Chromium
  caches it, and a 3 MB library isn't re-embedded on every run.
* `INLINE` — the source pasted into the page. What an export uses, so a
  single `.html` carries everything it needs and opens anywhere.

Behind a private mirror, set `FLOGRAPH_WEBLIB_BASE_URL` (or Settings) and
every asset is fetched from `<base>/<library>/<version>/<file>` instead of
cdnjs — the same courtesy the update check already extends to environments
with no route to the public internet.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

#: Environment override pointing installs at a private mirror laid out the
#: way cdnjs is: <base>/<library>/<version>/<filename>.
BASE_URL_ENV = "FLOGRAPH_WEBLIB_BASE_URL"

#: How a library is put into a page. Not a style choice — see the module
#: docstring: the card wants a cached file, an export wants self-contained.
LINK = "link"
INLINE = "inline"


class WebLibError(Exception):
    """Something went wrong installing or reading a web library."""


class MissingLibrary(WebLibError):
    """A node asked for a library that is not installed.

    Carries `name` so a caller can offer to install that one specifically
    rather than making the user find it in a list.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        known = name in CATALOGUE
        where = (f"Install it from Tools ▸ Web Libraries." if known else
                 f"It is not in the catalogue — add it from a URL in "
                 f"Tools ▸ Web Libraries.")
        super().__init__(f"the web library {name!r} is not installed. {where}")


@dataclass(frozen=True)
class Asset:
    """One file of a library, and where it came from."""

    filename: str
    url: str
    #: sha256 of the bytes this catalogue was built against. "" for a
    #: library added from a URL by hand, where there is nothing to compare
    #: against — the user chose the source, so the user is the authority.
    sha256: str = ""
    size: int = 0

    @property
    def is_stylesheet(self) -> bool:
        return self.filename.lower().endswith(".css")


@dataclass(frozen=True)
class Library:
    name: str
    title: str
    version: str
    summary: str = ""
    license: str = ""
    homepage: str = ""
    assets: tuple[Asset, ...] = ()

    @property
    def size(self) -> int:
        return sum(asset.size for asset in self.assets)


CATALOGUE: dict[str, Library] = {
    "d3": Library(
        name="d3",
        title="D3",
        version="7.9.0",
        summary="A JavaScript visualization library for HTML and SVG.",
        license="BSD-3-Clause",
        homepage="https://d3js.org",
        assets=(
            Asset(
                filename="d3.min.js",
                url="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js",
                sha256="f2094bbf6141b359722c4fe454eb6c4b0f0e42cc10cc7af921fc158fceb86539",
                size=279706,
            ),
        ),
    ),
    "echarts": Library(
        name="echarts",
        title="Apache ECharts",
        version="6.1.0",
        summary="A powerful, interactive charting and data visualization library for browser",
        license="Apache-2.0",
        homepage="https://echarts.apache.org",
        assets=(
            Asset(
                filename="echarts.min.js",
                url="https://cdnjs.cloudflare.com/ajax/libs/echarts/6.1.0/echarts.min.js",
                sha256="b66b25aeb4df84e33199dc21694014d336d222cbd9deb0e5a7c14bd6aa0d0fd0",
                size=1121883,
            ),
        ),
    ),
    "apexcharts": Library(
        name="apexcharts",
        title="ApexCharts",
        version="7.1.0",
        summary="A JavaScript Chart Library",
        license="MIT",
        homepage="https://apexcharts.com",
        assets=(
            Asset(
                filename="apexcharts.min.js",
                url="https://cdnjs.cloudflare.com/ajax/libs/apexcharts/7.1.0/apexcharts.min.js",
                sha256="44f6a2129104bf6ee9f29f0399ecc725990d007d8a89e754ddc250ce27d3f47b",
                size=936826,
            ),
        ),
    ),
    "chartjs": Library(
        name="chartjs",
        title="Chart.js",
        version="4.5.1",
        summary="Simple HTML5 charts using the canvas element.",
        license="MIT",
        homepage="http://www.chartjs.org",
        assets=(
            Asset(
                filename="chart.umd.min.js",
                url="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.5.1/chart.umd.min.js",
                sha256="48444a82d4edcb5bec0f1965faacdde18d9c17db3063d042abada2f705c9f54a",
                size=208522,
            ),
        ),
    ),
    "mermaid": Library(
        name="mermaid",
        title="Mermaid",
        version="11.15.0",
        summary="Markdownish syntax for flowcharts, sequence and class diagrams, gantts and more.",
        license="MIT",
        homepage="https://mermaid.js.org",
        assets=(
            Asset(
                filename="mermaid.min.js",
                url="https://cdnjs.cloudflare.com/ajax/libs/mermaid/11.15.0/mermaid.min.js",
                sha256="70137e77bb273bb2ef972b86e8b0400cca8be53cb25bfc45911a186dc98665de",
                size=3312967,
            ),
        ),
    ),
    "leaflet": Library(
        name="leaflet",
        title="Leaflet",
        version="1.9.4",
        summary="JavaScript library for mobile-friendly interactive maps",
        license="BSD-2-Clause",
        homepage="http://leafletjs.com/",
        assets=(
            Asset(
                filename="leaflet.js",
                url="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js",
                sha256="db49d009c841f5ca34a888c96511ae936fd9f5533e90d8b2c4d57596f4e5641a",
                size=147552,
            ),
            Asset(
                filename="leaflet.css",
                url="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css",
                sha256="a7837102824184820dfa198d1ebcd109ff6d0ff9a2672a074b9a1b4d147d04c6",
                size=14806,
            ),
        ),
    ),
    "cytoscape": Library(
        name="cytoscape",
        title="Cytoscape",
        version="3.34.2",
        summary="Graph theory (a.k.a. network) library for analysis and visualisation",
        license="MIT",
        homepage="http://js.cytoscape.org",
        assets=(
            Asset(
                filename="cytoscape.min.js",
                url="https://cdnjs.cloudflare.com/ajax/libs/cytoscape/3.34.2/cytoscape.min.js",
                sha256="b85c213252b880cbb2d86c10dc537f673560e82494da4330f1ccc18fbcb5f145",
                size=435503,
            ),
        ),
    ),
}

# ------------------------------------------------------------------- store

def store_dir() -> Path:
    """Where installed libraries live. A sibling of the nodes and frames
    directories: a web library is another thing the user adds to flograph,
    not a corner of any one project."""
    from flograph.paths import user_data_dir
    return user_data_dir() / "weblibs"


def library_dir(name: str, version: str) -> Path:
    """One library's directory. Versioned, so upgrading doesn't leave a
    half-old set of files behind and two projects pinned to different
    versions can coexist."""
    return store_dir() / name / version


def _manifest_path(name: str, version: str) -> Path:
    return library_dir(name, version) / "flograph-weblib.json"


def known(name: str) -> Optional[Library]:
    """The catalogue entry, or a manifest read back for something installed
    from a URL by hand."""
    entry = CATALOGUE.get(name)
    if entry is not None:
        return entry
    return _installed_from_manifest(name)


def _installed_from_manifest(name: str) -> Optional[Library]:
    """Rebuild a Library from what was written at install time.

    This is what makes a hand-added library a first-class citizen: it is
    described by its own manifest rather than having to be in a catalogue
    that shipped before it existed.
    """
    import json

    root = store_dir() / name
    if not root.is_dir():
        return None
    for version_dir in sorted(root.iterdir(), reverse=True):
        path = version_dir / "flograph-weblib.json"
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        return Library(
            name=data.get("name", name),
            title=data.get("title", name),
            version=data.get("version", version_dir.name),
            summary=data.get("summary", ""),
            license=data.get("license", ""),
            homepage=data.get("homepage", ""),
            assets=tuple(
                Asset(filename=a.get("filename", ""), url=a.get("url", ""),
                      sha256=a.get("sha256", ""), size=int(a.get("size", 0)))
                for a in data.get("assets", [])),
        )
    return None


def installed_version(name: str) -> Optional[str]:
    """The installed version of `name`, or None.

    Answers from the files on disk rather than from a record of what was
    installed: someone who deletes the directory has uninstalled it, and
    this should agree with them.
    """
    library = known(name)
    if library is None:
        return None
    directory = library_dir(name, library.version)
    if not directory.is_dir():
        return None
    if not all((directory / asset.filename).is_file()
               for asset in library.assets):
        return None            # a half-finished install is not installed
    return library.version


def is_installed(name: str) -> bool:
    return installed_version(name) is not None


def installed() -> list[Library]:
    """Every library currently in the store, catalogue or hand-added."""
    root = store_dir()
    names = set(CATALOGUE)
    if root.is_dir():
        names.update(p.name for p in root.iterdir() if p.is_dir())
    found = []
    for name in sorted(names):
        if is_installed(name):
            library = known(name)
            if library is not None:
                found.append(library)
    return found


def asset_path(name: str, filename: str) -> Path:
    """Where one file of an installed library sits."""
    library = known(name)
    if library is None or not is_installed(name):
        raise MissingLibrary(name)
    return library_dir(name, library.version) / filename


# ----------------------------------------------------------------- install

def _download(url: str, timeout: float = 60.0) -> bytes:
    import urllib.request
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    except Exception as exc:                       # URLError, HTTPError, ...
        raise WebLibError(f"could not fetch {url} — {exc}") from None


def _asset_url(library: Library, asset: Asset) -> str:
    """Where to fetch this asset from, honouring a private mirror.

    A mirror is assumed to be laid out the way cdnjs is, because that is
    what mirroring cdnjs produces; anything else can still be added by URL.
    """
    base = (os.environ.get(BASE_URL_ENV) or "").strip().rstrip("/")
    if not base:
        return asset.url
    return f"{base}/{library.name}/{library.version}/{asset.filename}"


def install(name: str, progress=None) -> Library:
    """Fetch every file of `name` into the store and return the library.

    The only function here that touches the network. Each asset is verified
    against the catalogue's sha256 before it is kept, and everything is
    written to a temporary directory that is moved into place at the end —
    so an interrupted or corrupted install leaves nothing behind that
    `installed_version` would mistake for a working one.

    `progress(done, total, filename)` is called as each file lands.
    """
    import hashlib
    import json
    import shutil
    import tempfile

    library = CATALOGUE.get(name) or _installed_from_manifest(name)
    if library is None:
        raise WebLibError(f"unknown web library {name!r}")
    if not library.assets:
        raise WebLibError(f"{name!r} lists no files to install")

    target = library_dir(library.name, library.version)
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{library.name}-",
                                    dir=str(target.parent)))
    try:
        total = len(library.assets)
        for index, asset in enumerate(library.assets, start=1):
            body = _download(_asset_url(library, asset))
            if asset.sha256:
                got = hashlib.sha256(body).hexdigest()
                if got != asset.sha256:
                    raise WebLibError(
                        f"{library.name}/{asset.filename} does not match the "
                        f"expected checksum — it was not installed "
                        f"(expected {asset.sha256[:12]}…, got {got[:12]}…)")
            (staging / asset.filename).write_bytes(body)
            if progress is not None:
                progress(index, total, asset.filename)

        (staging / "flograph-weblib.json").write_text(json.dumps({
            "name": library.name, "title": library.title,
            "version": library.version, "summary": library.summary,
            "license": library.license, "homepage": library.homepage,
            "assets": [{"filename": a.filename, "url": a.url,
                        "sha256": a.sha256, "size": a.size}
                       for a in library.assets],
        }, indent=2), encoding="utf-8")

        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        staging.rename(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return library


def add_from_url(name: str, urls: Iterable[str], version: str = "custom",
                 title: str = "", progress=None) -> Library:
    """Install a library that isn't in the catalogue, from URLs.

    The escape hatch, and the reason the catalogue does not have to be
    exhaustive to be useful. Nothing is checksummed — the user chose the
    source, so the user is the authority on it — but it is stored, recorded
    and rendered exactly like a catalogue library, so a node cannot tell
    the difference.
    """
    import posixpath
    import urllib.parse

    assets = []
    for url in urls:
        # The filename comes from the URL's *path*, so a bare host doesn't
        # quietly become a file called after the domain — which is what a
        # trailing-slash URL would otherwise produce. An extension is
        # required because that is what says which kind of tag it becomes.
        path = urllib.parse.urlsplit(url).path
        filename = posixpath.basename(path)
        if not filename or "." not in filename:
            raise WebLibError(
                f"can't tell a filename from {url!r} — the URL should end in "
                f"the file to fetch, like …/d3.min.js")
        assets.append(Asset(filename=filename, url=url))
    if not assets:
        raise WebLibError("no URLs given")

    library = Library(name=name, title=title or name, version=version,
                      summary="added from a URL", assets=tuple(assets))
    # install() reads the catalogue, so hand it this one through the same
    # manifest path a re-install would use.
    saved = CATALOGUE.get(name)
    CATALOGUE[name] = library
    try:
        return install(name, progress=progress)
    finally:
        if saved is None:
            CATALOGUE.pop(name, None)
        else:
            CATALOGUE[name] = saved


def remove(name: str) -> bool:
    """Delete every installed version of `name`. True if anything went."""
    import shutil
    root = store_dir() / name
    if not root.is_dir():
        return False
    shutil.rmtree(root, ignore_errors=True)
    return not root.exists()


# ------------------------------------------------------------- into a page

def markup(*names: str, mode: str = LINK) -> str:
    """The `<script>`/`<link>` tags that put these libraries into a page.

    This is what a node calls. Raises MissingLibrary — never a remote URL —
    when one isn't installed, which is the whole point of the module.

    Order is preserved, and a library's own assets come out stylesheets
    first: a script that draws on load would otherwise paint before its CSS
    arrives.
    """
    if mode not in (LINK, INLINE):
        raise WebLibError(f"unknown mode {mode!r}")
    out = []
    for name in names:
        library = known(name)
        if library is None or not is_installed(name):
            raise MissingLibrary(name)
        directory = library_dir(library.name, library.version)
        for asset in sorted(library.assets, key=lambda a: not a.is_stylesheet):
            path = directory / asset.filename
            if mode == INLINE:
                try:
                    source = path.read_text(encoding="utf-8", errors="replace")
                except OSError as exc:
                    raise WebLibError(
                        f"could not read {path} — {exc}") from None
                out.append(f"<style>{source}</style>" if asset.is_stylesheet
                           else f"<script>{source}</script>")
            else:
                url = path.as_uri()
                out.append(
                    f'<link rel="stylesheet" href="{url}">'
                    if asset.is_stylesheet else f'<script src="{url}"></script>')
    return "\n".join(out)


#: Matches the tags markup(LINK) writes, so an export can find the store
#: references in a finished page without the node having to co-operate.
_LOCAL_TAG = (
    r'<script src="(file://[^"]+)"></script>'
    r'|<link rel="stylesheet" href="(file://[^"]+)">'
)


def _store_paths(html: str):
    """Every (whole tag, path) in `html` that points into the store.

    Confined to the store on purpose: an export rewrites the libraries
    flograph installed, and leaves any other file:// the page happens to
    carry exactly as the node wrote it.
    """
    import re
    import urllib.parse
    import urllib.request

    root = str(store_dir().resolve())
    for match in re.finditer(_LOCAL_TAG, html):
        uri = match.group(1) or match.group(2)
        path = Path(urllib.request.url2pathname(
            urllib.parse.urlsplit(uri).path))
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if str(resolved).startswith(root) and resolved.is_file():
            yield match.group(0), resolved


def inline_page(html: str) -> str:
    """One self-contained page: every installed library pasted in.

    What "save this view as an HTML file" should produce — a single file
    that opens on a machine with no flograph, no store and no internet.
    The card keeps using `file://` references (a 3 MB library re-embedded
    on every run would be absurd); this is the one-off conversion at the
    point where the page stops being ours.
    """
    for tag, path in list(_store_paths(html)):
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        replacement = (f"<style>{source}</style>"
                       if path.suffix.lower() == ".css"
                       else f"<script>{source}</script>")
        html = html.replace(tag, replacement)
    return html


def bundle_page(html: str, folder, assets_dir: str = "assets") -> tuple:
    """Write the page's libraries beside it and point the page at them.

    The other half of exporting: a folder you can drop on a share or a
    static host. Returns `(rewritten page, files written)` — the caller
    writes the *returned* html, not the one it passed in.

    The rewritten hrefs are relative, so the folder works wherever it is
    put, which a `file://` path pointing at the author's home directory
    very much does not.
    """
    import shutil

    folder = Path(folder)
    target = folder / assets_dir
    written = []
    for tag, path in list(_store_paths(html)):
        target.mkdir(parents=True, exist_ok=True)
        destination = target / path.name
        if not destination.exists():
            shutil.copy2(path, destination)
            written.append(destination)
        href = f"{assets_dir}/{path.name}"
        replacement = (f'<link rel="stylesheet" href="{href}">'
                       if path.suffix.lower() == ".css"
                       else f'<script src="{href}"></script>')
        html = html.replace(tag, replacement)
    return html, written


def require(*names: str) -> None:
    """Raise MissingLibrary unless every named library is installed.

    For a node that wants to fail before doing expensive work rather than
    after building a figure it can't render.
    """
    for name in names:
        if not is_installed(name):
            raise MissingLibrary(name)

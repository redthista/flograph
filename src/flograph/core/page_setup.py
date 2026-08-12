"""How a report sits on the page: size, margins, a cover, headers and feet.

Deliberately Qt-free, and deliberately *not* expressed in Qt's vocabulary.

There are two renderers in this project's future and only one of them
exists yet. Today a report is laid out by Qt and printed by QPdfWriter; the
shelved plan (ideas_archived.md, item 8) is a second export target that
renders the same report through a Jinja template and CSS, where this becomes
`@page` rules and running elements. Anything expressed as a QPageSize or a
QMarginsF would have to be invented a second time for that path — and the
settings surface is the expensive half of this feature, not the printing.

So: millimetres and plain strings here, `page_css()` for the CSS side, and
`ui/report/export.py` converting to Qt at the last moment.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, fields

#: Named page sizes, in millimetres, portrait (width, height).
#:
#: A short list on purpose. These are the sizes people actually export a
#: report to; the full ISO range would be a longer menu that answers no
#: question anyone asked. `size` is a plain string, so a file naming a size
#: this build doesn't know still loads — it just falls back to A4.
PAGE_SIZES: dict[str, tuple[float, float]] = {
    "A3": (297.0, 420.0),
    "A4": (210.0, 297.0),
    "A5": (148.0, 210.0),
    "Letter": (215.9, 279.4),
    "Legal": (215.9, 355.6),
    "Tabloid": (279.4, 431.8),
}

DEFAULT_SIZE = "A4"

#: Generous enough that a printer's unprintable edge can't clip the text,
#: and close to what a word processor would default to.
DEFAULT_MARGIN_MM = 15.0

#: One point in millimetres. Page geometry is authored in mm (what a page
#: is measured in) and drawn in points (what a QTextDocument's fonts are
#: measured in) — see RESOLUTION in ui/report/export.py.
MM_PER_POINT = 25.4 / 72.0

#: Vertical room reserved for a running header or footer, in points —
#: enough for one line of the default 9pt text plus the gap that keeps it
#: from touching the body. Only taken out of the body when that band has
#: something in it, so a report with no header loses nothing to one.
BAND_HEIGHT = 22.0

#: Point size for header and footer text: smaller than the body, which is
#: what makes a running element read as furniture rather than as content.
BAND_FONT_SIZE = 9.0

#: What `{...}` in a header, footer or cover field expands to. Kept as a
#: tuple so the dialog can list them without knowing how they are filled.
FIELDS = (
    ("{page}", "the page number"),
    ("{pages}", "how many pages there are"),
    ("{title}", "the page's title"),
    ("{date}", "today's date"),
)


@dataclass
class PageSetup:
    """The page geometry of one report. Saved with the project.

    Every field has a default that reproduces exactly what reports did
    before this existed — A4 portrait, 15mm all round, no cover, no running
    header or footer — so a project written by an older build opens
    unchanged, and so does one where nobody has opened the dialog.
    """

    size: str = DEFAULT_SIZE
    landscape: bool = False

    # Millimetres, per edge. Four values rather than one because the common
    # reason to change a margin at all is binding room down one side.
    margin_top: float = DEFAULT_MARGIN_MM
    margin_right: float = DEFAULT_MARGIN_MM
    margin_bottom: float = DEFAULT_MARGIN_MM
    margin_left: float = DEFAULT_MARGIN_MM

    # A cover is a page of its own before the body: title, an optional line
    # under it, and an optional date. It is not part of the markdown, so
    # turning it off doesn't disturb what was written.
    cover: bool = False
    cover_title: str = ""        # "" = use the page's own title
    cover_subtitle: str = ""
    cover_date: bool = True

    # Running elements. Left/centre/right per band, because that is how a
    # header is actually composed — a title on one side, a page number on
    # the other — and one string could not say it.
    header_left: str = ""
    header_center: str = ""
    header_right: str = ""
    footer_left: str = ""
    footer_center: str = ""
    footer_right: str = ""

    #: Whether the running elements appear on the first body page. Off is
    #: the usual typographic choice when there is no cover: a header over
    #: the title of a two-page report is noise.
    bands_on_first_page: bool = True

    #: What the first body page is numbered. The cover, when there is one,
    #: is never numbered and never counted — it is a cover, not page 1.
    first_page_number: int = 1

    # -------------------------------------------------------------- geometry

    def page_mm(self) -> tuple[float, float]:
        """(width, height) of the sheet in mm, orientation applied."""
        width, height = PAGE_SIZES.get(self.size, PAGE_SIZES[DEFAULT_SIZE])
        return (height, width) if self.landscape else (width, height)

    def body_mm(self) -> tuple[float, float]:
        """(width, height) inside the margins, in mm.

        Clamped rather than allowed to go negative: margins are typed into
        a dialog, and a body of negative width would divide by zero
        somewhere far away from the spin box that caused it.
        """
        width, height = self.page_mm()
        return (max(10.0, width - self.margin_left - self.margin_right),
                max(10.0, height - self.margin_top - self.margin_bottom))

    def body_width_points(self) -> int:
        """The body width in points — the width a figure is drawn at.

        This is why page setup has to reach the *preview* and not only the
        PDF writer: charts are raster by the time they reach the document,
        so the width they are drawn at is decided before anyone can see
        whether it fits. Get it from the page, and the preview shows the
        proportions the export will really have.
        """
        return int(round(self.body_mm()[0] / MM_PER_POINT))

    def has_header(self) -> bool:
        return any((self.header_left, self.header_center, self.header_right))

    def has_footer(self) -> bool:
        return any((self.footer_left, self.footer_center, self.footer_right))

    def header_fields(self) -> tuple[str, str, str]:
        return (self.header_left, self.header_center, self.header_right)

    def footer_fields(self) -> tuple[str, str, str]:
        return (self.footer_left, self.footer_center, self.footer_right)

    # --------------------------------------------------------- serialization

    def to_dict(self) -> dict:
        """Only what differs from the defaults.

        A page that has never been near the dialog then adds nothing at all
        to the project file, which keeps a diff of a saved project about
        what the user changed.
        """
        defaults = PageSetup()
        return {f.name: getattr(self, f.name) for f in fields(self)
                if getattr(self, f.name) != getattr(defaults, f.name)}

    @classmethod
    def from_dict(cls, data) -> "PageSetup":
        """Rebuild from a saved dict, ignoring anything unrecognised.

        Forward compatibility matters more here than validation: a project
        saved by a later build that grew a field should still open, minus
        the field this build has never heard of.
        """
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in fields(cls)}
        setup = cls(**{k: v for k, v in data.items() if k in known})
        setup.normalize()
        return setup

    def copy(self) -> "PageSetup":
        return PageSetup(**asdict(self))

    def normalize(self) -> None:
        """Pull a hand-edited or future-built file into range.

        Types as well as values: a JSON file is a text format anyone may
        edit, and a margin that arrives as a string would otherwise fail
        much later, inside a paint call.
        """
        if self.size not in PAGE_SIZES:
            self.size = DEFAULT_SIZE
        self.landscape = bool(self.landscape)
        self.cover = bool(self.cover)
        self.cover_date = bool(self.cover_date)
        self.bands_on_first_page = bool(self.bands_on_first_page)
        for name in ("margin_top", "margin_right",
                     "margin_bottom", "margin_left"):
            try:
                value = float(getattr(self, name))
            except (TypeError, ValueError):
                value = DEFAULT_MARGIN_MM
            # 0 is legal (borderless), 100mm is past any sane binding edge
            setattr(self, name, min(100.0, max(0.0, value)))
        try:
            self.first_page_number = max(0, int(self.first_page_number))
        except (TypeError, ValueError):
            self.first_page_number = 1
        # The text fields are drawn straight into a QPainter, which will not
        # accept a number where it wants a string.
        for f in fields(self):
            if f.name.startswith(("header_", "footer_")) \
                    or f.name in ("cover_title", "cover_subtitle"):
                value = getattr(self, f.name)
                setattr(self, f.name, "" if value is None else str(value))


def expand(text: str, page: int, pages: int, title: str,
           date: str) -> str:
    """Replace the `{...}` fields in a header, footer or cover line.

    A plain string replace rather than str.format: the text is typed by a
    user, and `format` would raise on a stray brace — or, worse, reach into
    an attribute. Unknown fields are left as written so a typo shows on the
    page instead of disappearing.
    """
    if not text:
        return ""
    return (text.replace("{page}", str(page))
                .replace("{pages}", str(pages))
                .replace("{title}", title or "")
                .replace("{date}", date or ""))


def today() -> str:
    """The date a report is exported, in the machine's own locale format."""
    from datetime import date as _date
    return _date.today().strftime("%d %B %Y")


def page_css(setup: PageSetup) -> str:
    """The `@page` rule this setup describes.

    Unused by the Qt export — it is here because it is the reason this
    module is shaped the way it is. If the HTML/Jinja export lands
    (ideas_archived.md item 8) this is the whole of the geometry half, and
    the fact
    that it can be written now, from this dataclass alone, is what says the
    settings surface was designed once rather than per backend.
    """
    width, height = setup.page_mm()
    return (
        "@page {\n"
        f"  size: {width:g}mm {height:g}mm;\n"
        f"  margin: {setup.margin_top:g}mm {setup.margin_right:g}mm "
        f"{setup.margin_bottom:g}mm {setup.margin_left:g}mm;\n"
        "}\n"
    )

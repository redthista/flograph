"""Scrollytelling: prose that scrolls past a visual that keeps up.

A **story** is a run of steps. Each step is a paragraph or two, and each
step points at a **scene** — a finished page from another visual node. On a
screen the scenes sit still while the prose scrolls past them, and the scene
changes when the step that owns it arrives. It is the shape a newsroom
graphics desk builds by hand for an election night or a budget.

Three decisions hold this module up.

**The base document is an article, and JavaScript upgrades it.** The markup
this module writes is a picture followed by the steps that talk about it,
down one column — a perfectly ordinary illustrated article that reads top to
bottom with no script running at all. `SCRIPT` then lifts every scene into
the sticky stage and turns that article into the scrolling story. Nothing is
duplicated to make the two layouts, and the fallback is not a degraded mode
anybody had to design separately: it is the document.

**A scene is an `<iframe srcdoc>`, not inlined markup.** Every visual node
emits a *complete* page — its own `:root` variables, its own `body` rules —
and six complete pages cannot share one document without colliding. An
iframe is the only honest container. It buys something better than
isolation, too: an iframe **is a viewport**, so a chart written against
`100vh` (which is every visual `core.svgplot` draws — see that module on
why) resolves it against the pane it has been given. Measured through the
real `printToPdf` path, not assumed.

**`window.innerHeight` decides which layout runs.** A report snapshot lays
the page out in a view that has never been shown, where the viewport
measures **zero** — the same zero that makes any self-fitting page
impossible there. So it is also the signal: no viewport means no scrolling,
and a story that cannot be scrolled should be read as the article. The check
is one line in `SCRIPT`, and it is why a report gets prose and pictures
instead of one frozen frame of a scroll that never happened.
"""
from __future__ import annotations

import re
from typing import Any, Optional

#: How many scenes a story can hold. Six is a long story; the ports have to
#: be declared up front, and a node with a dozen unused pins reads worse
#: than a story that asks you to pick your six best moments.
MAX_SCENES = 6

#: A line of three or more dashes, alone, ends a step.
_BREAK = re.compile(r"^[ \t]*-{3,}[ \t]*$", re.M)

#: `@scene 3`, on its own line, points the step it appears in at a scene.
#: The newline goes with it. Left behind, it turns the one paragraph the
#: mark was sitting in the middle of into two.
_SCENE = re.compile(r"^[ \t]*@scene[ \t]+(\d+)[ \t]*(?:\n|$)", re.M | re.I)

#: A heading is a whole line and only ever a line — see `prose`.
_HEADING = re.compile(r"^[ \t]*(#{1,6})[ \t]*(.*)$")

_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
_BOLD = re.compile(r"\*\*(\S(?:[^*]*\S)?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(\S(?:[^*]*\S)?)\*(?![\w*])")
_CODE = re.compile(r"`([^`]+)`")


class StoryError(ValueError):
    """A story that cannot be built."""


def attribute(text: Any) -> str:
    """Escape a whole HTML document so it can live in a `srcdoc=""`.

    The ampersand has to go first or it eats the escapes that follow it —
    the oldest bug in this family, and a silent one: the page still loads,
    with `&amp;quot;` where the quotes were.
    """
    return (str(text).replace("&", "&amp;").replace('"', "&quot;")
            .replace("'", "&#39;").replace("<", "&lt;").replace(">", "&gt;"))


def escape(text: Any) -> str:
    """HTML-escape a value on its way into markup."""
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def split_steps(text: str) -> list[str]:
    """The Steps box as a list of blocks, split on a line of `---`.

    Blank blocks are dropped, so a trailing separator or a doubled one is
    not a step with nothing in it.
    """
    if not str(text or "").strip():
        return []
    return [block.strip() for block in _BREAK.split(str(text))
            if block.strip()]


def scene_marker(text: str) -> tuple[str, Optional[int]]:
    """Pull an `@scene N` line out of a block.

    Returns the block without it and the scene number, or None if the block
    did not name one. The last marker wins, which is the forgiving reading
    of a block someone has edited twice.
    """
    found = _SCENE.findall(str(text or ""))
    cleaned = _SCENE.sub("", str(text or "")).strip()
    if not found:
        return cleaned, None
    return cleaned, int(found[-1])


def prose(text: str) -> str:
    """A step's text as HTML: blank lines are paragraphs, `#` is a heading.

    Two rules here are the ones people actually expect from writing prose
    anywhere else, and getting either wrong is obvious the moment a story
    is looked at rather than asserted about.

    **A heading is a line, not a block.** Nobody leaves a blank line under a
    heading before typing the sentence it introduces, so a heading that ran
    to the end of its block swallowed the paragraph and set the whole thing
    in 24pt bold.

    **A single newline is a space.** The Steps box is a few inches wide and
    everyone hard-wraps in it; honouring those breaks literally puts a
    ragged short line in the middle of every paragraph. Two trailing spaces
    or a trailing backslash still force one, the same convention markdown
    uses, for an address or a line of verse.

    Deliberately **not escaping**. The Steps box is markup, the same way
    HTML Template's Template box is — anything typed there is the author's
    own, and a story that could not carry a `<span>` would send people
    straight to Extra CSS to get one back. Values coming *in* through
    `{{tokens}}` are escaped by the template engine before they ever reach
    here, which is where escaping belongs.
    """
    out: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if not buffer:
            return
        if buffer[0].lstrip().startswith("<"):
            out.append("\n".join(buffer))       # already markup; leave it
        else:
            out.append(f"<p>{_inline(_join(buffer))}</p>")
        buffer.clear()

    for line in str(text or "").splitlines():
        if not line.strip():
            flush()
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            said = _inline(heading.group(2).strip())
            tag = ("h2 class='step-title'" if level == 1
                   else "h3" if level == 2 else "h4")
            out.append(f"<{tag}>{said}</{tag.split()[0]}>")
            continue
        buffer.append(line)
    flush()
    return "".join(out)


def _join(lines: list[str]) -> str:
    """One paragraph's lines into one line, honouring hard breaks."""
    pieces = []
    for index, line in enumerate(lines):
        hard = line.endswith("  ") or line.rstrip("\n").endswith("\\")
        pieces.append(line.strip().rstrip("\\").strip())
        if index < len(lines) - 1:
            pieces.append("<br>" if hard else " ")
    return "".join(pieces)


def _inline(text: str) -> str:
    """`**bold**`, `*italic*`, `` `code` `` and `[text](url)`."""
    text = _CODE.sub(r"<code>\1</code>", text)
    text = _LINK.sub(r'<a href="\2">\1</a>', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


def assign_scenes(wanted: list[Optional[int]], available: int) -> list[int]:
    """Which scene each step shows, given what each step asked for.

    A step that named one gets it. A step that named nothing follows the
    step before it — *not* the next scene along, because "three paragraphs
    about the same chart" is the commonest thing a story does and it should
    need no marks at all after the first. The very first step falls back to
    scene 1.

    Out-of-range numbers are clamped rather than raised: a story wired to
    four visuals and written for six should still tell four visuals' worth
    of story, and the node logs what it clamped.
    """
    if available <= 0:
        return [0] * len(wanted)
    out: list[int] = []
    current = 1
    for index, ask in enumerate(wanted):
        if ask is None:
            # Nothing said: the first step opens on scene 1, and every
            # later step stays where the story already was.
            current = current if index else 1
        else:
            current = max(1, min(available, int(ask)))
        out.append(current)
    return out


def steps_from_rows(rows: list[dict], text_column: str,
                    scene_column: str = "") -> list[tuple[str, Optional[int]]]:
    """One step per row: its prose, and the scene it asked for."""
    steps = []
    for row in rows:
        raw = row.get(text_column) if text_column else None
        text = "" if raw is None else str(raw)
        if isinstance(raw, float) and raw != raw:      # NaN reads as "nan"
            text = ""
        text, marked = scene_marker(text)
        asked = marked
        if scene_column:
            number = _to_int(row.get(scene_column))
            if number is not None:
                asked = number
        steps.append((text, asked))
    return steps


def _to_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, float) and value != value:
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


#: The whole layout, both of them. Read `.story` as the article and
#: `.story.live` as what JavaScript turns it into.
CSS = """
.wrap{max-width:var(--reading);margin:0 auto}
.story-head{margin:0 0 calc(var(--gap) * 1.2)}
.story-head .subtitle{margin-top:6px;max-width:62ch}

/* The article. This is the document: a picture, then the steps that talk
   about it. It is what a report prints, what a page with no JavaScript
   shows, and what somebody sees who saved the file and opened it in a
   browser with scripting off. */
.story{display:block}
.stage{display:none}
.scene{aspect-ratio:var(--ratio);margin:var(--gap) 0;overflow:hidden;
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);break-inside:avoid}
.scene iframe{width:100%;height:100%;border:0;display:block}
.step{break-inside:avoid;margin:0 0 var(--gap);max-width:68ch}
.step-title{font-size:calc(var(--size) * 1.5);line-height:1.2;
  margin:0 0 .3em}
.step p{margin:0 0 .7em}
.step p:last-child{margin-bottom:0}
.step .note{color:var(--muted);font-size:calc(var(--size) * .86)}

/* The story. `live` is added by SCRIPT once it has moved every scene into
   the stage, so none of this can apply to a page whose script never ran. */
.story.live{display:flex;align-items:flex-start;gap:calc(var(--gap) * 2)}
.story.live.prose-left{flex-direction:row-reverse}
.story.live .stage{display:block;position:sticky;top:var(--pad);
  flex:1 1 auto;min-width:0;height:calc(100vh - var(--pad) * 2)}
.story.live .stage .scene{position:absolute;inset:0;margin:0;opacity:0;
  aspect-ratio:auto;pointer-events:none;transition:opacity .45s ease}
.story.live .stage .scene.on{opacity:1;pointer-events:auto}
.story.live.cut .stage .scene{transition:none}
.story.live .prose{flex:0 0 var(--prose);min-width:0}
.story.live .step{min-height:calc(100vh - var(--pad) * 2);max-width:none;
  margin:0;display:flex;flex-direction:column;justify-content:center;
  opacity:.34;transition:opacity .3s ease}
.story.live .step.here{opacity:1}
/* The last step needs somewhere to scroll to, or it can never reach the
   middle of the viewport and the final scene never arrives. */
.story.live .prose::after{content:"";display:block;height:32vh}

.live-rail{display:none}
.live-rail.on{display:block;position:fixed;left:0;top:0;height:3px;
  width:100%;z-index:9}
.live-rail i{display:block;height:100%;width:0;background:var(--accent);
  transition:width .1s linear}

/* Printing from a browser, where the script has already run. Everything
   the stage is doing has to be undone, or a sticky full-height pane prints
   as one frame with the rest of the story after it. */
@media print{
  .story.live{display:block}
  .story.live .stage{display:none}
  .story.live .prose{flex:none}
  .story.live .step{min-height:0;opacity:1;display:block;
    margin:0 0 var(--gap);break-inside:avoid}
  .story.live .prose::after{display:none}
  .live-rail.on{display:none}
}
"""

#: The upgrade. Everything it does is reversible by not running it.
SCRIPT = """
<script>
(function () {
  var story = document.getElementById('story');
  var stage = document.getElementById('stage');
  if (!story || !stage) { return; }

  // No viewport, no scrolling. A report snapshot lays the page out in a
  // view that was never shown, and there innerHeight is 0 — so the article
  // already in the document is the right thing to leave alone. This is the
  // same zero that makes a self-fitting page impossible on that path; here
  // it is useful.
  if (!window.innerHeight) { return; }

  var scenes = Array.prototype.slice.call(story.querySelectorAll('.scene'));
  scenes.forEach(function (scene) { stage.appendChild(scene); });
  story.classList.add('live');

  var steps = Array.prototype.slice.call(story.querySelectorAll('.step'));
  var rail = document.querySelector('.live-rail');
  var bar = rail ? rail.querySelector('i') : null;
  var showing = null;

  function show(step) {
    var want = step.getAttribute('data-scene');
    steps.forEach(function (other) {
      other.classList.toggle('here', other === step);
    });
    if (want === showing) { return; }
    showing = want;
    scenes.forEach(function (scene) {
      scene.classList.toggle('on', scene.getAttribute('data-scene') === want);
    });
  }

  if (steps.length) { show(steps[0]); }

  if (window.IntersectionObserver) {
    // A thin band across the middle of the viewport: a step becomes the
    // one being read when it crosses the middle, not when it appears.
    var watcher = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) { show(entry.target); }
      });
    }, {rootMargin: '-45% 0px -45% 0px', threshold: 0});
    steps.forEach(function (step) { watcher.observe(step); });
  }

  if (bar) {
    rail.classList.add('on');
    var draw = function () {
      var run = document.documentElement.scrollHeight - window.innerHeight;
      var at = run > 0 ? window.pageYOffset / run : 0;
      bar.style.width = Math.max(0, Math.min(1, at)) * 100 + '%';
    };
    window.addEventListener('scroll', draw, {passive: true});
    draw();
  }
}());
</script>
"""


def scene_markup(page: str, number: int) -> str:
    """One scene: a complete page sealed inside its own iframe.

    `loading="eager"` is deliberate. The lazy default leaves a frame
    unloaded until it scrolls near the viewport, and a scene in the stage
    never scrolls anywhere — it fades in already there, and would fade in
    blank.
    """
    return (f"<div class='scene' data-scene='{int(number)}'>"
            f"<iframe loading='eager' referrerpolicy='no-referrer' "
            f"title='Scene {int(number)}' "
            f"srcdoc=\"{attribute(page)}\"></iframe></div>")


def body(head: str, steps: list[tuple[str, int]], pages: list[str], *,
         prose_side: str = "left", transition: str = "fade",
         rail: bool = True) -> str:
    """Assemble the whole page body.

    Each scene is written **inside the prose column, at the first step that
    uses it** — which is what makes the article read as an article, picture
    before the words about it, rather than as a wall of text with the plates
    collected at the end.
    """
    classes = ["story"]
    if str(prose_side).lower() == "left":
        classes.append("prose-left")
    if str(transition).lower() == "cut":
        classes.append("cut")

    placed: set[int] = set()
    blocks = []
    for text, scene in steps:
        if scene and scene not in placed and 1 <= scene <= len(pages):
            placed.add(scene)
            blocks.append(scene_markup(pages[scene - 1], scene))
        blocks.append(f"<section class='step' data-scene='{scene or 0}'>"
                      f"{text}</section>")

    # A scene nobody pointed at still belongs in the document — it was wired
    # in on purpose, and dropping it silently would look like the port had
    # not worked.
    for index, page in enumerate(pages, 1):
        if index not in placed:
            blocks.append(scene_markup(page, index))

    return (f"<div class='wrap'>{head}"
            f"<div class='{' '.join(classes)}' id='story'>"
            f"<div class='stage' id='stage'></div>"
            f"<div class='prose'>{''.join(blocks)}</div>"
            f"</div></div>"
            + ("<div class='live-rail'><i></i></div>" if rail else "")
            + SCRIPT)

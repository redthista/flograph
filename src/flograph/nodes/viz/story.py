"""Story

**Scrollytelling.** The words scroll; the picture beside them keeps up. Wire
up to six visuals into the **scene** ports, write the story in **Steps**, and
each step brings its own scene forward as you reach it — the shape a
newsroom graphics desk builds by hand for an election night or a budget.

It is the last piece of the visuals set, and the only one that is not a
chart. Everything else on the board answers a question; this one **puts the
answers in an order and says what they mean**. A dashboard is read in any
order and a report is read once — a story is read the way it was written.

**Steps** is the story, one block per step, separated by a line of three
dashes:

    # Revenue grew almost everywhere
    Eleven of the twelve regions ended the year above where they
    started. **The North East gained the most**, at 31%.
    ---
    @scene 2
    ## Except London
    It fell in three quarters out of four.

A blank line starts a paragraph, a leading `#` is a heading (`##` and `###`
are smaller ones), and `**bold**`, `*italic*`, `` `code` `` and
`[text](url)` do what they look like. Anything else you type is passed
through as markup, so a `<span class="chip bad">` is yours to use — the
class names are HTML Template's, and Visual Style sets them.

**Which scene a step shows.** The first step opens on scene 1, and **every
step after it stays where the story already was** until one says otherwise —
so three paragraphs about the same chart need no marks at all. `@scene 3` on
its own line moves it. That default is the right way round: a story
lingers far more often than it cuts.

**From a table instead.** Wire a table into **steps** and you get one step
per row, with the prose from **Text column** and, if you have one, the scene
number from **Scene column**. The text is a template — `{{region}}` and
`{{growth:.1f}}%` resolve against that row — so a story can be *written by
the data*: sort the regions by growth, and the story tells itself in the
right order every time the numbers change.

**Scenes are sealed.** Each one is a complete page from another node, held
in its own frame, so six visuals with six sets of colours and fonts cannot
tread on each other. It also means a scene gets a **real viewport of its
own**, which is what lets the drawn-in-Python charts fill their pane exactly
as they do on their own card.

Ports are numbered by **what is actually wired**, skipping empty ones — wire
three visuals into scene 1, 3 and 4 and they are scenes 1, 2 and 3. The log
says which port became which scene.

**On paper it is an article.** A story is a scroll, and a report is a
rectangle, so there is nothing to freeze a scroll into. What the page does
instead is more useful: underneath the scrolling it *is* an ordinary
illustrated article — a picture, then the steps that talk about it, down one
column — and that is what a report prints, what somebody with JavaScript
switched off reads, and what comes out of **Save View as HTML…**. The
scrolling is an upgrade applied on top when there is a viewport to scroll
in. So the same node is a story on screen and a spread on paper, and neither
was designed as the consolation prize.

Give a report embed a generous `height=` for that: a report shows the top of
the card's box, so a story printed into 300px is a headline and a picture.

**It travels.** Nothing is fetched — no font link, no script, no stylesheet
— so what the card shows is what lands in a dashboard tile and what a
colleague sees when you send them the file.
"""
from flograph.core.story import MAX_SCENES

NODE = {
    "label": "Story",
    "category": "Viz",
    "version": "1.0",
    "card": "webview",
    "inputs": ([("steps", "dataframe", {"optional": True}),
                ("style", "object", {"optional": True})]
               + [(f"scene{n}", "string", {"optional": True})
                  for n in range(1, MAX_SCENES + 1)]),
    "outputs": [("html", "string"), ("style", "object")],
}

_RATIOS = ("16:10", "16:9", "3:2", "4:3", "1:1")

PARAMS = [
    {"name": "more", "type": "bool", "label": "More options",
     "default": False, "cosmetic": True},

    {"name": "title", "type": "string", "label": "Title", "default": "",
     "placeholder": "the headline across the top"},
    {"name": "subtitle", "type": "string", "label": "Standfirst",
     "default": "", "placeholder": "a line or two under the headline"},
    {"name": "steps", "type": "text", "label": "Steps", "default": "",
     "placeholder": "# First step\nWhat this scene shows.\n---\n@scene 2\n"
                    "# Second step\nWhat changed."},

    {"name": "prose_side", "type": "choice", "label": "Words on the",
     "options": ["left", "right"], "default": "left"},
    {"name": "prose_width", "type": "int", "label": "Words take %",
     "default": 38, "min": 22, "max": 65},
    {"name": "transition", "type": "choice", "label": "Scene change",
     "options": ["fade", "cut"], "default": "fade"},

    {"name": "text_column", "type": "columns", "label": "Text column",
     "multi": False, "default": "",
     "placeholder": "(when a table is wired in)"},
    {"name": "scene_column", "type": "columns", "label": "Scene column",
     "multi": False, "default": "", "placeholder": "(optional)"},

    {"name": "progress", "type": "bool", "label": "Progress bar",
     "default": True},
    {"name": "ratio", "type": "choice", "label": "Picture shape",
     "options": list(_RATIOS), "default": "16:10",
     "visible_when": {"more": ["True"]}},
    {"name": "reading_width", "type": "int", "label": "Reading width",
     "default": 1180, "min": 0, "max": 3000,
     "visible_when": {"more": ["True"]}},
    {"name": "bindings", "type": "text", "label": "Bindings", "default": "",
     "placeholder": "best = max(growth)", "visible_when": {"more": ["True"]}},
    {"name": "css", "type": "text", "label": "Extra CSS", "default": "",
     "placeholder": ".step-title{color:var(--accent)}",
     "visible_when": {"more": ["True"]}},

    {"name": "width", "type": "int", "label": "Width", "default": 760,
     "min": 260, "max": 1600, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height", "default": 560,
     "min": 200, "max": 2000, "cosmetic": True},
    {"name": "scale", "type": "int", "label": "Scale %", "default": 100,
     "min": 25, "max": 400, "cosmetic": True},
]

_EMPTY = """
<div class="card stack">
  <div class="label">Story</div>
  <p>Write the story in <strong>Steps</strong> — one block per step,
     separated by a line of three dashes — or wire a table of steps into
     <strong>steps</strong>.</p>
  <p class="muted">Then wire a visual's <strong>html</strong> output into
     <strong>scene 1</strong>, and it appears beside the words.</p>
</div>
"""


def _text_column(rows, params):
    """Which column holds the prose.

    Named wins; otherwise the widest text column, because the prose is
    almost always the longest thing in the row and guessing the *first*
    text column picks the label instead.
    """
    names = list(rows[0].keys()) if rows else []
    chosen = str(params.get("text_column", "") or "").strip()
    if chosen:
        if names and chosen not in names:
            raise ValueError(f"Text column {chosen!r} is not in the table "
                             f"(has: {', '.join(names)})")
        return chosen

    def length(name):
        seen = [row.get(name) for row in rows[:40]]
        text = [len(str(v)) for v in seen if isinstance(v, str)]
        return sum(text) / len(text) if text else -1.0

    ranked = sorted(names, key=lambda n: (-length(n), names.index(n)))
    return ranked[0] if ranked and length(ranked[0]) >= 0 else ""


def run(ctx, steps=None, style=None, scene1=None, scene2=None, scene3=None,
        scene4=None, scene5=None, scene6=None):
    from flograph.core import infographic, story, visual_style

    params = ctx.params

    # Numbered by what is wired, not by which pin it arrived on. A hole in
    # the middle is far more likely to be "I unplugged one" than "I meant
    # scene 2 to be blank", and the log names the mapping either way.
    ports = [("scene1", scene1), ("scene2", scene2), ("scene3", scene3),
             ("scene4", scene4), ("scene5", scene5), ("scene6", scene6)]
    pages, wired = [], []
    for name, value in ports:
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            ctx.log(f"{name}: not a page, ignored")
            continue
        pages.append(value)
        wired.append(name)
    if wired and wired != [f"scene{n}" for n in range(1, len(wired) + 1)]:
        ctx.log("scenes numbered by what is wired: "
                + ", ".join(f"{port} is scene {n}"
                            for n, port in enumerate(wired, 1)))

    merged_style = visual_style.merge_styles(
        style if visual_style.is_style(style) else None, None)
    tok = visual_style.tokens(merged_style)

    rows = infographic.rows_from_frame(steps)
    bindings = str(params.get("bindings", "") or "")
    unresolved: list[str] = []

    def fill(text, index=0):
        """A step's text through the template engine, then to markup."""
        if not str(text or "").strip():
            return ""
        out, missing = infographic.render(
            str(text), rows, bindings=bindings, row=index,
            palette=tok["palette"],
            values={"_n": index + 1, "_count": max(len(rows), 1)})
        unresolved.extend(missing)
        return out

    if rows:
        column = _text_column(rows, params)
        scene_column = str(params.get("scene_column", "") or "").strip()
        if scene_column and scene_column not in rows[0]:
            raise ValueError(f"Scene column {scene_column!r} is not in the "
                             f"table (has: {', '.join(rows[0])})")
        raw = story.steps_from_rows(rows, column, scene_column)
        written = [(fill(text, index), asked)
                   for index, (text, asked) in enumerate(raw)]
        ctx.log(f"{len(written)} step(s) from the table, prose from "
                f"{column or '(no column)'}")
    else:
        blocks = story.split_steps(params.get("steps", ""))
        raw = [story.scene_marker(block) for block in blocks]
        written = [(fill(text), asked) for text, asked in raw]
        ctx.log(f"{len(written)} step(s) from the Steps box")

    asked = [want for _, want in written]
    numbers = story.assign_scenes(asked, len(pages))
    clamped = [want for want in asked
               if want is not None and not 1 <= want <= len(pages)]
    if clamped:
        ctx.log(f"{len(clamped)} step(s) asked for a scene that is not "
                f"wired ({', '.join(str(c) for c in sorted(set(clamped)))}) "
                f"— clamped to the {len(pages)} there are")

    made = [(story.prose(text), number)
            for (text, _), number in zip(written, numbers)]

    title = fill(params.get("title", ""))
    subtitle = fill(params.get("subtitle", ""))
    head = ""
    if title or subtitle:
        head = "<header class='story-head'>"
        if title:
            head += f"<h1 class='title'>{title}</h1>"
        if subtitle:
            head += f"<p class='subtitle'>{subtitle}</p>"
        head += "</header>"

    if not made and not pages:
        markup = f"<div class='wrap'>{head}{_EMPTY}</div>"
    else:
        markup = story.body(
            head, made, pages,
            prose_side=str(params.get("prose_side", "left") or "left"),
            transition=str(params.get("transition", "fade") or "fade"),
            rail=bool(params.get("progress", True)))

    across = max(22, min(65, int(params.get("prose_width", 38) or 38)))
    reading = int(params.get("reading_width", 1180) or 0)
    shape = str(params.get("ratio", "16:10") or "16:10").replace(":", "/")
    extra = (f":root{{--prose:{across}%;"
             f"--reading:{str(reading) + 'px' if reading > 0 else 'none'};"
             f"--ratio:{shape}}}\n"
             + story.CSS + "\n" + str(params.get("css", "") or ""))

    html = visual_style.page(markup, tok, title=params.get("title", ""),
                             extra_css=extra)

    if unresolved:
        ctx.log(f"left {len(set(unresolved))} token(s) unresolved: "
                f"{', '.join(sorted(set(unresolved)))}")
    ctx.log(f"{len(pages)} scene(s), {tok['theme']} theme")
    return {"html": html, "style": merged_style}

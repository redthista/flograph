"""Control Template

A commented starting point for writing your own input control. Drop it on
the canvas, right-click and choose Edit Code, and rewrite it — every placed
node carries its own copy, so your changes don't touch other nodes. Once
it does what you want, "Save as user node…" puts it in your library.

As shipped it's a percentage slider: a Slider bounded 0–100 that emits a
fraction (0.0–1.0), for feeding straight into a sample size or a threshold.
That is the whole trick — a control node is a *configuration* of one of the
built-in widget shapes plus whatever run() does with the value, and most
useful controls are exactly that.

The shapes: slider, range, number, text, date, date_range, time, datetime,
toggle, choice, multi, colour, file. Change NODE["control"] to switch, and
give it the params that shape reads (listed against each below).

Every control also gets the Behaviour settings without declaring them —
Apply changes, Show reset button, Variable name, Required, Help text and
Accent colour (flograph/core/control_apply.py) — so yours can hold a change
until Apply and publish ${name} like the built-in ones.

If you need a shape that doesn't exist — a star rating, a map pin — that
one *does* need Python: add a ControlWidget subclass to
flograph/ui/controls.py and its name to CONTROL_KINDS in
flograph/core/script.py. Everything else here stays the same.
"""

# A control node declares card "control" plus which widget shape to draw.
# Its ports are ordinary ports: the output carries the value the user set,
# and optional inputs let the control configure itself from your data
# instead of from constants you typed.
#
# Well-known input port names the host understands:
#   minimum / maximum   a bound. A column is reduced for you — lowest value
#                       for minimum, highest for maximum — so wiring one
#                       date column into both pins a picker to your data.
#   options             the list a choice offers.
#   any other name      passed through as-is, and read by that shape if it
#                       knows the name (text's "placeholder", toggle's
#                       "text").
NODE = {
    "label": "Control Template",
    "category": "Scripting",
    "version": "1.1",
    "card": "control",
    "control": "slider",
    "inputs": [("maximum", "any", {"optional": True})],
    "outputs": [("value", "number")],
}

# PARAMS are the control's settings *and* its state. Two names are special:
#
#   value     the live value — what the widget writes when the user moves
#             it, and what the node should output. Every shape needs it.
#   caption   the label drawn above the widget on the card and the tile.
#
# The rest are read by the shape you chose:
#   slider   minimum maximum step decimals
#   number   minimum maximum step decimals prefix suffix
#   text     placeholder multiline
#   range    minimum maximum step decimals    (value: JSON pair)
#   date     minimum maximum preset days allow_blank
#                                     (blank = unbounded; ISO YYYY-MM-DD)
#   date_range minimum maximum        (value: a window name or a JSON pair)
#   time     -                        (value: "HH:MM")
#   datetime -                        (value: "YYYY-MM-DDTHH:MM")
#   toggle   text style               (the label beside the tick box)
#   choice   items style all_option   (one option per line)
#   multi    items none_means         (value: JSON list of the ticked)
#   colour   swatches                 (value: "#rrggbb")
#   file     mode filter              (value: the path)
#
# width/height are the card's size on the canvas. Declare them and the card
# gets a corner resize grip that writes straight into them; leave them out
# and the card is fixed at its default size, since a drag would have nowhere
# to put the result.
PARAMS = [
    {"name": "caption", "type": "string", "label": "Caption",
     "default": "Sample", "placeholder": "Shown above the slider"},
    {"name": "value", "type": "float", "label": "Value", "default": 10.0},
    {"name": "minimum", "type": "float", "label": "Minimum", "default": 0.0},
    {"name": "maximum", "type": "float", "label": "Maximum", "default": 100.0},
    {"name": "step", "type": "float", "label": "Step", "default": 5.0},
    {"name": "decimals", "type": "int", "label": "Decimals",
     "default": 0, "min": 0, "max": 6},
    # Declare these to make the card resizable: the corner grip writes the
    # new size straight into them, so a card without them has nowhere to
    # store one and shows no grip at all. Same numbers as the built-in
    # Slider, which is what this template is a copy of.
    {"name": "width", "type": "int", "label": "Width",
     "default": 240, "min": 140, "max": 800, "cosmetic": True},
    {"name": "height", "type": "int", "label": "Height",
     "default": 96, "min": 60, "max": 600, "cosmetic": True},
]


# run() gets the inputs as keyword arguments, exactly like any other node —
# unconnected optional inputs arrive as None. ctx.params holds the current
# settings, including "value".
#
# The one rule worth taking seriously: **emit what the card is showing.** The
# widget clamps the value into the live bounds, so run() has to clamp the
# same way, or the card reads 40 while the flow gets 900. The helpers in
# flograph.core.controls exist so both sides do it identically — use them
# rather than rolling your own.
def run(ctx, maximum=None):
    from flograph.core.controls import as_number, clamp, reduce_bound

    low = as_number(ctx.params.get("minimum"), 0.0)
    # a wired bound wins over the typed one, which is what the widget does
    high = as_number(reduce_bound(maximum, high=True),
                     as_number(ctx.params.get("maximum"), 100.0))
    percent = clamp(as_number(ctx.params.get("value"), low), low, high)

    # ...and here is the part that makes this node its own thing rather than
    # a copy of Slider: the user sets a percentage, downstream gets a
    # fraction. Whatever you want the control to *mean* goes here.
    ctx.log(f"{percent:g}% -> {percent / 100.0:g}")
    return {"value": percent / 100.0}

"""Enable `python -m flograph` as an entry point (mirrors the console script).

Dispatches through `flograph.cli`, so `python -m flograph run flow.flograph`
works the same as `flograph run flow.flograph`.
"""
from flograph.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

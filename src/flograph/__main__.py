"""Enable `python -m flograph` as an entry point (mirrors the console script)."""
from flograph.app import main

if __name__ == "__main__":
    raise SystemExit(main())

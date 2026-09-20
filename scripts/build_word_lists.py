"""Rebuild the bundled spelling word lists from SCOWL.

flograph's spell check has no dependency to install and no dictionary to
download at runtime: it carries its own words, because it has to work on a
machine that will not let anything be installed and inside the one-file
build. This is the script that makes them, run by hand when the lists want
refreshing — never at run time, and never by a user.

**Source.** SCOWL (Spell Checker Oriented Word Lists) by Kevin Atkinson,
through the Hunspell dictionaries its own `make-hunspell-dict` produces:
`en_US` and `en_GB-ise`. SCOWL's licence is permissive — use, copy, modify,
distribute and sell any part of it or of word lists made from it, provided
the copyright notice travels with them — which is why it is the source and
not the other `en_GB` in circulation, a different list under the LGPL.
The notice is written into each generated file's header and into
`src/flograph/spelling/SOURCES.md`.

`en_GB-ise` is the *-ise* British list (organise, not organize), which is
what "UK spelling" means to most people who ask for it; SCOWL's `-ize`
Oxford variant is the other British option and is not bundled.

**What it does.** A Hunspell dictionary is stems plus affix flags, so the
stems are expanded through the affix rules into whole words — the app then
needs no morphology of its own, and cannot invent a word the dictionary
would have rejected. The result is folded to lower case and split three
ways: what both Englishes share, and what each has to itself. A word that
never appears lower case in the source (`London`, `NASA`) is written
capitalised, and that is how the loader knows it needs its capital.

Possessives are dropped: `'s` comes off any word at check time, so
carrying 17,000 of them would be seventeen thousand lines saying the same
rule twice.

Usage:
    python scripts/build_word_lists.py            # downloads, then writes
    python scripts/build_word_lists.py <dir>      # unpacked zips already there
"""
from __future__ import annotations

import gzip
import io
import re
import sys
import urllib.request
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "src" / "flograph" / "spelling"

#: the SCOWL release the bundled lists were built from
RELEASE = "2020.12.07"
DOWNLOADS = "https://downloads.sourceforge.net/wordlist"
DICTS = {"en_GB": f"hunspell-en_GB-ise-{RELEASE}", "en_US": f"hunspell-en_US-{RELEASE}"}
STEMS = {"en_GB": "en_GB-ise", "en_US": "en_US"}

NOTICE = f"""# flograph spelling word list — do not edit by hand.
# Rebuild with scripts/build_word_lists.py; see spelling/SOURCES.md.
#
# Derived from SCOWL (Spell Checker Oriented Word Lists) {RELEASE},
# Copyright 2000-2020 by Kevin Atkinson.
#
# Permission to use, copy, modify, distribute and sell these word lists,
# the associated scripts, the output created from the scripts, and their
# documentation for any purpose is hereby granted without fee, provided
# that the above copyright notice appears in all copies and that both that
# copyright notice and this notice appear in supporting documentation.
# Kevin Atkinson makes no representations about the suitability of this
# array for any purpose. It is provided "as is" without express or implied
# warranty.
#
# A word written with a capital needs one; every other word is lower case.
"""


def fetch(into: Path) -> Path:
    """Download and unpack both dictionaries, returning the folder."""
    into.mkdir(parents=True, exist_ok=True)
    for name in DICTS.values():
        url = f"{DOWNLOADS}/{name}.zip"
        print(f"  {url}")
        with urllib.request.urlopen(url) as response:
            blob = response.read()
        zipfile.ZipFile(io.BytesIO(blob)).extractall(into)
    return into


def read_affixes(path: Path) -> tuple[dict, dict]:
    """The `.aff` file's SFX and PFX blocks as
    `{flag: (cross_product, [(strip, add, condition), …])}`."""
    lines = path.read_text(encoding="utf-8").splitlines()
    suffixes, prefixes = {}, {}
    i = 0
    while i < len(lines):
        head = lines[i].split()
        if head[:1] in (["SFX"], ["PFX"]) and len(head) >= 4 \
                and head[2] in ("Y", "N"):
            rules = []
            for offset in range(1, int(head[3]) + 1):
                rule = lines[i + offset].split()
                strip, add = rule[2], rule[3]
                rules.append(("" if strip == "0" else strip,
                              "" if add == "0" else add,
                              rule[4] if len(rule) > 4 else "."))
            into = suffixes if head[0] == "SFX" else prefixes
            into[head[1]] = (head[2] == "Y", rules)
            i += int(head[3]) + 1
            continue
        i += 1
    return suffixes, prefixes


def _suffixed(word: str, rules) -> list[str]:
    out = []
    for strip, add, condition in rules:
        if strip and not word.endswith(strip):
            continue
        if re.search(condition + "$", word):
            out.append(word[:len(word) - len(strip)] + add if strip
                       else word + add)
    return out


def _prefixed(word: str, rules) -> list[str]:
    out = []
    for strip, add, condition in rules:
        if strip and not word.startswith(strip):
            continue
        if re.match("^" + condition, word):
            out.append(add + word[len(strip):])
    return out


def expand(folder: Path, stem: str) -> set[str]:
    """Every whole word the dictionary knows: each stem, plus what its
    affix flags make of it, prefixes crossed with suffixes where the rule
    says they may be."""
    suffixes, prefixes = read_affixes(folder / f"{stem}.aff")
    words: set[str] = set()
    lines = (folder / f"{stem}.dic").read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:                      # line 1 is the entry count
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(.*?)(?<!\\)/([\w!]*)$", line)
        base, flags = (match.group(1), match.group(2)) if match else (line, "")
        base = base.replace("\\/", "/")
        # `c` is ONLYINCOMPOUND — the ordinal pieces that only mean anything
        # glued to a number (1th, 2th), a compound rule this expansion
        # deliberately does not implement. Nor does a word with a digit in
        # it mean anything to a spell check: the checker never looks at a
        # token holding one, so 0th and 1st would be dead weight.
        if "c" in flags or any(ch.isdigit() for ch in base):
            continue
        words.add(base)
        grown = [w for flag in flags if flag in suffixes
                 for w in _suffixed(base, suffixes[flag][1])]
        words.update(grown)
        for flag in flags:
            if flag not in prefixes:
                continue
            cross, rules = prefixes[flag]
            words.update(_prefixed(base, rules))
            if cross:
                for word in grown:
                    words.update(_prefixed(word, rules))
    return words


def fold(words: set[str]) -> set[str]:
    """Lower case, minus possessives, with a word that is never written
    lower case kept capitalised so the loader can tell."""
    ever_lower = {w.lower() for w in words if w[:1].islower()}
    folded = set()
    for word in words:
        if word.endswith("'s"):
            continue                    # `'s` comes off at check time
        lower = word.lower()
        folded.add(word[:1].upper() + lower[1:]
                   if word[:1].isupper() and lower not in ever_lower
                   else lower)
    return folded


def write(name: str, words: set[str]) -> None:
    path = OUT_DIR / f"{name}.txt.gz"
    body = NOTICE + "".join(f"{w}\n" for w in sorted(words, key=str.lower))
    path.write_bytes(gzip.compress(body.encode("utf-8"), 9, mtime=0))
    print(f"  {path.name:16} {len(words):7,} words  "
          f"{path.stat().st_size / 1024:5.0f} KB")


def main(argv: list[str]) -> int:
    folder = Path(argv[1]) if len(argv) > 1 else None
    if folder is None:
        folder = REPO_ROOT / "build" / "scowl"
        print(f"downloading SCOWL {RELEASE}")
        fetch(folder)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    each = {lang: fold(expand(folder, stem)) for lang, stem in STEMS.items()}
    shared = each["en_GB"] & each["en_US"]
    print("writing")
    write("core", shared)
    for lang, words in each.items():
        write(lang, words - shared)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

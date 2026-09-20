# Where the words come from

flograph's spell check installs nothing and downloads nothing. It has to
work on a locked-down machine and inside the one-file build, so it carries
its own dictionary: the three `.txt.gz` files beside this one.

## SCOWL

The words are derived from **SCOWL** (Spell Checker Oriented Word Lists)
release **2020.12.07**, by Kevin Atkinson — specifically the Hunspell
dictionaries SCOWL's own `make-hunspell-dict` produces, `en_US` and
`en_GB-ise`, both at SCOWL size 60.

> Copyright 2000-2020 by Kevin Atkinson
>
> Permission to use, copy, modify, distribute and sell these word lists,
> the associated scripts, the output created from the scripts, and their
> documentation for any purpose is hereby granted without fee, provided
> that the above copyright notice appears in all copies and that both that
> copyright notice and this notice appear in supporting documentation.
> Kevin Atkinson makes no representations about the suitability of this
> array for any purpose. It is provided "as is" without express or implied
> warranty.

That notice is also written into the header of each generated file, so a
list that travels on its own travels with its licence.

**Why this British list and not the other one.** There are two `en_GB`
Hunspell dictionaries in wide circulation. The one most Linux
distributions ship is the Bartlett / Kelk / Brown list, which descends
from Kevin Atkinson's early Aspell work and is **LGPL**. SCOWL's own
`en_GB-ise` is not, and is covered by the permissive notice above, so it
is the one bundled here. `-ise` is the traditional British spelling
(organise); SCOWL's `-ize` Oxford variant is the other British option and
is not bundled.

## What was done to them

`scripts/build_word_lists.py` does all of it, and is the only thing that
should ever write these files:

1. **Expanded.** A Hunspell dictionary is stems plus affix flags
   (`walk/DGS`), so the affix rules are applied to produce whole words.
   The app then needs no morphology of its own and cannot accept a word
   the dictionary would have rejected — `child` does not admit `childs`.
   Hunspell's compound rules are *not* implemented; the only entries that
   need them are the ordinal fragments (`1th`, `2th`), which are dropped.
2. **Folded to lower case.** A word that never appears lower case in the
   source is written capitalised (`London`, `NASA`), and that is how the
   loader knows it needs its capital: `London` and `LONDON` pass,
   `london` does not.
3. **Split three ways.** `core.txt.gz` is what both Englishes agree on;
   `en_GB.txt.gz` and `en_US.txt.gz` are the ~2,600 words each has to
   itself. One copy of the 85,000 shared words rather than two.
4. **Possessives dropped.** `'s` comes off a word at check time, so the
   17,000 possessive forms would be the same rule said twice.

## Rebuilding

```
python scripts/build_word_lists.py
```

It downloads the two dictionaries from SourceForge and rewrites the three
files. Give it a folder holding the unpacked `.dic`/`.aff` files to skip
the download.

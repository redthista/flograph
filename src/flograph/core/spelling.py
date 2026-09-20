"""Spell checking for the prose a flow carries — report pages, Report
cards and Notes.

Qt-free on purpose: the rule for what counts as a word, what counts as
prose and what a suggestion is has to be one rule, and a highlighter on
one editor plus a context menu on another is two places for it to drift.
The three editors call `Checker.unknown` on a line and `Checker.suggest`
on a word; nothing else here knows a widget exists.

**No dictionary to install.** The words are bundled — `flograph/spelling`,
built from SCOWL by `scripts/build_word_lists.py` — because the app has to
work on a machine that will not let anything be installed and inside the
one-file build. British is the default; American is the other choice.

**Only prose is checked.** A report page is markdown with machinery in it,
and underlining `![[Revenue by Region]]`, a URL or a `${variable}` would
make the whole feature an irritation. `prose_spans` takes those out before
a word is looked at, and a fenced code block is skipped whole.
"""
from __future__ import annotations

import gzip
import re
from typing import Iterable, Optional

#: what the language choice may be, and how to write it in a menu
LANGUAGES = {"en_GB": "British (UK)", "en_US": "American (US)"}

#: UK, as asked for. A setting nobody has touched should be the one most
#: of this app's users would have chosen.
DEFAULT_LANGUAGE = "en_GB"

#: shorter than this is never underlined. Two letters is already mostly
#: initials and maths, and a red squiggle under "x" teaches nobody
#: anything.
MIN_LENGTH = 3

#: A word in prose: letters, with an apostrophe allowed inside it so
#: "don't" and "o'clock" arrive whole. No digits and no underscore —
#: `\w` would swallow `col_2` and every identifier in the file.
_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")

#: What is not prose, taken out before any word is read. Order does not
#: matter; each one simply masks the characters it covers.
_NOT_PROSE = re.compile(
    r"`[^`]*`"                       # `inline code`
    r"|!?\[\[[^\]]*\]\]"             # ![[an embed]] and [[a wiki link]]
    r"|\$\{[^}]*\}"                  # ${a flow variable}
    r"|\]\([^)]*\)"                  # the target half of a markdown link
    r"|<[^>\s]+>"                    # an HTML tag, and <a@b.com>
    r"|\b\w+://\S+"                  # a URL with a scheme
    r"|\bwww\.\S+"                   # and one without
    r"|\S+@\S+\.\S+"                 # an email address
    r"|\S*[/\\]\S*"                  # anything with a path separator in it
    r"|[^\W\d_]+\.[^\W\d_]{2,}\S*"   # a.dotted.name or a bare domain
    r"|&[a-zA-Z]+;|&#\d+;"           # an HTML entity
)

#: a line that opens or closes a fenced code block
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")

#: letters a suggestion may be built from. The apostrophe is in because
#: "dont" wants "don't" back.
_ALPHABET = "abcdefghijklmnopqrstuvwxyz'"

Span = tuple[int, int, str]


def _read_list(name: str) -> tuple[set[str], set[str]]:
    """One bundled list as (every word lower case, the ones that need a
    capital). A word written with a capital in the file needs one."""
    import importlib.resources

    blob = (importlib.resources.files("flograph.spelling")
            / f"{name}.txt.gz").read_bytes()
    words: set[str] = set()
    capitals: set[str] = set()
    for line in gzip.decompress(blob).decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        lower = line.lower()
        words.add(lower)
        if line[:1].isupper():
            capitals.add(lower)
    return words, capitals


class Dictionary:
    """The bundled words for one language, loaded once.

    Held as two sets of lower-case words: everything it knows, and the
    subset that has to be written with a capital. That is how `London`
    and `LONDON` pass while `london` does not, without keeping a second
    copy of the list in its original case.
    """

    __slots__ = ("language", "words", "capitals")

    def __init__(self, language: str) -> None:
        self.language = language if language in LANGUAGES else DEFAULT_LANGUAGE
        self.words, self.capitals = _read_list("core")
        extra, extra_capitals = _read_list(self.language)
        self.words |= extra
        self.capitals |= extra_capitals

    def knows(self, word: str) -> bool:
        lower = word.lower()
        if lower not in self.words:
            return False
        # a word the list keeps capitalised is a name, and a name written
        # in lower case is what a spell check is for
        return not (lower in self.capitals and word[:1].islower())


_loaded: dict[str, Dictionary] = {}


def dictionary(language: str = DEFAULT_LANGUAGE) -> Dictionary:
    """The dictionary for a language, loaded on first use and kept. Two
    editors on screen share one set of 85,000 strings."""
    language = language if language in LANGUAGES else DEFAULT_LANGUAGE
    if language not in _loaded:
        _loaded[language] = Dictionary(language)
    return _loaded[language]


def opens_or_closes_a_fence(line: str) -> bool:
    return _FENCE.match(line) is not None


def prose_spans(line: str) -> list[Span]:
    """Every word in a line that is prose, as (start, end, word).

    What the line says about itself is taken out first — code, embeds,
    variables, links, addresses and paths — so a word is only offered up
    when there is nothing machine-readable sitting on it.
    """
    masked = bytearray(len(line))
    for match in _NOT_PROSE.finditer(line):
        masked[match.start():match.end()] = b"\x01" * (
            match.end() - match.start())
    out: list[Span] = []
    for match in _WORD.finditer(line):
        start, end = match.start(), match.end()
        if any(masked[start:end]):
            continue
        out.append((start, end, match.group()))
    return out


def _strip_possessive(word: str) -> str:
    """`Dan's` is `Dan`. The lists carry no possessives, because the rule
    that makes one is this line rather than 17,000 more words."""
    if len(word) > 2 and word[-2] in "'’" and word[-1] in "sS":
        return word[:-2]
    return word


# ----------------------------------------------- the user's own words

#: Where the words you have taught it live: one per line, beside the rest
#: of your flograph settings. Yours rather than the project's — the same
#: jargon follows you from flow to flow, and a word taught while writing
#: one report should not have to be taught again in the next. It is a
#: plain text file on purpose: adding a hundred column names is a paste,
#: and removing one is a line.
DICTIONARY_FILE = "dictionary.txt"

_mine: Optional[list[str]] = None


def dictionary_path():
    """The user's own word list. Created the first time a word is added."""
    from flograph.paths import user_data_dir

    return user_data_dir() / DICTIONARY_FILE


def my_words() -> list[str]:
    """The words this user has taught it, in the order they were learned.

    Held in memory after the first read: a highlighter asks once a line,
    and going to disk for that would be a file read per keystroke.
    """
    global _mine
    if _mine is None:
        try:
            text = dictionary_path().read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            text = ""
        _mine = _tidy(line for line in text.splitlines()
                      if not line.startswith("#"))
    return list(_mine)


def set_my_words(words: Iterable[str]) -> None:
    """Replace the list and write it out. Deduplicated without case,
    keeping the first spelling of each — `Acme` and `acme` are one word,
    and it is the one that was written down."""
    global _mine
    _mine = _tidy(words)
    path = dictionary_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_FILE_HEADER + "".join(f"{w}\n" for w in _mine),
                        encoding="utf-8")
    except OSError:
        # a read-only profile: the words still hold for this session, which
        # is better than refusing to accept one at all
        pass


def learn_word(word: str) -> None:
    """Add one word to the user's list."""
    set_my_words(my_words() + [str(word)])


def forget_words() -> None:
    """Drop the cached copy so the next ask re-reads the file. For a test,
    and for anything that edits the file from outside."""
    global _mine
    _mine = None


_FILE_HEADER = (
    "# Words flograph's spell check should accept, one per line.\n"
    "# Added by right-clicking an underlined word, and editable here or\n"
    "# in Settings > General > Writing. Case is ignored when matching.\n")


def _tidy(words: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for word in words:
        text = str(word).strip()
        if text and not text.startswith("#") and text.lower() not in seen:
            seen.add(text.lower())
            kept.append(text)
    return kept


class Checker:
    """A dictionary plus whatever it has been told to accept besides.

    Those extra words are the user's own — column names, product names,
    the client's surname. Every flow is full of them, and without
    somewhere to put them a spell check is a wall of red that gets turned
    off on the first afternoon.
    """

    def __init__(self, language: str = DEFAULT_LANGUAGE,
                 extra: Iterable[str] = ()) -> None:
        self.language = language if language in LANGUAGES else DEFAULT_LANGUAGE
        self._dictionary: Optional[Dictionary] = None
        self._extra: set[str] = set()
        self.set_extra(extra)

    # the list is 85,000 words; a Checker made for an editor nobody types
    # in should not pay for it
    @property
    def dictionary(self) -> Dictionary:
        if self._dictionary is None:
            self._dictionary = dictionary(self.language)
        return self._dictionary

    def set_language(self, language: str) -> None:
        language = language if language in LANGUAGES else DEFAULT_LANGUAGE
        if language != self.language:
            self.language = language
            self._dictionary = None

    def set_extra(self, words: Iterable[str]) -> None:
        self._extra = {str(w).strip().lower() for w in words if str(w).strip()}

    @property
    def extra(self) -> set[str]:
        return set(self._extra)

    def knows(self, word: str) -> bool:
        word = _strip_possessive(word)
        if len(word) < MIN_LENGTH:
            return True
        return word.lower() in self._extra or self.dictionary.knows(word)

    def unknown(self, line: str) -> list[Span]:
        """The words in one line of prose this checker does not know."""
        return [span for span in prose_spans(line) if not self.knows(span[2])]

    # ---- suggestions

    def suggest(self, word: str, limit: int = 7) -> list[str]:
        """What was probably meant, best first.

        One edit away, then two if that found nothing — the classic
        spelling-corrector search. What it cannot do without a frequency
        table, which is a second thing to bundle and keep current, is know
        that "the" is a likelier answer than "tex". Two cheap stand-ins
        get most of the way there: the *kind* of slip is ranked (two
        letters swapped beats one letter wrong beats a letter missing or
        spare), and the handful of words that make up most of written
        English are floated to the top (see `COMMONEST`). After that it is
        the same first letter, the nearest length, then alphabetical — so
        two identical typos at least get the same answer.
        """
        stem = _strip_possessive(word)
        lower = stem.lower()
        if not lower:
            return []
        found = self._known(_edits(lower))
        if not found and len(lower) <= 8:
            far = {}
            for near, kind in _edits(lower).items():
                for further, _ in _edits(near).items():
                    far[further] = min(far.get(further, 9), kind + 4)
            found = self._known(far)
        found.pop(lower, None)
        ranked = sorted(found.items(),
                        key=lambda pair: (pair[0] not in COMMONEST,
                                          pair[1],
                                          pair[0][:1] != lower[:1],
                                          abs(len(pair[0]) - len(lower)),
                                          pair[0]))
        return [_recase(stem, w) for w, _kind in ranked[:limit]]

    def _known(self, candidates) -> dict:
        known = self.dictionary.words
        return {w: kind for w, kind in candidates.items()
                if w in known or w in self._extra}


#: How likely each kind of slip is, lowest first. Swapping two letters is
#: nearly always a typo and nearly always what was meant; a missing or
#: spare letter is the vaguest, because it matches far more words.
SWAP, WRONG, SPARE, MISSING = 0, 1, 2, 3


def _edits(word: str) -> dict:
    """Every word one edit away, mapped to the kind of edit that made it.
    Where two kinds reach the same word the likelier one is kept."""
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    out: dict = {}

    def offer(candidate: str, kind: int) -> None:
        if out.get(candidate, 9) > kind:
            out[candidate] = kind

    for left, right in splits:
        if len(right) > 1:
            offer(left + right[1] + right[0] + right[2:], SWAP)
        if right:
            offer(left + right[1:], SPARE)
            for letter in _ALPHABET:
                offer(left + letter + right[1:], WRONG)
        for letter in _ALPHABET:
            offer(left + letter + right, MISSING)
    return out


#: The words that make up most of written English, which is the whole of
#: the frequency information this checker has. They exist so that "teh"
#: offers "the" rather than "tea, ted, tee, tel, ten, tet, tex" — the
#: alphabet's answer, and never the right one. Kept short on purpose: it
#: is a tie-breaker, not a second dictionary.
COMMONEST = frozenset("""
the be to of and a in that have it for not on with he as you do at this
but his by from they we say her she or an will my one all would there
their what so up out if about who get which go me when make can like time
no just him know take people into year your good some could them see other
than then now look only come its over think also back after use two how
our work first well way even new want because any these give day most us
is are was were been has had did does said made went could should must
than very much many more less such own same each both few own here where
why while again ever never always often sometimes every another
""".split())


def _recase(typed: str, suggestion: str) -> str:
    """A suggestion dressed the way the word was typed, so correcting
    "Teh" at the start of a sentence does not hand back "the"."""
    if typed.isupper() and len(typed) > 1:
        return suggestion.upper()
    if typed[:1].isupper():
        return suggestion[:1].upper() + suggestion[1:]
    return suggestion

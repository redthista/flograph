"""Named AI connections (Qt-free).

A profile is one server you talk to — *Local Ollama*, *Work gateway*,
*Anthropic* — with its wire format, address, model and request options.
You keep several and pick one; Ask AI and the Flo Assistant use the
active one.

Each profile also carries the **most the assistant may see** of your data
when it talks to that server (`ceiling`, an index into `LEVELS`). That
belongs to the connection rather than to the chat because it is a fact
about *where the data goes*: a model on this PC can be shown anything,
one on someone else's server starts at column names and has to be raised
on purpose. `is_local()` is what decides the default, and only loopback
counts — a gateway on the office network is still another machine.

Saved as JSON in the user folder (`ai_profiles.json`). API keys are never
in that file; they live in the keychain under `key_name` (see `keys`).
"""
from __future__ import annotations

import ipaddress
import json
import os
import uuid
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from . import wire

PROFILES_FILE = "ai_profiles.json"

DEFAULT_LOCAL_BASE = "http://localhost:11434/v1"  # Ollama's OpenAI endpoint
DEFAULT_LOCAL_MODEL = "llama3.1"

# What the assistant may see of your data, least to most. The index is what
# is stored; the key is for code; the label is what the dialog shows.
LEVELS = (
    ("structure", "Structure — the flow only, no column names"),
    ("schema", "Schema — column names and types"),
    ("profile", "Profile — counts and ranges, no values"),
    ("lookalike", "Look-alike rows — made up to match your data"),
    ("sample", "Sample — real rows"),
    ("analyse", "Analyse — run nodes and read the results"),
)
LOCAL_DEFAULT_CEILING = 5
ONLINE_DEFAULT_CEILING = 1

LOCATIONS = ("auto", "local", "online")


def level_label(index: int) -> str:
    return LEVELS[max(0, min(index, len(LEVELS) - 1))][1]


def is_loopback_url(url: str) -> bool:
    """True when `url` points at this computer.

    Only loopback: a private address (10.x, 192.168.x) is another machine,
    and "nothing leaves this PC" has to mean exactly that.
    """
    text = (url or "").strip()
    if not text:
        return False  # blank = the provider's official, online endpoint
    if "://" not in text:
        text = "http://" + text
    try:
        host = (urlsplit(text).hostname or "").lower()
    except ValueError:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def url_host(url: str) -> str:
    text = (url or "").strip()
    if "://" not in text:
        text = "http://" + text
    try:
        return urlsplit(text).hostname or ""
    except ValueError:
        return ""


def new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Profile:
    id: str = field(default_factory=new_id)
    name: str = "Local server"
    provider: str = "openai"
    base_url: str = DEFAULT_LOCAL_BASE
    model: str = DEFAULT_LOCAL_MODEL
    verify_ssl: bool = True
    timeout: float = wire.DEFAULT_TIMEOUT
    max_tokens: int = wire.DEFAULT_MAX_TOKENS
    thinking: str = "default"
    extra_json: str = ""
    location: str = "auto"            # auto | local | online
    ceiling: Optional[int] = None     # None = the default for its location
    # How the assistant asks this server to call tools — see llm.toolcall.
    # "auto" tries the native API and falls back if the server refuses it;
    # "json" is for a model that has tools but uses them badly.
    tool_mode: str = "auto"

    # -- where the data goes ------------------------------------------------

    def detected_local(self) -> bool:
        if not (self.base_url or "").strip():
            return False
        return is_loopback_url(self.base_url)

    def is_local(self) -> bool:
        if self.location == "local":
            return True
        if self.location == "online":
            return False
        return self.detected_local()

    def default_ceiling(self) -> int:
        return LOCAL_DEFAULT_CEILING if self.is_local() else ONLINE_DEFAULT_CEILING

    def effective_ceiling(self) -> int:
        if self.ceiling is None:
            return self.default_ceiling()
        return max(0, min(int(self.ceiling), len(LEVELS) - 1))

    def where_label(self) -> str:
        """The badge: what a user needs to know about where a send goes."""
        if self.is_local():
            return "Local — nothing leaves this PC"
        host = url_host(self.base_url) or url_host(
            wire.DEFAULT_BASES.get(self.provider, ""))
        return f"Online — {host}" if host else "Online"

    # -- the request --------------------------------------------------------

    @property
    def key_name(self) -> str:
        return f"ai-profile:{self.id}"

    def extra(self) -> dict:
        """Extra request JSON as a mapping; raises LLMError when malformed."""
        text = (self.extra_json or "").strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except ValueError as exc:
            raise wire.LLMError(
                f"'Extra request JSON' on the '{self.name}' connection is not "
                f"valid JSON: {exc}") from None
        if not isinstance(value, dict):
            raise wire.LLMError(
                f"'Extra request JSON' on the '{self.name}' connection must "
                f"be a JSON object ({{...}}), not {type(value).__name__}")
        return value

    def connection(self, api_key: str = "",
                   temperature: Optional[float] = None) -> wire.Connection:
        return wire.Connection(
            provider=self.provider if self.provider in wire.PROVIDERS else "openai",
            base_url=(self.base_url or "").strip(),
            model=(self.model or "").strip(),
            api_key=api_key or "",
            verify_ssl=bool(self.verify_ssl),
            timeout=float(self.timeout or wire.DEFAULT_TIMEOUT),
            max_tokens=int(self.max_tokens or wire.DEFAULT_MAX_TOKENS),
            thinking=self.thinking or "default",
            extra=self.extra(),
            temperature=temperature,
        )

    # -- persistence --------------------------------------------------------

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        known = {f.name for f in fields(cls)}
        profile = cls(**{k: v for k, v in data.items() if k in known})
        if not profile.id:
            profile.id = new_id()
        if profile.location not in LOCATIONS:
            profile.location = "auto"
        if profile.tool_mode not in ("auto", "native", "json"):
            profile.tool_mode = "auto"
        if profile.ceiling is not None:
            try:
                profile.ceiling = max(0, min(int(profile.ceiling), len(LEVELS) - 1))
            except (TypeError, ValueError):
                profile.ceiling = None
        return profile

    def copy(self, **changes) -> "Profile":
        return Profile.from_dict({**self.to_dict(), **changes})


@dataclass
class ProfileSet:
    profiles: list = field(default_factory=list)
    active_id: str = ""

    def active(self) -> Profile:
        for profile in self.profiles:
            if profile.id == self.active_id:
                return profile
        if not self.profiles:
            self.profiles.append(Profile())
        self.active_id = self.profiles[0].id
        return self.profiles[0]

    def get(self, profile_id: str) -> Optional[Profile]:
        return next((p for p in self.profiles if p.id == profile_id), None)


def profiles_path() -> Path:
    from ..paths import user_data_dir
    return user_data_dir() / PROFILES_FILE


def exists(path: Optional[Path] = None) -> bool:
    return (path or profiles_path()).is_file()


def load(path: Optional[Path] = None) -> ProfileSet:
    """The saved profiles; one default local profile if there are none."""
    path = path or profiles_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    profiles = []
    for entry in data.get("profiles") or []:
        if isinstance(entry, dict):
            try:
                profiles.append(Profile.from_dict(entry))
            except TypeError:
                continue
    result = ProfileSet(profiles, str(data.get("active") or ""))
    result.active()  # settles active_id, and a default when the list is empty
    return result


def save(profile_set: ProfileSet, path: Optional[Path] = None) -> None:
    path = path or profiles_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"active": profile_set.active_id,
               "profiles": [p.to_dict() for p in profile_set.profiles]}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    os.replace(tmp, path)

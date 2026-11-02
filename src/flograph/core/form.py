"""The Qt-free schema and value rules for User Form nodes.

Field declarations are shared by the node, the editor and the Form from
Table helper so the form cannot show one shape and emit another.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
from dataclasses import dataclass
from typing import Any

FIELD_TYPES = frozenset({
    "text", "textarea", "password", "int", "float", "date", "toggle",
    "choice",
})


@dataclass(frozen=True)
class Field:
    name: str
    kind: str
    label: str
    default: Any = ""
    options: tuple[str, ...] = ()
    required: bool = False


def _field(record: dict[str, Any], where: str) -> Field:
    name = str(record.get("name", "")).strip()
    if not name or "\n" in name or "\r" in name:
        raise ValueError(f"{where}: field name must not be blank")
    kind = str(record.get("type", record.get("kind", ""))).strip().lower()
    required_raw = record.get("required", False)
    required = (required_raw.strip().lower() in ("1", "true", "yes", "on")
                if isinstance(required_raw, str) else bool(required_raw))
    if kind.endswith("*"):
        kind = kind[:-1]
        required = True
    if kind not in FIELD_TYPES:
        raise ValueError(f"{where}: unknown field type {kind!r}")
    label = str(record.get("label", name)).strip() or name
    raw_options = record.get("options", ())
    if isinstance(raw_options, str):
        options = tuple(part.strip() for part in raw_options.split(",")
                        if part.strip())
    elif isinstance(raw_options, (list, tuple)):
        options = tuple(str(part) for part in raw_options)
    else:
        raise ValueError(f"{where}: options must be text or a list")
    if kind == "choice" and not options:
        raise ValueError(f"{where}: a choice field needs at least one option")
    default = record.get("default", "")
    return Field(name, kind, label, default, options, required)


def parse_form_schema(raw: Any) -> list[Field]:
    """Parse one pipe-delimited field declaration per line.

    The columns are ``name|type[ * ]|label|default[|options]``. CSV quoting
    is accepted, so a label or default may contain a pipe or a comma.
    """
    if raw is None:
        return []
    if not isinstance(raw, str):
        raise ValueError("form fields must be written as text")
    fields: list[Field] = []
    seen: set[str] = set()
    for line_no, line in enumerate(raw.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            columns = next(csv.reader([line], delimiter="|", quotechar='"'))
        except csv.Error as exc:
            raise ValueError(f"line {line_no}: {exc}") from exc
        if len(columns) < 2 or len(columns) > 5:
            raise ValueError(
                f"line {line_no}: expected name|type|label|default[|options]")
        columns += [""] * (5 - len(columns))
        record = {"name": columns[0], "type": columns[1],
                  "label": columns[2] or columns[0], "default": columns[3],
                  "options": columns[4]}
        field = _field(record, f"line {line_no}")
        key = field.name.casefold()
        if key in seen:
            raise ValueError(f"line {line_no}: duplicate field {field.name!r}")
        seen.add(key)
        fields.append(field)
    return fields


def schema_from_upstream(value: Any, fallback: Any = "") -> list[Field]:
    """Normalize a wired schema (text, records, or DataFrame) or use fallback."""
    if value is None:
        return parse_form_schema(fallback)
    if isinstance(value, str):
        return parse_form_schema(value) if value.strip() else parse_form_schema(fallback)
    if hasattr(value, "to_dict") and hasattr(value, "columns"):
        columns = list(value.columns)
        if {"name", "type"}.issubset(columns):
            records = value.to_dict(orient="records")
            return _records_to_fields(records)
        if len(columns) == 1:
            return parse_form_schema("\n".join(str(x) for x in value.iloc[:, 0]))
        raise ValueError("a fields table needs name and type columns")
    if isinstance(value, dict):
        if "name" in value:
            return _records_to_fields([value])
        if "fields" in value:
            return schema_from_upstream(value["fields"], fallback)
        raise ValueError("a fields mapping needs name and type keys")
    if isinstance(value, (list, tuple)):
        if all(isinstance(row, dict) for row in value):
            return _records_to_fields(value)
        if all(isinstance(row, str) for row in value):
            return parse_form_schema("\n".join(value))
    raise ValueError("fields input must be text, field records, or a table")


def _records_to_fields(records) -> list[Field]:
    fields: list[Field] = []
    seen: set[str] = set()
    for index, record in enumerate(records, 1):
        field = _field(record, f"field {index}")
        key = field.name.casefold()
        if key in seen:
            raise ValueError(f"duplicate field {field.name!r}")
        seen.add(key)
        fields.append(field)
    return fields


def schema_to_text(fields: Any) -> str:
    """Write a canonical, pasteable pipe-delimited schema."""
    records = []
    for index, item in enumerate(fields, 1):
        if isinstance(item, Field):
            field = item
        elif isinstance(item, dict):
            field = _field(item, f"field {index}")
        else:
            raise ValueError(f"field {index} must be a Field or mapping")
        kind = field.kind + ("*" if field.required else "")
        records.append((field.name, kind, field.label, _default_text(field.default),
                        ",".join(field.options)))
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter="|", quotechar='"',
                        lineterminator="\n")
    writer.writerows(records)
    return stream.getvalue().rstrip("\n")


def _default_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def coerce(field: Field, raw: Any) -> Any:
    """Convert one submitted value to its stable, JSON-safe flow value."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if field.required:
            raise ValueError(f"{field.label} is required")
        return None if field.kind in ("int", "float") else ""
    if field.kind in ("text", "textarea", "password"):
        return str(raw)
    if field.kind == "int":
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field.label} must be a whole number") from exc
    if field.kind == "float":
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field.label} must be a number") from exc
        if not math.isfinite(value):
            raise ValueError(f"{field.label} must be a finite number")
        return value
    if field.kind == "date":
        text = str(raw)
        try:
            return dt.date.fromisoformat(text).isoformat()
        except ValueError as exc:
            raise ValueError(f"{field.label} must be a date") from exc
    if field.kind == "toggle":
        if isinstance(raw, bool):
            return raw
        if raw in (1, 0):
            return bool(raw)
        text = str(raw).strip().lower()
        if text in ("true", "yes", "on", "1"):
            return True
        if text in ("false", "no", "off", "0"):
            return False
        raise ValueError(f"{field.label} must be on or off")
    if field.kind == "choice":
        value = str(raw)
        if value not in field.options:
            raise ValueError(f"{field.label} is not one of the offered choices")
        return value
    raise ValueError(f"unknown field type {field.kind!r}")


def default_entry(fields: list[Field]) -> dict[str, Any]:
    """The typed values Reset restores, without requiring required fields."""
    output = {}
    for field in fields:
        relaxed = Field(field.name, field.kind, field.label, field.default,
                        field.options, False)
        output[field.name] = coerce(relaxed, field.default)
    return output


def coerce_entry(fields: list[Field], values: dict[str, Any], *,
                 check_required: bool = True) -> dict[str, Any]:
    """Keep schema keys only and normalize each value in field order."""
    if not isinstance(values, dict):
        raise ValueError("submitted form value must be a mapping")
    output = {}
    for field in fields:
        relaxed = field if check_required else Field(
            field.name, field.kind, field.label, field.default,
            field.options, False)
        output[field.name] = coerce(relaxed, values.get(field.name))
    return output


def parse_entry(raw: Any, fields: list[Field], *,
                check_required: bool = True) -> dict[str, Any]:
    """Decode the JSON stored in the node's value param."""
    if raw in (None, ""):
        return {}
    if isinstance(raw, dict):
        value = raw
    else:
        try:
            value = json.loads(str(raw))
        except (TypeError, ValueError) as exc:
            raise ValueError("saved form value is not valid JSON") from exc
    return coerce_entry(fields, value, check_required=check_required)

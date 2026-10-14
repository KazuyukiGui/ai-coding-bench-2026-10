=== FILE: config_parser.py ===
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""


IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_DIGITS = r"[0-9](?:_?[0-9])*"
INT_RE = re.compile(
    r"[+-]?(?:"
    r"0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*|"
    r"0[oO][0-7](?:_?[0-7])*|"
    r"0[bB][01](?:_?[01])*|"
    + _DIGITS
    + r")"
)
FLOAT_RE = re.compile(
    rf"[+-]?(?:(?:{_DIGITS}\.(?:{_DIGITS})?|\.{_DIGITS})"
    rf"(?:[eE][+-]?{_DIGITS})?|{_DIGITS}[eE][+-]?{_DIGITS})"
)
_NUMERIC_SHAPE_RE = re.compile(
    r"[+-]?(?:[0-9_]+(?:\.[0-9_]*)?|\.[0-9_]+)"
    r"(?:[eE][+-]?[0-9_]*)?"
)
_PREFIXED_NUMBER_RE = re.compile(r"[+-]?0[xXoObB]")
_ESCAPES = {
    "\\": "\\",
    '"': '"',
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "$": "$",
}


@dataclass(frozen=True)
class _Reference:
    path: tuple[str, ...] | None = None
    env_name: str | None = None
    default: str | None = None


@dataclass(frozen=True)
class _Expression:
    kind: str
    value: Any


@dataclass(frozen=True)
class _RawValue:
    expression: _Expression
    section: tuple[str, ...]


def _strip_comment(
    line: str, quote: str | None = None
) -> tuple[str, str | None]:
    i = 0
    while i < len(line):
        ch = line[i]
        if quote == '"':
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                quote = None
        elif quote == "'":
            if ch == "'":
                quote = None
        elif ch == "#":
            return line[:i], quote
        elif ch in ('"', "'"):
            quote = ch
        i += 1
    return line, quote


def _join_continuation_lines(text: str) -> list[str]:
    raw_lines = text.replace("\r\n", "\n").split("\n")
    if raw_lines[-1] == "":
        raw_lines.pop()

    logical_lines: list[str] = []
    buffer: list[str] = []
    continuing = False
    quote: str | None = None

    for line in raw_lines:
        clean, next_quote = _strip_comment(line, quote)
        clean = clean.strip(" \t")
        if not clean or clean.isspace():
            clean = ""

        if not clean and not continuing:
            quote = None
            continue

        backslashes = len(clean) - len(clean.rstrip("\\"))
        if backslashes % 2:
            buffer.append(clean[:-1])
            continuing = True
            quote = next_quote
        else:
            buffer.append(clean)
            logical = "".join(buffer).strip(" \t")
            if logical:
                logical_lines.append(logical)
            buffer.clear()
            continuing = False
            quote = None

    if continuing:
        raise ConfigError("Line continuation at end of file")

    return logical_lines


def _read_quoted(expr: str) -> tuple[str, frozenset[int]]:
    quote = expr[0]
    out: list[str] = []
    protected_dollars: set[int] = set()
    i = 1

    while i < len(expr):
        ch = expr[i]
        if ch == quote:
            if i != len(expr) - 1:
                raise ConfigError("Unexpected characters after quoted string")
            return "".join(out), frozenset(protected_dollars)

        if quote == '"' and ch == "\\":
            if i + 1 >= len(expr):
                raise ConfigError("Trailing backslash in string")
            escaped = expr[i + 1]
            if escaped not in _ESCAPES:
                raise ConfigError(f"Invalid escape sequence: \\{escaped}")
            if escaped == "$":
                protected_dollars.add(len(out))
            out.append(_ESCAPES[escaped])
            i += 2
        else:
            out.append(ch)
            i += 1

    raise ConfigError("Unterminated quoted string")


def _split_array_elements(content: str) -> list[str]:
    if not content.strip(" \t"):
        return []

    elements: list[str] = []
    start = 0
    depth = 0
    quote: str | None = None
    i = 0

    while i < len(content):
        ch = content[i]
        if quote == '"':
            if ch == "\\":
                i += 2
                continue
            if ch == '"':
                quote = None
        elif quote == "'":
            if ch == "'":
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth < 0:
                raise ConfigError("Unbalanced brackets in array")
        elif ch == "," and depth == 0:
            element = content[start:i].strip(" \t")
            if not element:
                raise ConfigError("Empty element in array")
            elements.append(element)
            start = i + 1
        i += 1

    if quote is not None or depth != 0:
        raise ConfigError("Unterminated string or bracket in array")

    last = content[start:].strip(" \t")
    if last:
        elements.append(last)
    return elements


def _coerce_unquoted(value: str) -> Any:
    if not value:
        raise ConfigError("Empty value is not allowed")
    if any(ch.isspace() or ch in ('"', "'") for ch in value):
        raise ConfigError(f"Invalid unquoted string: {value}")

    lowered = value.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "none"):
        return None

    if INT_RE.fullmatch(value):
        unsigned = value.lstrip("+-")
        base = 0 if unsigned[:2].lower() in ("0x", "0o", "0b") else 10
        try:
            return int(value, base)
        except ValueError as exc:
            raise ConfigError(f"Invalid integer: {value}") from exc

    if FLOAT_RE.fullmatch(value):
        try:
            return float(value)
        except (ValueError, OverflowError) as exc:
            raise ConfigError(f"Invalid float: {value}") from exc

    if _PREFIXED_NUMBER_RE.match(value) or (
        _NUMERIC_SHAPE_RE.fullmatch(value)
        and any(ch in "0123456789" for ch in value)
    ):
        raise ConfigError(f"Invalid numeric literal: {value}")

    return value


def _parse_reference(body: str) -> _Reference:
    if not body:
        raise ConfigError("Empty interpolation")

    if body.startswith("ENV:"):
        specification = body[4:]
        name, separator, default = specification.partition(":-")
        if not name or any(
            ch.isspace() or ch in "{}$" for ch in name
        ):
            raise ConfigError(f"Invalid environment variable reference: {body}")
        return _Reference(
            env_name=name,
            default=default if separator else None,
        )

    parts = tuple(body.split("."))
    if any(not IDENT_RE.fullmatch(part) for part in parts):
        raise ConfigError(f"Invalid reference path: {body}")
    return _Reference(path=parts)


def _parse_interpolation(
    value: str, protected_dollars: frozenset[int] = frozenset()
) -> tuple[str | _Reference, ...]:
    parts: list[str | _Reference] = []
    start = 0
    i = 0

    while i < len(value):
        if not value.startswith("${", i) or i in protected_dollars:
            i += 1
            continue

        end = value.find("}", i + 2)
        if end == -1:
            raise ConfigError("Unterminated interpolation")

        for position in range(i + 2, end):
            if (
                value.startswith("${", position)
                and position not in protected_dollars
            ):
                raise ConfigError("Nested interpolation is not supported")

        if i > start:
            parts.append(value[start:i])
        parts.append(_parse_reference(value[i + 2:end]))
        i = end + 1
        start = i

    if start < len(value):
        parts.append(value[start:])
    if not parts:
        parts.append("")
    return tuple(parts)


def _parse_expression(expr: str, is_raw: bool) -> _Expression:
    expr = expr.strip(" \t")
    if not expr:
        raise ConfigError("Empty expression")

    if expr[0] in ('"', "'"):
        value, protected_dollars = _read_quoted(expr)
        if expr[0] == "'" or is_raw:
            return _Expression("literal", value)
        return _Expression(
            "string", _parse_interpolation(value, protected_dollars)
        )

    if expr.startswith("["):
        if not expr.endswith("]"):
            raise ConfigError("Unterminated array")
        return _Expression(
            "array",
            tuple(
                _parse_expression(element, is_raw)
                for element in _split_array_elements(expr[1:-1])
            ),
        )

    if is_raw:
        return _Expression("literal", _coerce_unquoted(expr))

    parts = _parse_interpolation(expr)
    if all(isinstance(part, str) for part in parts):
        return _Expression("literal", _coerce_unquoted(expr))
    return _Expression("unquoted", parts)


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ConfigError(
        f"Cannot interpolate non-scalar value: {type(value).__name__}"
    )


def parse_config(
    text: str, env: dict[str, str] | None = None
) -> dict[str, Any]:
    environment = {} if env is None else env
    root: dict[str, Any] = {}
    current_section: tuple[str, ...] = ()

    for line in _join_continuation_lines(text):
        if line.startswith("["):
            if not line.endswith("]"):
                raise ConfigError(f"Invalid section declaration: {line}")
            section_name = line[1:-1].strip(" \t")
            parts = tuple(section_name.split("."))
            if any(not IDENT_RE.fullmatch(part) for part in parts):
                raise ConfigError(f"Invalid section name: {section_name}")

            target = root
            for part in parts:
                if part not in target:
                    target[part] = {}
                elif not isinstance(target[part], dict):
                    raise ConfigError(
                        f"Section conflicts with existing key: {section_name}"
                    )
                target = target[part]
            current_section = parts
            continue

        delimiter = re.search(r":?=", line)
        if delimiter is None:
            raise ConfigError(f"Invalid syntax in line: {line}")

        key = line[:delimiter.start()].strip(" \t")
        if not IDENT_RE.fullmatch(key):
            raise ConfigError(f"Invalid key name: {key}")

        expression = _parse_expression(
            line[delimiter.end():], delimiter.group() == ":="
        )
        target = root
        for part in current_section:
            target = target[part]
        if key in target and isinstance(target[key], dict):
            raise ConfigError(f"Key conflicts with existing section: {key}")
        target[key] = _RawValue(expression, current_section)

    resolved: dict[tuple[str, ...], Any] = {}
    resolving: set[tuple[str, ...]] = set()

    def resolve_node(path: tuple[str, ...], node: Any) -> Any:
        if path in resolved:
            return resolved[path]
        if path in resolving:
            raise ConfigError(
                f"Circular reference detected at {'.'.join(path)}"
            )

        resolving.add(path)
        try:
            if isinstance(node, _RawValue):
                result = evaluate(node.expression, node.section)
            elif isinstance(node, dict):
                result = {
                    key: resolve_node(path + (key,), value)
                    for key, value in node.items()
                }
            else:
                result = node
            resolved[path] = result
            return result
        finally:
            resolving.remove(path)

    def lookup(path: tuple[str, ...]) -> tuple[bool, Any]:
        node: Any = root
        prefix: tuple[str, ...] = ()
        for part in path:
            if isinstance(node, _RawValue):
                node = resolve_node(prefix, node)
            if not isinstance(node, dict) or part not in node:
                return False, None
            node = node[part]
            prefix += (part,)
        return True, node

    def resolve_reference(
        reference: _Reference, section: tuple[str, ...]
    ) -> Any:
        if reference.env_name is not None:
            name = reference.env_name
            if name in environment:
                value = environment[name]
            elif reference.default is not None:
                value = reference.default
            else:
                raise ConfigError(f"Missing environment variable: {name}")
            if not isinstance(value, str):
                raise ConfigError(
                    f"Environment variable must contain a string: {name}"
                )
            return value

        path = reference.path
        if path is None:
            raise ConfigError("Invalid reference")

        if len(path) == 1 and section:
            local_path = section + path
            found, node = lookup(local_path)
            if found:
                return resolve_node(local_path, node)

        found, node = lookup(path)
        if not found:
            raise ConfigError(f"Undefined reference: {'.'.join(path)}")
        return resolve_node(path, node)

    def evaluate(expression: _Expression, section: tuple[str, ...]) -> Any:
        if expression.kind == "literal":
            return expression.value
        if expression.kind == "array":
            return [
                evaluate(element, section) for element in expression.value
            ]

        parts = expression.value
        if (
            expression.kind == "unquoted"
            and len(parts) == 1
            and isinstance(parts[0], _Reference)
        ):
            reference = parts[0]
            value = resolve_reference(reference, section)
            if reference.env_name is None and not isinstance(value, str):
                return deepcopy(value)
            return _coerce_unquoted(value)

        output: list[str] = []
        for part in parts:
            if isinstance(part, str):
                output.append(part)
            else:
                output.append(_format_scalar(resolve_reference(part, section)))
        value = "".join(output)

        if expression.kind == "string":
            return value
        return _coerce_unquoted(value)

    return resolve_node((), root)
=== END ===
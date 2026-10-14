=== FILE: config_parser.py ===
import copy
import re
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""
    pass


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

_DECIMAL_DIGITS = r"[0-9](?:_?[0-9])*"
_HEX_DIGITS = r"[0-9a-fA-F](?:_?[0-9a-fA-F])*"
_OCTAL_DIGITS = r"[0-7](?:_?[0-7])*"
_BINARY_DIGITS = r"[01](?:_?[01])*"

DECIMAL_INT_RE = re.compile(rf"^[+-]?{_DECIMAL_DIGITS}$")
PREFIXED_INT_RE = re.compile(
    rf"^[+-]?(?:"
    rf"0[xX]{_HEX_DIGITS}|"
    rf"0[oO]{_OCTAL_DIGITS}|"
    rf"0[bB]{_BINARY_DIGITS}"
    rf")$"
)
FLOAT_RE = re.compile(
    rf"^[+-]?(?:"
    rf"(?:{_DECIMAL_DIGITS}\.(?:{_DECIMAL_DIGITS})?"
    rf"|\.{_DECIMAL_DIGITS})"
    rf"(?:[eE][+-]?{_DECIMAL_DIGITS})?"
    rf"|{_DECIMAL_DIGITS}[eE][+-]?{_DECIMAL_DIGITS}"
    rf")$"
)
BASE_NUMBER_CANDIDATE_RE = re.compile(
    r"^[+-]?0[xXoObB][0-9A-Za-z_]*$"
)
DECIMAL_NUMBER_CANDIDATE_RE = re.compile(
    r"^[+-]?(?:[0-9][0-9_eE.+-]*|\.[0-9][0-9_eE.+-]*)$"
)


class _RawValue:
    def __init__(
        self,
        raw: str,
        is_raw_assign: bool,
        section: tuple[str, ...],
    ):
        self.raw = raw
        self.is_raw_assign = is_raw_assign
        self.section = section


def _strip_comment(
    line: str,
    initial_quote: str | None = None,
) -> tuple[str, str | None]:
    quote = initial_quote
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
        else:
            if ch == "#":
                return line[:i], None
            if ch == '"':
                quote = '"'
            elif ch == "'":
                quote = "'"

        i += 1

    return line, quote


def _join_continuation_lines(text: str) -> list[str]:
    raw_lines = text.split("\n")
    if text.endswith("\n"):
        raw_lines.pop()

    logical_lines: list[str] = []
    buffer = ""
    continuing = False
    quote_state: str | None = None

    for raw_line in raw_lines:
        if raw_line.endswith("\r"):
            raw_line = raw_line[:-1]

        clean, ending_quote = _strip_comment(
            raw_line,
            quote_state if continuing else None,
        )
        clean = clean.strip(" \t")
        if clean and clean.isspace():
            clean = ""

        if not clean and not continuing:
            quote_state = None
            continue

        slash_count = 0
        for ch in reversed(clean):
            if ch != "\\":
                break
            slash_count += 1

        if slash_count % 2 == 1:
            buffer += clean[:-1].rstrip(" \t")
            continuing = True
            quote_state = ending_quote
        else:
            buffer += clean
            logical_lines.append(buffer)
            buffer = ""
            continuing = False
            quote_state = None

    if continuing:
        raise ConfigError("File ends with a continuation line")

    return logical_lines


def _decode_double_quoted(expr: str) -> tuple[str, set[int]]:
    out: list[str] = []
    escaped_dollars: set[int] = set()
    escapes = {
        "\\": "\\",
        '"': '"',
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "$": "$",
    }

    i = 1
    while i < len(expr):
        ch = expr[i]

        if ch == '"':
            if i != len(expr) - 1:
                raise ConfigError(
                    "Unexpected characters after double-quoted string"
                )
            return "".join(out), escaped_dollars

        if ch == "\\":
            if i + 1 >= len(expr):
                raise ConfigError("Trailing backslash in double-quoted string")

            escaped = expr[i + 1]
            if escaped not in escapes:
                raise ConfigError(f"Invalid escape sequence: \\{escaped}")

            if escaped == "$":
                escaped_dollars.add(len(out))
            out.append(escapes[escaped])
            i += 2
            continue

        out.append(ch)
        i += 1

    raise ConfigError("Unterminated double-quoted string")


def _decode_single_quoted(expr: str) -> str:
    closing = expr.find("'", 1)
    if closing < 0:
        raise ConfigError("Unterminated single-quoted string")
    if closing != len(expr) - 1:
        raise ConfigError(
            "Unexpected characters after single-quoted string"
        )
    return expr[1:closing]


def _split_array_elements(content: str) -> list[str]:
    if not content.strip():
        return []

    elements: list[str] = []
    current: list[str] = []
    depth = 0
    quote: str | None = None
    i = 0

    while i < len(content):
        ch = content[i]

        if quote == '"':
            current.append(ch)
            if ch == "\\":
                if i + 1 >= len(content):
                    raise ConfigError("Unterminated string in array")
                current.append(content[i + 1])
                i += 2
                continue
            if ch == '"':
                quote = None
            i += 1
            continue

        if quote == "'":
            current.append(ch)
            if ch == "'":
                quote = None
            i += 1
            continue

        if ch == '"':
            quote = '"'
            current.append(ch)
        elif ch == "'":
            quote = "'"
            current.append(ch)
        elif ch == "[":
            depth += 1
            current.append(ch)
        elif ch == "]":
            if depth == 0:
                raise ConfigError("Unbalanced brackets in array")
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            element = "".join(current).strip()
            if not element:
                raise ConfigError("Empty element in array")
            elements.append(element)
            current = []
        else:
            current.append(ch)

        i += 1

    if quote is not None:
        raise ConfigError("Unterminated string in array")
    if depth != 0:
        raise ConfigError("Unbalanced brackets in array")

    last = "".join(current).strip()
    if last:
        elements.append(last)

    return elements


def _looks_like_invalid_number(value: str) -> bool:
    if BASE_NUMBER_CANDIDATE_RE.fullmatch(value):
        return True
    return DECIMAL_NUMBER_CANDIDATE_RE.fullmatch(value) is not None


def _coerce_unquoted(value: str) -> Any:
    if not value:
        raise ConfigError("Empty value is not allowed")

    lowered = value.lower()
    if lowered in ("true", "yes", "on"):
        return True
    if lowered in ("false", "no", "off"):
        return False
    if lowered in ("null", "none"):
        return None

    if PREFIXED_INT_RE.fullmatch(value):
        try:
            return int(value.replace("_", ""), 0)
        except ValueError as exc:
            raise ConfigError(f"Invalid integer literal: {value}") from exc

    if DECIMAL_INT_RE.fullmatch(value):
        try:
            return int(value.replace("_", ""), 10)
        except ValueError as exc:
            raise ConfigError(f"Invalid integer literal: {value}") from exc

    if FLOAT_RE.fullmatch(value):
        try:
            return float(value.replace("_", ""))
        except ValueError as exc:
            raise ConfigError(f"Invalid float literal: {value}") from exc

    if _looks_like_invalid_number(value):
        raise ConfigError(f"Invalid numeric literal: {value}")

    if any(ch.isspace() or ch in ('"', "'") for ch in value):
        raise ConfigError(f"Invalid unquoted string: {value}")

    return value


def _lookup_path(
    root: dict[str, Any],
    path: tuple[str, ...],
) -> tuple[bool, Any]:
    current: Any = root

    for part in path:
        if not isinstance(current, dict) or part not in current:
            return False, None
        current = current[part]

    return True, current


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int, float)):
        return str(value)
    raise ConfigError(
        f"Cannot interpolate non-scalar value: {type(value).__name__}"
    )


def _validate_reference_path(reference: str) -> tuple[str, ...]:
    if not reference:
        raise ConfigError("Empty reference")

    parts = tuple(reference.split("."))
    if any(not IDENT_RE.fullmatch(part) for part in parts):
        raise ConfigError(f"Invalid reference path: {reference}")

    return parts


def parse_config(
    text: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    environment = {} if env is None else env
    lines = _join_continuation_lines(text)

    root: dict[str, Any] = {}
    current_section: tuple[str, ...] = ()

    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            section_name = line[1:-1].strip()
            if not section_name:
                raise ConfigError("Empty section name")

            parts = tuple(section_name.split("."))
            for part in parts:
                if not IDENT_RE.fullmatch(part):
                    raise ConfigError(f"Invalid section part: {part}")

            current: dict[str, Any] = root
            for part in parts:
                if part not in current:
                    current[part] = {}
                elif not isinstance(current[part], dict):
                    raise ConfigError(
                        f"Section conflicts with existing key: {section_name}"
                    )
                current = current[part]

            current_section = parts
            continue

        separator = line.find("=")
        if separator < 0:
            raise ConfigError(f"Invalid syntax in line: {line}")

        is_raw_assign = separator > 0 and line[separator - 1] == ":"
        if is_raw_assign:
            key_part = line[:separator - 1]
        else:
            key_part = line[:separator]

        key = key_part.strip()
        value_text = line[separator + 1:].strip()

        if not IDENT_RE.fullmatch(key):
            raise ConfigError(f"Invalid key name: {key}")
        if not value_text:
            raise ConfigError(f"Empty value for key: {key}")

        target: dict[str, Any] = root
        for part in current_section:
            child = target.get(part)
            if not isinstance(child, dict):
                raise ConfigError(
                    f"Section conflicts with existing key: "
                    f"{'.'.join(current_section)}"
                )
            target = child

        if key in target and isinstance(target[key], dict):
            raise ConfigError(
                f"Key conflicts with existing section: {key}"
            )

        target[key] = _RawValue(
            value_text,
            is_raw_assign,
            current_section,
        )

    resolving: set[tuple[str, ...]] = set()

    def assign_resolved(path: tuple[str, ...], value: Any) -> None:
        target = root
        for part in path[:-1]:
            child = target.get(part)
            if not isinstance(child, dict):
                raise ConfigError(
                    f"Invalid resolved path: {'.'.join(path)}"
                )
            target = child
        target[path[-1]] = value

    def resolve_value(path: tuple[str, ...], value: Any) -> Any:
        if isinstance(value, _RawValue):
            return resolve_node(path, value)

        if isinstance(value, dict):
            for key, child in list(value.items()):
                child_path = path + (key,)
                value[key] = resolve_value(child_path, child)
            return value

        return value

    def resolve_ref(
        reference: str,
        section: tuple[str, ...],
    ) -> Any:
        parts = _validate_reference_path(reference)

        if len(parts) == 1 and section:
            local_path = section + parts
            found, value = _lookup_path(root, local_path)
            if found:
                return resolve_value(local_path, value)

        found, value = _lookup_path(root, parts)
        if not found:
            raise ConfigError(f"Undefined reference: {reference}")

        return resolve_value(parts, value)

    def resolve_environment(specification: str) -> str:
        if ":-" in specification:
            variable, default = specification.split(":-", 1)
        else:
            variable = specification
            default = None

        if not variable:
            raise ConfigError("Empty environment variable name")

        if variable in environment:
            value = environment[variable]
        elif default is not None:
            value = default
        else:
            raise ConfigError(
                f"Missing environment variable: {variable}"
            )

        if not isinstance(value, str):
            raise ConfigError(
                f"Environment variable is not a string: {variable}"
            )
        return value

    def interpolate(
        value: str,
        section: tuple[str, ...],
        escaped_dollars: set[int] | None = None,
        allow_direct_value: bool = False,
    ) -> tuple[bool, Any]:
        escaped = escaped_dollars or set()
        tokens: list[tuple[str, Any]] = []
        literal_start = 0
        i = 0

        while i < len(value):
            if (
                value[i] == "$"
                and i not in escaped
                and i + 1 < len(value)
                and value[i + 1] == "{"
            ):
                closing = value.find("}", i + 2)
                if closing < 0:
                    raise ConfigError("Unterminated interpolation")

                expression = value[i + 2:closing]
                if not expression:
                    raise ConfigError("Empty interpolation")

                if literal_start < i:
                    tokens.append(("literal", value[literal_start:i]))

                if expression.startswith("ENV:"):
                    environment_value = resolve_environment(expression[4:])
                    tokens.append(("environment", environment_value))
                else:
                    referenced = resolve_ref(expression, section)
                    tokens.append(("reference", referenced))

                i = closing + 1
                literal_start = i
                continue

            i += 1

        if not tokens:
            return False, value

        if literal_start < len(value):
            tokens.append(("literal", value[literal_start:]))

        if (
            allow_direct_value
            and len(tokens) == 1
            and tokens[0][0] == "reference"
        ):
            return True, copy.deepcopy(tokens[0][1])

        output: list[str] = []
        for token_type, token_value in tokens:
            if token_type == "literal":
                output.append(token_value)
            elif token_type == "environment":
                output.append(token_value)
            else:
                output.append(_format_scalar(token_value))

        return False, "".join(output)

    def evaluate_expr(
        expression: str,
        is_raw_assign: bool,
        section: tuple[str, ...],
    ) -> Any:
        expression = expression.strip()
        if not expression:
            raise ConfigError("Empty expression")

        if expression.startswith('"'):
            decoded, escaped_dollars = _decode_double_quoted(expression)
            if is_raw_assign:
                return decoded

            _, interpolated = interpolate(
                decoded,
                section,
                escaped_dollars=escaped_dollars,
                allow_direct_value=False,
            )
            return interpolated

        if expression.startswith("'"):
            return _decode_single_quoted(expression)

        if expression.startswith("["):
            if not expression.endswith("]"):
                raise ConfigError("Unterminated array")

            elements = _split_array_elements(expression[1:-1])
            return [
                evaluate_expr(element, is_raw_assign, section)
                for element in elements
            ]

        if is_raw_assign:
            return _coerce_unquoted(expression)

        is_direct, interpolated = interpolate(
            expression,
            section,
            allow_direct_value=True,
        )
        if is_direct:
            return interpolated

        return _coerce_unquoted(interpolated)

    def resolve_node(
        path: tuple[str, ...],
        node: _RawValue,
    ) -> Any:
        if path in resolving:
            raise ConfigError(
                f"Circular reference detected at {'.'.join(path)}"
            )

        resolving.add(path)
        try:
            result = evaluate_expr(
                node.raw,
                node.is_raw_assign,
                node.section,
            )
        finally:
            resolving.remove(path)

        assign_resolved(path, result)
        return result

    def walk_and_resolve(
        current: dict[str, Any],
        prefix: tuple[str, ...],
    ) -> None:
        for key, value in list(current.items()):
            path = prefix + (key,)
            current[key] = resolve_value(path, value)

    walk_and_resolve(root, ())
    return root
=== END ===
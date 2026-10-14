=== FILE: config_parser.py ===
import copy
import re
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""
    pass


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

_DEC_DIGITS = r"[0-9](?:_?[0-9])*"
_HEX_DIGITS = r"[0-9a-fA-F](?:_?[0-9a-fA-F])*"
_OCT_DIGITS = r"[0-7](?:_?[0-7])*"
_BIN_DIGITS = r"[01](?:_?[01])*"

INT_RE = re.compile(
    rf"^[+-]?(?:"
    rf"0[xX]{_HEX_DIGITS}|"
    rf"0[oO]{_OCT_DIGITS}|"
    rf"0[bB]{_BIN_DIGITS}|"
    rf"{_DEC_DIGITS}"
    rf")$"
)

FLOAT_RE = re.compile(
    rf"^[+-]?(?:"
    rf"(?:{_DEC_DIGITS}\.(?:{_DEC_DIGITS})?|\.(?:{_DEC_DIGITS}))"
    rf"(?:[eE][+-]?{_DEC_DIGITS})?"
    rf"|{_DEC_DIGITS}[eE][+-]?{_DEC_DIGITS}"
    rf")$"
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


class _DecodedDouble:
    def __init__(self, text: str, escaped_dollars: set[int]):
        self.text = text
        self.escaped_dollars = escaped_dollars


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    i = 0

    while i < len(line):
        ch = line[i]

        if in_double and ch == "\\":
            i += 2
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i]

        i += 1

    return line


def _physical_lines(text: str) -> list[str]:
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()

    result = []
    for line in lines:
        if line.endswith("\r"):
            line = line[:-1]
        result.append(line)
    return result


def _join_continuation_lines(text: str) -> list[str]:
    logical_lines: list[str] = []
    buffer = ""
    continuing = False

    for line in _physical_lines(text):
        clean = _strip_comment(line).strip(" \t")

        if not clean and not continuing:
            continue

        trailing_backslashes = len(clean) - len(clean.rstrip("\\"))
        has_continuation = trailing_backslashes % 2 == 1

        if has_continuation:
            buffer += clean[:-1]
            continuing = True
        else:
            buffer += clean
            logical_lines.append(buffer)
            buffer = ""
            continuing = False

    if continuing:
        raise ConfigError("File ends with a continuation line")

    return logical_lines


def _decode_double_quoted(expr: str) -> _DecodedDouble:
    out: list[str] = []
    escaped_dollars: set[int] = set()
    i = 1

    while i < len(expr):
        ch = expr[i]

        if ch == '"':
            if i != len(expr) - 1:
                raise ConfigError(
                    "Extra characters after double-quoted string"
                )
            return _DecodedDouble("".join(out), escaped_dollars)

        if ch != "\\":
            out.append(ch)
            i += 1
            continue

        if i + 1 >= len(expr):
            raise ConfigError("Trailing backslash in double-quoted string")

        nxt = expr[i + 1]
        if nxt == "\\":
            out.append("\\")
        elif nxt == '"':
            out.append('"')
        elif nxt == "n":
            out.append("\n")
        elif nxt == "t":
            out.append("\t")
        elif nxt == "r":
            out.append("\r")
        elif nxt == "$":
            escaped_dollars.add(len(out))
            out.append("$")
        else:
            raise ConfigError(f"Invalid escape sequence: \\{nxt}")

        i += 2

    raise ConfigError("Unterminated double-quoted string")


def _decode_single_quoted(expr: str) -> str:
    end = expr.find("'", 1)
    if end < 0:
        raise ConfigError("Unterminated single-quoted string")
    if end != len(expr) - 1:
        raise ConfigError("Extra characters after single-quoted string")
    return expr[1:end]


def _split_array_elements(content: str) -> list[str]:
    if not content.strip(" \t"):
        return []

    elements: list[str] = []
    current: list[str] = []
    depth = 0
    in_single = False
    in_double = False
    i = 0

    while i < len(content):
        ch = content[i]

        if in_double and ch == "\\":
            current.append(ch)
            if i + 1 < len(content):
                current.append(content[i + 1])
            i += 2
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth < 0:
                    raise ConfigError("Unbalanced brackets in array")
            elif ch == "," and depth == 0:
                element = "".join(current).strip(" \t")
                if not element:
                    raise ConfigError("Empty element in array")
                elements.append(element)
                current = []
                i += 1
                continue

        current.append(ch)
        i += 1

    if in_single or in_double:
        raise ConfigError("Unterminated quoted string in array")
    if depth != 0:
        raise ConfigError("Unbalanced brackets in array")

    last = "".join(current).strip(" \t")
    if last:
        elements.append(last)

    return elements


def _looks_like_invalid_number(value: str) -> bool:
    unsigned = value
    had_sign = False

    if unsigned.startswith(("+", "-")):
        had_sign = True
        unsigned = unsigned[1:]

    if re.match(r"^0[xXoObB]", unsigned):
        return True

    if not unsigned:
        return False

    numeric_chars = set("0123456789_.eE+-")

    if unsigned[0].isdigit():
        return all(ch in numeric_chars for ch in unsigned)

    if unsigned[0] == "." and len(unsigned) > 1:
        if unsigned[1].isdigit() or unsigned[1] == "_":
            return all(ch in numeric_chars for ch in unsigned)

    if had_sign and unsigned[0] == "_" and len(unsigned) > 1:
        return all(ch in numeric_chars for ch in unsigned)

    return False


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

    if INT_RE.fullmatch(value):
        unsigned = value[1:] if value.startswith(("+", "-")) else value
        if unsigned.lower().startswith("0x"):
            base = 16
        elif unsigned.lower().startswith("0o"):
            base = 8
        elif unsigned.lower().startswith("0b"):
            base = 2
        else:
            base = 10

        try:
            return int(value.replace("_", ""), base)
        except ValueError as exc:
            raise ConfigError(f"Invalid integer literal: {value}") from exc

    if FLOAT_RE.fullmatch(value):
        try:
            return float(value.replace("_", ""))
        except ValueError as exc:
            raise ConfigError(f"Invalid float literal: {value}") from exc

    if _looks_like_invalid_number(value):
        raise ConfigError(f"Invalid numeric literal: {value}")

    if any(
        ch.isspace() or ch in ('"', "'")
        for ch in value
    ):
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
    parts = tuple(reference.split("."))
    if not parts or any(not IDENT_RE.fullmatch(part) for part in parts):
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
            section_name = line[1:-1].strip(" \t")
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
                        f"Section conflicts with existing key: "
                        f"{section_name}"
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

        value_part = line[separator + 1:]
        key = key_part.strip(" \t")
        value = value_part.strip(" \t")

        if not IDENT_RE.fullmatch(key):
            raise ConfigError(f"Invalid key name: {key}")
        if not value:
            raise ConfigError(f"Empty value for key: {key}")

        target = root
        for part in current_section:
            section_value = target.get(part)
            if not isinstance(section_value, dict):
                raise ConfigError(
                    "Current section conflicts with a non-dictionary value"
                )
            target = section_value

        if key in target and isinstance(target[key], dict):
            raise ConfigError(
                f"Key conflicts with existing section: {key}"
            )

        target[key] = _RawValue(
            value,
            is_raw_assign,
            current_section,
        )

    resolving: set[tuple[str, ...]] = set()

    def resolve_value(path: tuple[str, ...], value: Any) -> Any:
        if isinstance(value, _RawValue):
            return resolve_raw_value(path, value)

        if isinstance(value, dict):
            for child_key in list(value):
                child_path = path + (child_key,)
                value[child_key] = resolve_value(
                    child_path,
                    value[child_key],
                )
            return value

        return value

    def resolve_raw_value(
        path: tuple[str, ...],
        raw_value: _RawValue,
    ) -> Any:
        current_value: Any = root
        for part in path:
            if not isinstance(current_value, dict):
                return current_value
            current_value = current_value[part]

        if not isinstance(current_value, _RawValue):
            return resolve_value(path, current_value)

        if path in resolving:
            raise ConfigError(
                f"Circular reference detected at {'.'.join(path)}"
            )

        resolving.add(path)
        try:
            result = evaluate_expression(
                raw_value.raw,
                raw_value.is_raw_assign,
                raw_value.section,
            )
        finally:
            resolving.remove(path)

        target = root
        for part in path[:-1]:
            child = target.get(part)
            if not isinstance(child, dict):
                raise ConfigError(
                    f"Invalid resolved path: {'.'.join(path)}"
                )
            target = child

        target[path[-1]] = result
        return result

    def resolve_reference(
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

    def resolve_placeholder(
        expression: str,
        section: tuple[str, ...],
    ) -> tuple[bool, Any]:
        if not expression:
            raise ConfigError("Empty interpolation")
        if "{" in expression or "${" in expression:
            raise ConfigError(
                f"Invalid interpolation expression: {expression}"
            )

        if expression.startswith("ENV:"):
            specification = expression[4:]
            if ":-" in specification:
                variable, default = specification.split(":-", 1)
            else:
                variable = specification
                default = None

            if not variable:
                raise ConfigError("Empty environment variable name")

            if variable in environment:
                return True, environment[variable]
            if default is not None:
                return True, default

            raise ConfigError(
                f"Missing environment variable: {variable}"
            )

        return False, resolve_reference(expression, section)

    def interpolate(
        value: str,
        section: tuple[str, ...],
        escaped_dollars: set[int] | None = None,
        allow_direct_reference: bool = False,
    ) -> tuple[bool, Any]:
        protected = escaped_dollars or set()
        pieces: list[str] = []
        placeholders: list[tuple[int, int, bool, Any]] = []
        literal_start = 0
        i = 0

        while i < len(value):
            if (
                value[i] == "$"
                and i not in protected
                and i + 1 < len(value)
                and value[i + 1] == "{"
            ):
                pieces.append(value[literal_start:i])
                end = value.find("}", i + 2)
                if end < 0:
                    raise ConfigError("Unterminated interpolation")

                expression = value[i + 2:end]
                is_environment, resolved = resolve_placeholder(
                    expression,
                    section,
                )
                placeholders.append(
                    (i, end + 1, is_environment, resolved)
                )
                pieces.append(_format_scalar(resolved))
                i = end + 1
                literal_start = i
                continue

            i += 1

        pieces.append(value[literal_start:])

        if (
            allow_direct_reference
            and len(placeholders) == 1
            and placeholders[0][0] == 0
            and placeholders[0][1] == len(value)
            and not placeholders[0][2]
        ):
            return True, copy.deepcopy(placeholders[0][3])

        return False, "".join(pieces)

    def evaluate_expression(
        expression: str,
        is_raw_assign: bool,
        section: tuple[str, ...],
    ) -> Any:
        expression = expression.strip(" \t")
        if not expression:
            raise ConfigError("Empty expression")

        if expression.startswith('"'):
            decoded = _decode_double_quoted(expression)
            if is_raw_assign:
                return decoded.text

            _, interpolated = interpolate(
                decoded.text,
                section,
                escaped_dollars=decoded.escaped_dollars,
                allow_direct_reference=False,
            )
            return interpolated

        if expression.startswith("'"):
            return _decode_single_quoted(expression)

        if expression.startswith("["):
            if not expression.endswith("]"):
                raise ConfigError("Unterminated array")

            elements = _split_array_elements(expression[1:-1])
            return [
                evaluate_expression(
                    element,
                    is_raw_assign,
                    section,
                )
                for element in elements
            ]

        if is_raw_assign:
            return _coerce_unquoted(expression)

        is_direct, interpolated = interpolate(
            expression,
            section,
            allow_direct_reference=True,
        )
        if is_direct:
            return interpolated

        return _coerce_unquoted(interpolated)

    resolve_value((), root)
    return root
=== END ===
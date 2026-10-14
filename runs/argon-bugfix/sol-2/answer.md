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


def _strip_comment(
    line: str,
    in_single: bool = False,
    in_double: bool = False,
) -> tuple[str, bool, bool]:
    i = 0
    while i < len(line):
        ch = line[i]

        if ch == "\\" and in_double:
            i += 2
            continue

        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i], in_single, in_double

        i += 1

    return line, in_single, in_double


def _join_continuation_lines(text: str) -> list[str]:
    if re.search(r"\r(?!\n)", text):
        raise ConfigError("Invalid line ending")

    normalized = text.replace("\r\n", "\n")
    raw_lines = normalized.split("\n")
    if normalized.endswith("\n"):
        raw_lines.pop()

    logical_lines: list[str] = []
    buffer = ""
    continuing = False
    in_single = False
    in_double = False

    for raw_line in raw_lines:
        if not continuing:
            in_single = False
            in_double = False

        clean, end_single, end_double = _strip_comment(
            raw_line,
            in_single,
            in_double,
        )
        clean = clean.rstrip(" \t")
        if clean and clean.isspace():
            clean = ""

        piece = clean.lstrip(" \t")

        slash_count = 0
        for ch in reversed(piece):
            if ch != "\\":
                break
            slash_count += 1

        continues_here = slash_count % 2 == 1

        if continues_here:
            buffer += piece[:-1]
            continuing = True
            in_single = end_single
            in_double = end_double
            continue

        logical = buffer + piece
        if logical and not logical.isspace():
            logical_lines.append(logical)

        buffer = ""
        continuing = False
        in_single = False
        in_double = False

    if continuing:
        raise ConfigError("File ends with a continuation line")

    return logical_lines


def _parse_double_quoted(expr: str) -> tuple[str, set[int]]:
    out: list[str] = []
    protected_dollars: set[int] = set()
    i = 1

    while i < len(expr):
        ch = expr[i]

        if ch == '"':
            if i != len(expr) - 1:
                raise ConfigError(
                    "Extra characters after double-quoted string"
                )
            return "".join(out), protected_dollars

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
            protected_dollars.add(len(out))
            out.append("$")
        else:
            raise ConfigError(f"Invalid escape sequence: \\{nxt}")

        i += 2

    raise ConfigError("Unterminated double-quoted string")


def _parse_single_quoted(expr: str) -> str:
    closing = expr.find("'", 1)
    if closing < 0:
        raise ConfigError("Unterminated single-quoted string")
    if closing != len(expr) - 1:
        raise ConfigError("Extra characters after single-quoted string")
    return expr[1:closing]


def _split_array_elements(content: str) -> list[str]:
    if not content.strip():
        return []

    elements: list[str] = []
    current: list[str] = []
    depth = 0
    in_single = False
    in_double = False
    i = 0

    while i < len(content):
        ch = content[i]

        if ch == "\\" and in_double:
            current.append(ch)
            if i + 1 < len(content):
                current.append(content[i + 1])
                i += 2
            else:
                i += 1
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
                element = "".join(current).strip()
                if not element:
                    raise ConfigError("Empty element in array")
                elements.append(element)
                current = []
                i += 1
                continue

        current.append(ch)
        i += 1

    if in_single or in_double:
        raise ConfigError("Unterminated string in array")
    if depth != 0:
        raise ConfigError("Unbalanced brackets in array")

    last = "".join(current).strip()
    if last:
        elements.append(last)

    return elements


def _looks_like_invalid_number(value: str) -> bool:
    body = value
    if body[:1] in ("+", "-"):
        body = body[1:]

    if not body:
        return False

    if re.match(r"^0[xXoObB]", body):
        return True

    if not any(ch.isdigit() for ch in body):
        return False

    if body[0] not in "0123456789_.":
        return False

    if re.fullmatch(r"[0-9_]+", body):
        return True

    if (
        "." in body or "e" in body.lower()
    ) and re.fullmatch(r"[0-9_.eE+-]+", body):
        return True

    return False


def _coerce_unquoted(value: str) -> Any:
    if not value:
        raise ConfigError("Empty value is not allowed")

    if any(ch.isspace() or ch in ('"', "'") for ch in value):
        raise ConfigError(f"Invalid unquoted string: {value}")

    low = value.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none"):
        return None

    if INT_RE.fullmatch(value):
        cleaned = value.replace("_", "")
        unsigned = cleaned[1:] if cleaned[:1] in ("+", "-") else cleaned
        base = 0 if re.match(r"^0[xXoObB]", unsigned) else 10
        try:
            return int(cleaned, base)
        except ValueError as exc:
            raise ConfigError(f"Invalid integer literal: {value}") from exc

    if FLOAT_RE.fullmatch(value):
        try:
            return float(value.replace("_", ""))
        except ValueError as exc:
            raise ConfigError(f"Invalid float literal: {value}") from exc

    if _looks_like_invalid_number(value):
        raise ConfigError(f"Invalid numeric literal: {value}")

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


def parse_config(
    text: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    environment = {} if env is None else env
    lines = _join_continuation_lines(text)

    root: dict[str, Any] = {}
    current_section: tuple[str, ...] = ()

    for line in lines:
        line = line.strip(" \t")
        if not line:
            continue

        if line.startswith("[") and line.endswith("]"):
            section_text = line[1:-1].strip(" \t")
            if not section_text:
                raise ConfigError("Empty section name")

            parts = tuple(section_text.split("."))
            for part in parts:
                if not IDENT_RE.fullmatch(part):
                    raise ConfigError(f"Invalid section part: {part}")

            target = root
            for part in parts:
                existing = target.get(part)
                if existing is None and part not in target:
                    target[part] = {}
                elif not isinstance(existing, dict):
                    raise ConfigError(
                        f"Section conflicts with existing key: "
                        f"{section_text}"
                    )
                target = target[part]

            current_section = parts
            continue

        equals_index = line.find("=")
        if equals_index < 0:
            raise ConfigError(f"Invalid syntax in line: {line}")

        is_raw = (
            equals_index > 0 and line[equals_index - 1] == ":"
        )
        if is_raw:
            key_text = line[:equals_index - 1]
        else:
            key_text = line[:equals_index]

        value_text = line[equals_index + 1:]
        key = key_text.strip(" \t")
        raw_value = value_text.strip(" \t")

        if not IDENT_RE.fullmatch(key):
            raise ConfigError(f"Invalid key name: {key}")
        if not raw_value:
            raise ConfigError(f"Empty value for key: {key}")

        target = root
        for part in current_section:
            child = target.get(part)
            if not isinstance(child, dict):
                raise ConfigError(
                    "Current section conflicts with an existing value"
                )
            target = child

        if key in target and isinstance(target[key], dict):
            raise ConfigError(
                f"Key conflicts with existing section: {key}"
            )

        target[key] = _RawValue(
            raw_value,
            is_raw,
            current_section,
        )

    resolving: set[tuple[str, ...]] = set()

    def assign_at_path(path: tuple[str, ...], value: Any) -> None:
        target = root
        for part in path[:-1]:
            child = target.get(part)
            if not isinstance(child, dict):
                raise ConfigError(
                    f"Invalid configuration path: {'.'.join(path)}"
                )
            target = child
        target[path[-1]] = value

    def resolve_node(
        path: tuple[str, ...],
        node: Any,
    ) -> Any:
        if isinstance(node, _RawValue):
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

            assign_at_path(path, result)
            return result

        if isinstance(node, dict):
            for key in list(node):
                child_path = path + (key,)
                node[key] = resolve_node(child_path, node[key])
            return node

        return node

    def resolve_reference(
        reference: str,
        section: tuple[str, ...],
    ) -> Any:
        if not reference:
            raise ConfigError("Empty reference")

        parts = tuple(reference.split("."))
        if any(not IDENT_RE.fullmatch(part) for part in parts):
            raise ConfigError(f"Invalid reference: {reference}")

        if len(parts) == 1 and section:
            local_path = section + parts
            found, value = _lookup_path(root, local_path)
            if found:
                return resolve_node(local_path, value)

        found, value = _lookup_path(root, parts)
        if not found:
            raise ConfigError(f"Undefined reference: {reference}")

        return resolve_node(parts, value)

    def resolve_environment(expression: str) -> str:
        specification = expression[4:]
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

    def interpolate_string(
        value: str,
        section: tuple[str, ...],
        protected_dollars: set[int] | None = None,
        allow_direct_reference: bool = False,
    ) -> tuple[bool, Any]:
        protected = protected_dollars or set()
        placeholders: list[tuple[int, int, str]] = []
        i = 0

        while i < len(value):
            if (
                value[i] == "$"
                and i not in protected
                and i + 1 < len(value)
                and value[i + 1] == "{"
            ):
                closing = value.find("}", i + 2)
                if closing < 0:
                    raise ConfigError("Unterminated interpolation")

                expression = value[i + 2:closing]
                if not expression:
                    raise ConfigError("Empty interpolation")

                placeholders.append((i, closing + 1, expression))
                i = closing + 1
                continue

            i += 1

        if not placeholders:
            return False, value

        if (
            allow_direct_reference
            and len(placeholders) == 1
            and placeholders[0][0] == 0
            and placeholders[0][1] == len(value)
            and not placeholders[0][2].startswith("ENV:")
        ):
            referenced = resolve_reference(
                placeholders[0][2],
                section,
            )
            return True, copy.deepcopy(referenced)

        output: list[str] = []
        last = 0

        for start, end, expression in placeholders:
            output.append(value[last:start])

            if expression.startswith("ENV:"):
                replacement = resolve_environment(expression)
            else:
                replacement = _format_scalar(
                    resolve_reference(expression, section)
                )

            output.append(replacement)
            last = end

        output.append(value[last:])
        return False, "".join(output)

    def evaluate_expr(
        expression: str,
        is_raw_assign: bool,
        section: tuple[str, ...],
    ) -> Any:
        expression = expression.strip(" \t")
        if not expression:
            raise ConfigError("Empty expression")

        if expression.startswith('"'):
            decoded, protected = _parse_double_quoted(expression)
            if is_raw_assign:
                return decoded

            _, interpolated = interpolate_string(
                decoded,
                section,
                protected_dollars=protected,
                allow_direct_reference=False,
            )
            return interpolated

        if expression.startswith("'"):
            return _parse_single_quoted(expression)

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

        is_direct, interpolated = interpolate_string(
            expression,
            section,
            allow_direct_reference=True,
        )
        if is_direct:
            return interpolated

        return _coerce_unquoted(interpolated)

    resolve_node((), root)
    return root
=== END ===
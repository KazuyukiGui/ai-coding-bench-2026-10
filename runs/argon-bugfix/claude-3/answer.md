=== FILE: config_parser.py ===
import copy
import re
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""
    pass


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
INT_RE = re.compile(r"^[+-]?(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|[0-9][0-9_]*)$")
FLOAT_RE = re.compile(r"^[+-]?(?:[0-9][0-9_]*\.[0-9_]*|\.[0-9_]+)(?:[eE][+-]?[0-9_]+)?$|^[+-]?[0-9][0-9_]*[eE][+-]?[0-9_]+$")

_ESCAPES = {
    "\\": "\\",
    '"': '"',
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "$": "$",
}


class _RawValue:
    def __init__(self, raw: str, is_raw_assign: bool, section: tuple[str, ...]):
        self.raw = raw
        self.is_raw_assign = is_raw_assign
        self.section = section


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
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
            return line[:i]
        i += 1
    return line


def _split_physical_lines(text: str) -> list[str]:
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def _ends_with_continuation(s: str) -> bool:
    count = len(s) - len(s.rstrip("\\"))
    return count % 2 == 1


def _join_continuation_lines(text: str) -> list[str]:
    logical_lines: list[str] = []
    buffer: str | None = None

    for line in _split_physical_lines(text):
        clean = _strip_comment(line).strip(" \t")
        if clean.isspace():
            clean = ""

        continues = _ends_with_continuation(clean)
        if continues:
            clean = clean[:-1]
        if buffer is not None:
            clean = buffer + clean

        if continues:
            buffer = clean
            continue

        buffer = None
        clean = clean.strip(" \t")
        if clean:
            logical_lines.append(clean)

    if buffer is not None:
        raise ConfigError("Line continuation at end of file")

    return logical_lines


def _find_closing_double_quote(s: str) -> int:
    i = 1
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            return i
        i += 1
    return -1


def _unescape_double_quoted(s: str) -> list[tuple[str, bool]]:
    # Returns list of (char, produced_by_escape)
    out: list[tuple[str, bool]] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            if i + 1 >= len(s):
                raise ConfigError("Trailing backslash in string")
            nxt = s[i + 1]
            if nxt not in _ESCAPES:
                raise ConfigError(f"Invalid escape sequence: \\{nxt}")
            out.append((_ESCAPES[nxt], True))
            i += 2
        else:
            out.append((ch, False))
            i += 1
    return out


def _split_template(chars: list[tuple[str, bool]]) -> list[tuple[bool, str]]:
    # Returns list of (is_placeholder, text)
    segments: list[tuple[bool, str]] = []
    buf: list[str] = []
    i = 0
    n = len(chars)
    while i < n:
        ch, escaped = chars[i]
        if ch == "$" and not escaped and i + 1 < n and chars[i + 1][0] == "{":
            j = i + 2
            while j < n and chars[j][0] != "}":
                j += 1
            if j >= n:
                raise ConfigError("Unterminated interpolation")
            expr = "".join(c for c, _ in chars[i + 2:j])
            if not expr:
                raise ConfigError("Empty interpolation")
            if buf:
                segments.append((False, "".join(buf)))
                buf = []
            segments.append((True, expr))
            i = j + 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        segments.append((False, "".join(buf)))
    return segments


def _split_array_elements(content: str) -> list[str]:
    content = content.strip()
    if not content:
        return []
    elements = []
    current = []
    depth = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(content):
        ch = content[i]
        if ch == "\\" and in_double:
            current.append(content[i:i + 2])
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
                elem = "".join(current).strip()
                if not elem:
                    raise ConfigError("Empty element in array")
                elements.append(elem)
                current = []
                i += 1
                continue
        current.append(ch)
        i += 1

    if in_single or in_double or depth != 0:
        raise ConfigError("Unterminated string or bracket in array")

    last = "".join(current).strip()
    if last:
        elements.append(last)
    return elements


def _coerce_unquoted(val: str) -> Any:
    if not val:
        raise ConfigError("Empty value is not allowed")

    low = val.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none"):
        return None

    if INT_RE.fullmatch(val):
        try:
            return int(val, 0)
        except ValueError:
            raise ConfigError(f"Invalid integer literal: {val}") from None

    if FLOAT_RE.fullmatch(val):
        try:
            return float(val)
        except ValueError:
            raise ConfigError(f"Invalid float literal: {val}") from None

    if any(c.isspace() or c in ('"', "'") for c in val):
        raise ConfigError(f"Invalid unquoted string: {val}")

    return val


def _format_scalar(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float, str)):
        return str(val)
    raise ConfigError(f"Cannot interpolate non-scalar value: {type(val)}")


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    if env is None:
        env = {}

    lines = _join_continuation_lines(text)
    root: dict[str, Any] = {}
    current_section: tuple[str, ...] = ()

    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            sec_str = line[1:-1].strip()
            if not sec_str:
                raise ConfigError("Empty section name")
            parts = tuple(sec_str.split("."))
            for p in parts:
                if not IDENT_RE.fullmatch(p):
                    raise ConfigError(f"Invalid section part: {p}")
            current_section = parts

            curr = root
            for p in parts:
                if p not in curr:
                    curr[p] = {}
                elif not isinstance(curr[p], dict):
                    raise ConfigError(f"Section conflicts with existing key: {sec_str}")
                curr = curr[p]
            continue

        eq = line.find("=")
        if eq == -1:
            raise ConfigError(f"Invalid syntax in line: {line}")
        is_raw = eq > 0 and line[eq - 1] == ":"
        key = line[:eq - 1 if is_raw else eq].strip(" \t")
        val_str = line[eq + 1:].strip(" \t")

        if not IDENT_RE.fullmatch(key):
            raise ConfigError(f"Invalid key name: {key}")
        if not val_str:
            raise ConfigError(f"Empty value for key: {key}")

        target = root
        for p in current_section:
            target = target[p]

        if key in target and isinstance(target[key], dict):
            raise ConfigError(f"Key conflicts with existing section: {key}")

        target[key] = _RawValue(val_str, is_raw, current_section)

    resolving: set[tuple[str, ...]] = set()

    def resolve_node(path: tuple[str, ...], node: Any) -> Any:
        if isinstance(node, _RawValue):
            if path in resolving:
                raise ConfigError(f"Circular reference detected at {'.'.join(path)}")
            resolving.add(path)
            try:
                res = evaluate_expr(node.raw, node.is_raw_assign, node.section)
            finally:
                resolving.discard(path)

            target = root
            for p in path[:-1]:
                target = target[p]
            target[path[-1]] = res
            return res

        if isinstance(node, dict):
            if path in resolving:
                raise ConfigError(f"Circular reference detected at {'.'.join(path)}")
            resolving.add(path)
            try:
                for k in list(node):
                    resolve_node(path + (k,), node[k])
            finally:
                resolving.discard(path)

        return node

    def lookup(path: tuple[str, ...]) -> tuple[bool, Any]:
        curr: Any = root
        for i, part in enumerate(path):
            if not isinstance(curr, dict) or part not in curr:
                return False, None
            curr = curr[part]
            if isinstance(curr, _RawValue) and i < len(path) - 1:
                curr = resolve_node(path[:i + 1], curr)
        return True, curr

    def resolve_ref(ref_str: str, section: tuple[str, ...]) -> Any:
        if not ref_str:
            raise ConfigError("Empty reference")
        parts = tuple(ref_str.split("."))
        if len(parts) == 1:
            local_path = section + parts
            found, val = lookup(local_path)
            if found:
                return resolve_node(local_path, val)

        found, val = lookup(parts)
        if not found:
            raise ConfigError(f"Undefined reference: {ref_str}")
        return resolve_node(parts, val)

    def resolve_env(spec: str) -> str:
        if ":-" in spec:
            var_name, default = spec.split(":-", 1)
        else:
            var_name, default = spec, None
        if not var_name:
            raise ConfigError("Empty environment variable name")
        if var_name in env:
            return str(env[var_name])
        if default is None:
            raise ConfigError(f"Missing environment variable: {var_name}")
        return default

    def interpolate(
        chars: list[tuple[str, bool]], section: tuple[str, ...], allow_direct: bool
    ) -> tuple[bool, Any]:
        # Returns (is_direct_single_ref, value)
        segments = _split_template(chars)

        if allow_direct and len(segments) == 1:
            is_ref, expr = segments[0]
            if is_ref and not expr.startswith("ENV:"):
                return True, copy.deepcopy(resolve_ref(expr, section))

        out = []
        for is_ref, text_part in segments:
            if not is_ref:
                out.append(text_part)
            elif text_part.startswith("ENV:"):
                out.append(resolve_env(text_part[4:]))
            else:
                out.append(_format_scalar(resolve_ref(text_part, section)))
        return False, "".join(out)

    def evaluate_expr(expr: str, is_raw_assign: bool, section: tuple[str, ...]) -> Any:
        expr = expr.strip(" \t")
        if not expr:
            raise ConfigError("Empty expression")

        if expr.startswith('"'):
            end = _find_closing_double_quote(expr)
            if end == -1:
                raise ConfigError("Unterminated double-quoted string")
            if end != len(expr) - 1:
                raise ConfigError("Unexpected characters after double-quoted string")
            chars = _unescape_double_quoted(expr[1:-1])
            if is_raw_assign:
                return "".join(c for c, _ in chars)
            _, interpolated = interpolate(chars, section, False)
            return interpolated

        if expr.startswith("'"):
            end = expr.find("'", 1)
            if end == -1:
                raise ConfigError("Unterminated single-quoted string")
            if end != len(expr) - 1:
                raise ConfigError("Unexpected characters after single-quoted string")
            return expr[1:-1]

        if expr.startswith("["):
            if not expr.endswith("]"):
                raise ConfigError("Unterminated array")
            elems = _split_array_elements(expr[1:-1])
            return [evaluate_expr(e, is_raw_assign, section) for e in elems]

        if is_raw_assign:
            return _coerce_unquoted(expr)

        is_direct, val = interpolate([(c, False) for c in expr], section, True)
        if is_direct:
            return val
        return _coerce_unquoted(val)

    resolve_node((), root)
    return root
=== END ===
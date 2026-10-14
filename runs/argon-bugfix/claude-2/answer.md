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

WS = " \t"


class _RawValue:
    def __init__(self, raw: str, is_raw_assign: bool, section: tuple[str, ...]):
        self.raw = raw
        self.is_raw_assign = is_raw_assign
        self.section = section


def _strip_comment(line: str, in_single: bool = False, in_double: bool = False) -> tuple[str, bool, bool]:
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
    raw_lines = text.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()

    logical_lines: list[str] = []
    buffer = ""
    continuing = False
    in_single = False
    in_double = False

    for line in raw_lines:
        if line.endswith("\r"):
            line = line[:-1]
        line = line.lstrip(WS)
        body, in_single, in_double = _strip_comment(line, in_single, in_double)
        body = body.rstrip(WS)

        trailing = len(body) - len(body.rstrip("\\"))
        if trailing % 2 == 1:
            buffer += body[:-1]
            continuing = True
            continue

        buffer += body
        logical = buffer.strip(WS)
        if logical:
            logical_lines.append(logical)
        buffer = ""
        continuing = False
        in_single = False
        in_double = False

    if continuing:
        raise ConfigError("Line continuation at end of file")

    return logical_lines


def _extract_double_quoted(expr: str) -> str:
    i = 1
    while i < len(expr):
        ch = expr[i]
        if ch == "\\":
            i += 2
            continue
        if ch == '"':
            if i != len(expr) - 1:
                raise ConfigError("Unexpected characters after closing quote")
            return expr[1:i]
        i += 1
    raise ConfigError("Unterminated double-quoted string")


def _unescape_double_quoted(s: str) -> list[tuple[str, bool]]:
    # Returns list of (char, is_escaped)
    out: list[tuple[str, bool]] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            if i + 1 >= len(s):
                raise ConfigError("Trailing backslash in string")
            nxt = s[i + 1]
            if nxt == "n":
                out.append(("\n", True))
            elif nxt == "t":
                out.append(("\t", True))
            elif nxt == "r":
                out.append(("\r", True))
            elif nxt == '"':
                out.append(('"', True))
            elif nxt == "\\":
                out.append(("\\", True))
            elif nxt == "$":
                out.append(("$", True))
            else:
                raise ConfigError(f"Invalid escape sequence: \\{nxt}")
            i += 2
        else:
            out.append((ch, False))
            i += 1
    return out


def _split_array_elements(content: str) -> list[str]:
    content = content.strip(WS)
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
                elem = "".join(current).strip(WS)
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

    last = "".join(current).strip(WS)
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
            sec_str = line[1:-1].strip(WS)
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
        if eq < 0:
            raise ConfigError(f"Invalid syntax in line: {line}")
        is_raw = False
        if eq > 0 and line[eq - 1] == ":":
            is_raw = True
            key_part = line[:eq - 1]
        else:
            key_part = line[:eq]
        val_part = line[eq + 1:]

        key = key_part.strip(WS)
        val_str = val_part.strip(WS)

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

    def resolve_node(path: tuple[str, ...]) -> Any:
        parent = root
        for p in path[:-1]:
            parent = parent[p]
        node = parent[path[-1]]
        if not isinstance(node, _RawValue):
            return node
        if path in resolving:
            raise ConfigError(f"Circular reference detected at {'.'.join(path)}")

        resolving.add(path)
        try:
            res = evaluate_expr(node.raw, node.is_raw_assign, node.section)
        finally:
            resolving.discard(path)

        parent[path[-1]] = res
        return res

    def resolve_fully(d: dict[str, Any], prefix: tuple[str, ...]) -> None:
        for k, v in list(d.items()):
            path = prefix + (k,)
            if isinstance(v, _RawValue):
                resolve_node(path)
            elif isinstance(v, dict):
                resolve_fully(v, path)

    def lookup(path: tuple[str, ...]) -> tuple[bool, Any]:
        curr: Any = root
        for idx, part in enumerate(path):
            if not isinstance(curr, dict) or part not in curr:
                return False, None
            node = curr[part]
            if isinstance(node, _RawValue):
                node = resolve_node(path[:idx + 1])
            curr = node
        return True, curr

    def resolve_ref(ref_str: str, section: tuple[str, ...]) -> tuple[tuple[str, ...], Any]:
        if not ref_str:
            raise ConfigError("Empty reference")
        parts = tuple(ref_str.split("."))
        if len(parts) == 1 and section:
            local_path = section + parts
            found, val = lookup(local_path)
            if found:
                return local_path, val

        found, val = lookup(parts)
        if not found:
            raise ConfigError(f"Undefined reference: {ref_str}")
        return parts, val

    def resolve_env(spec: str) -> str:
        if ":-" in spec:
            var_name, default = spec.split(":-", 1)
            if not var_name:
                raise ConfigError("Empty environment variable name")
            if var_name in env:
                return str(env[var_name])
            return default
        if not spec:
            raise ConfigError("Empty environment variable name")
        if spec not in env:
            raise ConfigError(f"Missing environment variable: {spec}")
        return str(env[spec])

    def interpolate(chars: list[tuple[str, bool]], section: tuple[str, ...], allow_direct: bool) -> tuple[bool, Any]:
        # Returns (is_direct_single_ref, value)
        segments: list[tuple[bool, str]] = []
        literal: list[str] = []
        n = len(chars)
        i = 0
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
                if literal:
                    segments.append((False, "".join(literal)))
                    literal = []
                segments.append((True, expr))
                i = j + 1
                continue
            literal.append(ch)
            i += 1
        if literal:
            segments.append((False, "".join(literal)))

        if allow_direct and len(segments) == 1 and segments[0][0] and not segments[0][1].startswith("ENV:"):
            path, val = resolve_ref(segments[0][1], section)
            if isinstance(val, dict):
                resolve_fully(val, path)
            return True, copy.deepcopy(val)

        out = []
        for is_ref, s in segments:
            if not is_ref:
                out.append(s)
            elif s.startswith("ENV:"):
                out.append(resolve_env(s[4:]))
            else:
                _, val = resolve_ref(s, section)
                out.append(_format_scalar(val))
        return False, "".join(out)

    def evaluate_expr(expr: str, is_raw_assign: bool, section: tuple[str, ...]) -> Any:
        expr = expr.strip(WS)
        if not expr:
            raise ConfigError("Empty expression")

        if expr.startswith('"'):
            inner = _extract_double_quoted(expr)
            chars = _unescape_double_quoted(inner)
            if is_raw_assign:
                return "".join(c for c, _ in chars)
            _, interpolated = interpolate(chars, section, allow_direct=False)
            return interpolated

        if expr.startswith("'"):
            if len(expr) < 2 or not expr.endswith("'"):
                raise ConfigError("Unterminated single-quoted string")
            inner = expr[1:-1]
            if "'" in inner:
                raise ConfigError("Unexpected characters after closing quote")
            return inner

        if expr.startswith("["):
            if not expr.endswith("]"):
                raise ConfigError("Unterminated array")
            elems = _split_array_elements(expr[1:-1])
            return [evaluate_expr(e, is_raw_assign, section) for e in elems]

        if is_raw_assign:
            return _coerce_unquoted(expr)

        is_direct, val = interpolate([(c, False) for c in expr], section, allow_direct=True)
        if is_direct:
            return val
        return _coerce_unquoted(val)

    def walk_and_resolve(curr: dict[str, Any], prefix: tuple[str, ...]) -> None:
        for k, v in list(curr.items()):
            path = prefix + (k,)
            if isinstance(v, _RawValue):
                resolve_node(path)
            elif isinstance(v, dict):
                walk_and_resolve(v, path)

    walk_and_resolve(root, ())
    return root
=== END ===
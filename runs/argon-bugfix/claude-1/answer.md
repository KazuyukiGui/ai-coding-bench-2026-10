=== FILE: config_parser.py ===
import copy
import re
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""
    pass


IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
INT_DEC_RE = re.compile(r"[+-]?[0-9][0-9_]*")
INT_PREFIXED_RE = re.compile(r"[+-]?0[xXoObB][0-9a-fA-F_]+")
FLOAT_RE = re.compile(
    r"[+-]?(?:(?:[0-9][0-9_]*\.[0-9_]*|\.[0-9_]+)(?:[eE][+-]?[0-9_]+)?"
    r"|[0-9][0-9_]*[eE][+-]?[0-9_]+)"
)
WS = " \t"
SIMPLE_ESCAPES = {"\\": "\\", '"': '"', "n": "\n", "t": "\t", "r": "\r"}


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


def _join_continuation_lines(text: str) -> list[str]:
    raw_lines = text.replace("\r\n", "\n").split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()

    logical_lines: list[str] = []
    buffer: str | None = None

    for line in raw_lines:
        body = _strip_comment(line.strip(WS)).rstrip(WS)
        trailing = len(body) - len(body.rstrip("\\"))
        if trailing % 2 == 1:
            buffer = (buffer or "") + body[:-1]
            continue

        full = ((buffer or "") + body).strip(WS)
        buffer = None
        if full:
            logical_lines.append(full)

    if buffer is not None:
        raise ConfigError("File ends with a line continuation")

    return logical_lines


def _parse_double_quoted(expr: str) -> tuple[str, frozenset[int]]:
    # Returns (unescaped string, positions of '$' produced by '\$')
    out: list[str] = []
    protected: set[int] = set()
    i = 1
    n = len(expr)
    while i < n:
        ch = expr[i]
        if ch == "\\":
            if i + 1 >= n:
                raise ConfigError("Unterminated double-quoted string")
            nxt = expr[i + 1]
            if nxt in SIMPLE_ESCAPES:
                out.append(SIMPLE_ESCAPES[nxt])
            elif nxt == "$":
                protected.add(len(out))
                out.append("$")
            else:
                raise ConfigError(f"Invalid escape sequence: \\{nxt}")
            i += 2
        elif ch == '"':
            if i != n - 1:
                raise ConfigError("Unexpected characters after double-quoted string")
            return "".join(out), frozenset(protected)
        else:
            out.append(ch)
            i += 1
    raise ConfigError("Unterminated double-quoted string")


def _parse_single_quoted(expr: str) -> str:
    end = expr.find("'", 1)
    if end == -1:
        raise ConfigError("Unterminated single-quoted string")
    if end != len(expr) - 1:
        raise ConfigError("Unexpected characters after single-quoted string")
    return expr[1:end]


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


def _split_template(s: str, protected: frozenset[int] = frozenset()) -> list[tuple[bool, str]]:
    # Returns a list of (is_placeholder, text)
    pieces: list[tuple[bool, str]] = []
    buf: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "$" and i not in protected and i + 1 < n and s[i + 1] == "{":
            end = s.find("}", i + 2)
            if end == -1:
                raise ConfigError("Unterminated interpolation")
            expr = s[i + 2:end]
            if not expr:
                raise ConfigError("Empty interpolation")
            if buf:
                pieces.append((False, "".join(buf)))
                buf = []
            pieces.append((True, expr))
            i = end + 1
        else:
            buf.append(s[i])
            i += 1
    if buf:
        pieces.append((False, "".join(buf)))
    return pieces


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

    if INT_DEC_RE.fullmatch(val):
        try:
            return int(val, 10)
        except ValueError:
            raise ConfigError(f"Invalid integer literal: {val}") from None

    if INT_PREFIXED_RE.fullmatch(val):
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

            curr = root
            for p in parts:
                if p not in curr:
                    curr[p] = {}
                elif not isinstance(curr[p], dict):
                    raise ConfigError(f"Section conflicts with existing key: {sec_str}")
                curr = curr[p]
            current_section = parts
            continue

        eq = line.find("=")
        if eq == -1:
            raise ConfigError(f"Invalid syntax in line: {line}")
        if eq > 0 and line[eq - 1] == ":":
            key_part = line[:eq - 1]
            is_raw = True
        else:
            key_part = line[:eq]
            is_raw = False
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

    def resolve_node(parent: dict[str, Any], key: str, path: tuple[str, ...]) -> Any:
        node = parent[key]
        if not isinstance(node, _RawValue):
            return node
        if path in resolving:
            raise ConfigError(f"Circular reference detected at {'.'.join(path)}")

        resolving.add(path)
        try:
            res = evaluate_expr(node.raw, node.is_raw_assign, node.section)
        finally:
            resolving.discard(path)

        parent[key] = res
        return res

    def resolve_dict(d: dict[str, Any], path: tuple[str, ...]) -> None:
        if path in resolving:
            raise ConfigError(f"Circular reference detected at {'.'.join(path)}")

        resolving.add(path)
        try:
            for k in list(d):
                sub_path = path + (k,)
                v = resolve_node(d, k, sub_path)
                if isinstance(v, dict):
                    resolve_dict(v, sub_path)
        finally:
            resolving.discard(path)

    def lookup(path: tuple[str, ...]) -> tuple[bool, Any]:
        curr: Any = root
        for i, part in enumerate(path):
            if not isinstance(curr, dict) or part not in curr:
                return False, None
            curr = resolve_node(curr, part, path[:i + 1])
        if isinstance(curr, dict):
            resolve_dict(curr, path)
        return True, curr

    def resolve_ref(ref_str: str, section: tuple[str, ...]) -> Any:
        parts = tuple(ref_str.split("."))
        for p in parts:
            if not IDENT_RE.fullmatch(p):
                raise ConfigError(f"Invalid reference: {ref_str}")

        if len(parts) == 1 and section:
            found, val = lookup(section + parts)
            if found:
                return val

        found, val = lookup(parts)
        if not found:
            raise ConfigError(f"Undefined reference: {ref_str}")
        return val

    def resolve_env(env_spec: str) -> str:
        sep = env_spec.find(":-")
        if sep >= 0:
            var_name, default = env_spec[:sep], env_spec[sep + 2:]
        else:
            var_name, default = env_spec, None
        if not var_name:
            raise ConfigError("Empty environment variable name")
        if var_name in env:
            return str(env[var_name])
        if default is not None:
            return default
        raise ConfigError(f"Missing environment variable: {var_name}")

    def render(pieces: list[tuple[bool, str]], section: tuple[str, ...]) -> str:
        out = []
        for is_placeholder, content in pieces:
            if not is_placeholder:
                out.append(content)
            elif content.startswith("ENV:"):
                out.append(resolve_env(content[4:]))
            else:
                out.append(_format_scalar(resolve_ref(content, section)))
        return "".join(out)

    def evaluate_expr(expr: str, is_raw_assign: bool, section: tuple[str, ...]) -> Any:
        expr = expr.strip(WS)
        if not expr:
            raise ConfigError("Empty expression")

        if expr.startswith('"'):
            inner, protected = _parse_double_quoted(expr)
            if is_raw_assign:
                return inner
            return render(_split_template(inner, protected), section)

        if expr.startswith("'"):
            return _parse_single_quoted(expr)

        if expr.startswith("["):
            if not expr.endswith("]"):
                raise ConfigError("Unterminated array")
            elems = _split_array_elements(expr[1:-1])
            return [evaluate_expr(e, is_raw_assign, section) for e in elems]

        if is_raw_assign:
            return _coerce_unquoted(expr)

        pieces = _split_template(expr)
        if len(pieces) == 1 and pieces[0][0] and not pieces[0][1].startswith("ENV:"):
            return copy.deepcopy(resolve_ref(pieces[0][1], section))
        return _coerce_unquoted(render(pieces, section))

    resolve_dict(root, ())
    return root
=== END ===
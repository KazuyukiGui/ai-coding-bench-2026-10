=== FILE: config_parser.py ===
import copy
import re
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""
    pass


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

VALID_INT_RE = re.compile(
    r"^[+-]?(?:0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*|"
    r"0[oO][0-7](?:_?[0-7])*|"
    r"0[bB][01](?:_?[01])*|"
    r"[0-9](?:_?[0-9])*)$"
)
VALID_FLOAT_RE = re.compile(
    r"^[+-]?(?:"
    r"(?:[0-9](?:_?[0-9])*\.(?:[0-9](?:_?[0-9])*)?|\.[0-9](?:_?[0-9])*)(?:[eE][+-]?[0-9](?:_?[0-9])*)?|"
    r"[0-9](?:_?[0-9])*[eE][+-]?[0-9](?:_?[0-9])*"
    r")$"
)

INVALID_INT_LIKE_RE = re.compile(
    r"^[+-]?(?:0[xX][0-9a-fA-F_]*|0[oO][0-7_]*|0[bB][01_]*|(?=.*[0-9])[0-9_]+)$"
)
INVALID_FLOAT_LIKE_RE = re.compile(
    r"^[+-]?(?=.*[0-9])(?:[0-9_]*\.[0-9_]*(?:[eE][+-]?[0-9_]*)?|[0-9_]+[eE][+-]?[0-9_]*)$"
)


class _RawValue:
    def __init__(self, raw: str, is_raw_assign: bool, section: tuple[str, ...]):
        self.raw = raw
        self.is_raw_assign = is_raw_assign
        self.section = section


def _strip_comment_stateful(
    line: str, in_single: bool, in_double: bool
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


def _is_continuation(s: str) -> bool:
    count = 0
    i = len(s) - 1
    while i >= 0 and s[i] == "\\":
        count += 1
        i -= 1
    return (count % 2) == 1


def _join_continuation_lines(text: str) -> list[str]:
    raw_lines = text.splitlines()
    logical_lines: list[str] = []
    buffer = ""
    continuing = False
    in_single = False
    in_double = False

    for line in raw_lines:
        clean, in_single, in_double = _strip_comment_stateful(line, in_single, in_double)
        if continuing:
            clean = clean.strip()
        else:
            clean = clean.strip()
            if not clean:
                in_single = False
                in_double = False
                continue

        if _is_continuation(clean):
            buffer += clean[:-1]
            continuing = True
        else:
            buffer += clean
            logical_lines.append(buffer)
            buffer = ""
            continuing = False
            in_single = False
            in_double = False

    if continuing:
        raise ConfigError("File ends with line continuation")

    return logical_lines


def _unescape_double_quoted(s: str) -> tuple[str, set[int]]:
    out: list[str] = []
    escaped_dollars: set[int] = set()
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == '"':
            raise ConfigError("Unescaped double quote inside double-quoted string")
        if ch == "\\":
            if i + 1 >= len(s):
                raise ConfigError("Trailing backslash in string")
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "r":
                out.append("\r")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            elif nxt == "$":
                escaped_dollars.add(len(out))
                out.append("$")
            else:
                raise ConfigError(f"Invalid escape sequence: \\{nxt}")
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out), escaped_dollars


def _split_array_elements(content: str) -> list[str]:
    content = content.strip()
    if not content:
        return []
    elements = []
    current = []
    bracket_depth = 0
    brace_depth = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(content):
        ch = content[i]
        if ch == "\\" and in_double:
            if i + 1 >= len(content):
                raise ConfigError("Trailing backslash in array element")
            current.append(content[i:i + 2])
            i += 2
            continue
        if ch == "'" and not in_double and brace_depth == 0:
            in_single = not in_single
        elif ch == '"' and not in_single and brace_depth == 0:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "$" and i + 1 < len(content) and content[i + 1] == "{":
                brace_depth += 1
                current.append("${")
                i += 2
                continue
            elif ch == "}" and brace_depth > 0:
                brace_depth -= 1
            elif brace_depth == 0:
                if ch == "[":
                    bracket_depth += 1
                elif ch == "]":
                    bracket_depth -= 1
                    if bracket_depth < 0:
                        raise ConfigError("Unbalanced brackets in array")
                elif ch == "," and bracket_depth == 0:
                    elem = "".join(current).strip()
                    if not elem:
                        raise ConfigError("Empty element in array")
                    elements.append(elem)
                    current = []
                    i += 1
                    continue
        current.append(ch)
        i += 1

    if in_single or in_double or bracket_depth != 0 or brace_depth != 0:
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

    if VALID_INT_RE.match(val):
         stripped = val.lstrip("+-")
        if stripped.startswith(("0x", "0X", "0o", "0O", "0b", "0B")):
            return int(val, 0)
        return int(val, 10)

    if VALID_FLOAT_RE.match(val):
        return float(val)

    if INVALID_INT_LIKE_RE.match(val) or INVALID_FLOAT_LIKE_RE.match(val):
        raise ConfigError(f"Invalid number literal: {val}")

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
        if line.startswith("[") and line.endswith("]") and "=" not in line:
            sec_str = line[1:-1]
            if not sec_str:
                raise ConfigError("Empty section name")
            parts = tuple(sec_str.split("."))
            for p in parts:
                if not IDENT_RE.match(p):
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

        eq_idx = line.find("=")
        if eq_idx == -1:
            raise ConfigError(f"Invalid syntax in line: {line}")

        if eq_idx > 0 and line[eq_idx - 1] == ":":
            key_part = line[:eq_idx - 1]
            val_part = line[eq_idx + 1:]
            is_raw = True
        else:
            key_part = line[:eq_idx]
            val_part = line[eq_idx + 1:]
            is_raw = False

        key = key_part.strip()
        val_str = val_part.strip()

        if not IDENT_RE.match(key):
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
                resolving.remove(path)

            target = root
            for p in path[:-1]:
                target = target[p]
            target[path[-1]] = res
            return res

        if isinstance(node, dict):
            for k, v in list(node.items()):
                node[k] = resolve_node(path + (k,), v)
            return node

        return node

    def resolve_ref(ref_str: str, section: tuple[str, ...]) -> Any:
        if not ref_str:
            raise ConfigError("Empty reference")
        parts = tuple(ref_str.split("."))
        for p in parts:
            if not IDENT_RE.match(p):
                raise ConfigError(f"Invalid reference path: {ref_str}")

        if len(parts) == 1 and section:
            sec_dict: Any = root
            for p in section:
                sec_dict = sec_dict[p]
            if isinstance(sec_dict, dict) and parts[0] in sec_dict:
                local_path = section + parts
                return resolve_node(local_path, sec_dict[parts[0]])

        curr: Any = root
        curr_path: tuple[str, ...] = ()
        for p in parts:
            if isinstance(curr, _RawValue):
                curr = resolve_node(curr_path, curr)
            if not isinstance(curr, dict) or p not in curr:
                raise ConfigError(f"Undefined reference: {ref_str}")
            curr = curr[p]
            curr_path = curr_path + (p,)

        return resolve_node(curr_path, curr)

    def interpolate_string(
        s: str,
        section: tuple[str, ...],
        escaped_dollars: set[int],
        is_quoted: bool,
    ) -> tuple[bool, Any]:
        out: list[str] = []
        i = 0
        n = len(s)

        while i < n:
            if s[i] == "$" and i not in escaped_dollars and i + 1 < n and s[i + 1] == "{":
                start = i
                end = s.find("}", i + 2)
                if end == -1:
                    raise ConfigError(f"Unterminated interpolation in: {s}")
                expr = s[i + 2:end]
                if not expr:
                    raise ConfigError("Empty interpolation")

                if expr.startswith("ENV:"):
                    env_spec = expr[4:]
                    if ":-" in env_spec:
                        var_name, default = env_spec.split(":-", 1)
                    else:
                        var_name = env_spec
                        default = None

                    if not var_name or not IDENT_RE.match(var_name):
                        raise ConfigError(f"Invalid environment variable name: {var_name}")

                    if var_name in env:
                        val = env[var_name]
                    elif default is not None:
                        val = default
                    else:
                        raise ConfigError(f"Missing environment variable: {var_name}")
                    out.append(val)
                else:
                    val = resolve_ref(expr, section)
                    if not is_quoted and start == 0 and end == n - 1:
                        return True, copy.deepcopy(val)
                    out.append(_format_scalar(val))

                i = end + 1
            else:
                out.append(s[i])
                i += 1

        return False, "".join(out)

    def evaluate_expr(expr: str, is_raw_assign: bool, section: tuple[str, ...]) -> Any:
        expr = expr.strip()
        if not expr:
            raise ConfigError("Empty expression")

        if expr.startswith('"'):
            if not expr.endswith('"') or len(expr) < 2:
                raise ConfigError("Unterminated double-quoted string")
            inner, escaped_dollars = _unescape_double_quoted(expr[1:-1])
            if is_raw_assign:
                return inner
            _, interpolated = interpolate_string(inner, section, escaped_dollars, True)
            return interpolated

        if expr.startswith("'"):
            if not expr.endswith("'") or len(expr) < 2:
                raise ConfigError("Unterminated single-quoted string")
            inner = expr[1:-1]
            if "'" in inner:
                raise ConfigError("Single quote inside single-quoted string")
            return inner

        if expr.startswith("["):
            if not expr.endswith("]"):
                raise ConfigError("Unterminated array")
            elems = _split_array_elements(expr[1:-1])
            return [evaluate_expr(e, is_raw_assign, section) for e in elems]

        if is_raw_assign:
            return _coerce_unquoted(expr)

        is_direct, val = interpolate_string(expr, section, set(), False)
        if is_direct:
            return val
        return _coerce_unquoted(val)

    def walk_and_resolve(curr: dict[str, Any], prefix: tuple[str, ...]) -> None:
        for k, v in list(curr.items()):
            path = prefix + (k,)
            if isinstance(v, _RawValue):
                resolve_node(path, v)
            elif isinstance(v, dict):
                walk_and_resolve(v, path)

    walk_and_resolve(root, ())
    return root
=== END ===

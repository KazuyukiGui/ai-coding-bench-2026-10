=== FILE: config_parser.py ===
import copy
import re
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""
    pass


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
INT_RE = re.compile(
    r"^[+-]?(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|[0-9_]*[0-9][0-9_]*)$"
)
FLOAT_RE = re.compile(
    r"^[+-]?(?:(?:[0-9_]*[0-9][0-9_]*\.[0-9_]*|\.[0-9_]*[0-9][0-9_]*)(?:[eE][+-]?[0-9_]+)?|[0-9_]*[0-9][0-9_]*[eE][+-]?[0-9_]+)$"
)
ASSIGN_RE = re.compile(r":?=")


class _RawValue:
    def __init__(self, raw: str, is_raw_assign: bool, section: tuple[str, ...]):
        self.raw = raw
        self.is_raw_assign = is_raw_assign
        self.section = section


def _strip_comment(
    line: str, in_single: bool = False, in_double: bool = False
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
    if not text:
        return []
    if text.endswith("\r\n"):
        text = text[:-2]
    elif text.endswith("\n"):
        text = text[:-1]
    raw_lines = re.split(r"\r?\n", text)

    logical_lines: list[str] = []
    buffer = ""
    continuing = False
    in_single = False
    in_double = False

    for line in raw_lines:
        no_comment, in_single, in_double = _strip_comment(line, in_single, in_double)
        clean = no_comment.strip(" \t")
        if not clean and not continuing:
            in_single = False
            in_double = False
            continue

        bs_count = len(clean) - len(clean.rstrip("\\"))
        if bs_count % 2 == 1:
            buffer += clean[:-1]
            continuing = True
        else:
            buffer += clean
            final_line = buffer.strip(" \t")
            if final_line:
                logical_lines.append(final_line)
            buffer = ""
            continuing = False
            in_single = False
            in_double = False

    if continuing:
        raise ConfigError("Line continuation at end of file")

    return logical_lines


def _parse_double_quoted(expr: str) -> tuple[str, set[int]]:
    if len(expr) < 2 or not expr.startswith('"'):
        raise ConfigError("Invalid double-quoted string")
    out: list[str] = []
    escaped_dollars: set[int] = set()
    i = 1
    closed = False
    while i < len(expr):
        ch = expr[i]
        if ch == '"':
            if i != len(expr) - 1:
                raise ConfigError("Extra characters after closing double quote")
            closed = True
            break
        if ch == "\\":
            if i + 1 >= len(expr):
                raise ConfigError("Trailing backslash in double-quoted string")
            nxt = expr[i + 1]
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

    if not closed:
        raise ConfigError("Unterminated double-quoted string")
    return "".join(out), escaped_dollars


def _parse_single_quoted(expr: str) -> str:
    if not expr.startswith("'") or not expr.endswith("'") or len(expr) < 2:
        raise ConfigError("Unterminated single-quoted string")
    inner = expr[1:-1]
    if "'" in inner:
        raise ConfigError("Single quote inside single-quoted string")
    return inner


def _split_array_elements(content: str, is_raw_assign: bool = False) -> list[str]:
    content = content.strip()
    if not content:
        return []
    elements: list[str] = []
    current: list[str] = []
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
            current.append(content[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if not is_raw_assign and ch == "$" and i + 1 < len(content) and content[i + 1] == "{":
                brace_depth += 1
                current.append("${")
                i += 2
                continue
            elif not is_raw_assign and ch == "}" and brace_depth > 0:
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
        raise ConfigError("Unterminated string, bracket, or interpolation in array")

    last = "".join(current).strip()
    if last:
        elements.append(last)
    return elements


def _find_interpolations(s: str, escaped_dollars: set[int]) -> list[tuple[int, int, str]]:
    matches: list[tuple[int, int, str]] = []
    i = 0
    while i < len(s):
        if s[i] == "$" and i not in escaped_dollars and i + 1 < len(s) and s[i + 1] == "{":
            close_idx = s.find("}", i + 2)
            if close_idx == -1:
                raise ConfigError(f"Unterminated interpolation in: {s}")
            expr = s[i + 2 : close_idx]
            if not expr:
                raise ConfigError("Empty interpolation: ${}")
            if expr.startswith("ENV:"):
                env_spec = expr[4:]
                var_name = env_spec.split(":-", 1)[0] if ":-" in env_spec else env_spec
                if not var_name or not IDENT_RE.match(var_name):
                    raise ConfigError(f"Invalid environment variable in interpolation: {expr}")
            else:
                parts = expr.split(".")
                for p in parts:
                    if not p or not IDENT_RE.match(p):
                        raise ConfigError(f"Invalid reference path in interpolation: {expr}")
            matches.append((i, close_idx + 1, expr))
            i = close_idx + 1
        else:
            i += 1
    return matches


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

    if INT_RE.match(val):
        if re.match(r"^[+-]?0[xXoObB]_", val):
            raise ConfigError(f"Invalid integer literal: {val}")
        try:
            return int(val, 0)
        except ValueError as e:
            raise ConfigError(f"Invalid integer literal: {val}") from e

    if FLOAT_RE.match(val):
        try:
            return float(val)
        except ValueError as e:
            raise ConfigError(f"Invalid float literal: {val}") from e

    if any(c.isspace() or c in ('"', "'") for c in val):
        raise ConfigError(f"Invalid unquoted string: {val}")

    return val


def _validate_syntax(expr: str, is_raw_assign: bool) -> None:
    expr = expr.strip()
    if not expr:
        raise ConfigError("Empty expression")

    if expr.startswith('"'):
        inner, escaped_dollars = _parse_double_quoted(expr)
        if not is_raw_assign:
            _find_interpolations(inner, escaped_dollars)
        return

    if expr.startswith("'"):
        _parse_single_quoted(expr)
        return

    if expr.startswith("["):
        if not expr.endswith("]"):
            raise ConfigError("Unterminated array")
        elems = _split_array_elements(expr[1:-1], is_raw_assign)
        for e in elems:
            _validate_syntax(e, is_raw_assign)
        return

    if is_raw_assign:
        _coerce_unquoted(expr)
    else:
        matches = _find_interpolations(expr, set())
        if not matches:
            _coerce_unquoted(expr)


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

        m = ASSIGN_RE.search(line)
        if not m:
            raise ConfigError(f"Invalid syntax in line: {line}")

        is_raw = m.group(0) == ":="
        key = line[: m.start()].strip(" \t")
        val_str = line[m.end() :].strip(" \t")

        if not IDENT_RE.match(key):
            raise ConfigError(f"Invalid key name: {key}")
        if not val_str:
            raise ConfigError(f"Empty value for key: {key}")

        _validate_syntax(val_str, is_raw)

        target = root
        for p in current_section:
            target = target[p]

        if key in target and isinstance(target[key], dict):
            raise ConfigError(f"Key conflicts with existing section: {key}")

        target[key] = _RawValue(val_str, is_raw, current_section)

    resolving: set[tuple[str, ...]] = set()

    def resolve_node(path: tuple[str, ...], node: Any) -> Any:
        if path in resolving:
            raise ConfigError(f"Circular reference detected at {'.'.join(path)}")

        if isinstance(node, _RawValue):
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
            resolving.add(path)
            try:
                for k in list(node.keys()):
                    resolve_node(path + (k,), node[k])
            finally:
                resolving.remove(path)
            return node

        return node

    def resolve_path(path: tuple[str, ...]) -> tuple[bool, Any]:
        curr: Any = root
        for i, part in enumerate(path):
            if not IDENT_RE.match(part):
                raise ConfigError(f"Invalid reference path: {'.'.join(path)}")
            if not isinstance(curr, dict) or part not in curr:
                return False, None
            nxt = curr[part]
            if i < len(path) - 1:
                if isinstance(nxt, _RawValue):
                    curr = resolve_node(path[: i + 1], nxt)
                else:
                    curr = nxt
            else:
                curr = resolve_node(path, nxt)
        return True, curr

    def resolve_ref(ref_str: str, section: tuple[str, ...]) -> Any:
        if not ref_str:
            raise ConfigError("Empty reference")
        parts = tuple(ref_str.split("."))
        for p in parts:
            if not IDENT_RE.match(p):
                raise ConfigError(f"Invalid reference: {ref_str}")

        if len(parts) == 1 and section:
            local_path = section + parts
            found, val = resolve_path(local_path)
            if found:
                return val

        found, val = resolve_path(parts)
        if not found:
            raise ConfigError(f"Undefined reference: {ref_str}")
        return val

    def interpolate_string(
        s: str, escaped_dollars: set[int], section: tuple[str, ...], is_unquoted: bool
    ) -> tuple[bool, Any]:
        matches = _find_interpolations(s, escaped_dollars)
        if not matches:
            return False, s

        if is_unquoted and len(matches) == 1 and matches[0][0] == 0 and matches[0][1] == len(s):
            expr = matches[0][2]
            if not expr.startswith("ENV:"):
                val = resolve_ref(expr, section)
                return True, copy.deepcopy(val)

        out: list[str] = []
        last_idx = 0
        for start, end, expr in matches:
            out.append(s[last_idx:start])
            if expr.startswith("ENV:"):
                env_spec = expr[4:]
                if ":-" in env_spec:
                    var_name, default = env_spec.split(":-", 1)
                    val = env.get(var_name, default)
                else:
                    var_name = env_spec
                    if var_name not in env:
                        raise ConfigError(f"Missing environment variable: {var_name}")
                    val = env[var_name]
                out.append(val)
            else:
                val = resolve_ref(expr, section)
                out.append(_format_scalar(val))
            last_idx = end

        out.append(s[last_idx:])
        return False, "".join(out)

    def evaluate_expr(expr: str, is_raw_assign: bool, section: tuple[str, ...]) -> Any:
        expr = expr.strip()
        if not expr:
            raise ConfigError("Empty expression")

        if expr.startswith('"'):
            inner, escaped_dollars = _parse_double_quoted(expr)
            if is_raw_assign:
                return inner
            _, interpolated = interpolate_string(inner, escaped_dollars, section, is_unquoted=False)
            return interpolated

        if expr.startswith("'"):
            return _parse_single_quoted(expr)

        if expr.startswith("["):
            if not expr.endswith("]"):
                raise ConfigError("Unterminated array")
            elems = _split_array_elements(expr[1:-1], is_raw_assign)
            return [evaluate_expr(e, is_raw_assign, section) for e in elems]

        if is_raw_assign:
            return _coerce_unquoted(expr)

        is_direct, val = interpolate_string(expr, set(), section, is_unquoted=True)
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

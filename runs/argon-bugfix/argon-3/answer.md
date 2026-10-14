=== FILE: config_parser.py ===
import copy
import re
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""
    pass


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

_DEC_DIGITS = r"[0-9](?:_?[0-9])*"
VALID_INT_RE = re.compile(
    rf"^[+-]?(?:0[xX][0-9a-fA-F](?:_?[0-9a-fA-F])*|0[oO][0-7](?:_?[0-7])*|0[bB][01](?:_?[01])*|{_DEC_DIGITS})$"
)
VALID_FLOAT_RE = re.compile(
    rf"^[+-]?(?:(?:{_DEC_DIGITS}\.(?:{_DEC_DIGITS})?|\.{_DEC_DIGITS})(?:[eE][+-]?{_DEC_DIGITS})?|{_DEC_DIGITS}[eE][+-]?{_DEC_DIGITS})$"
)
NUM_LIKE_RE = re.compile(
    r"^[+-]?(?:"
    r"0[xX][0-9a-fA-F_]*|"
    r"0[oO][0-7_]*|"
    r"0[bB][01_]*|"
    r"(?=[0-9_]*[0-9])[0-9_]+|"
    r"(?=[0-9_.]*[0-9])[0-9_]*\.[0-9_]*(?:[eE][+-]?[0-9_]*)?|"
    r"(?=[0-9_]*[0-9])[0-9_]+[eE][+-]?[0-9_]*"
    r")$"
)


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


def _count_trailing_backslashes(s: str) -> int:
    count = 0
    for ch in reversed(s):
        if ch == "\\":
            count += 1
        else:
            break
    return count


def _join_continuation_lines(text: str) -> list[str]:
    if text.endswith("\r\n"):
        raw_lines = re.split(r"\r?\n", text[:-2])
    elif text.endswith("\n"):
        raw_lines = re.split(r"\r?\n", text[:-1])
    elif text:
        raw_lines = re.split(r"\r?\n", text)
    else:
        raw_lines = []

    logical_lines: list[str] = []
    buffer = ""
    continuing = False
    in_single = False
    in_double = False

    for line in raw_lines:
        if not continuing:
            in_single = False
            in_double = False
        no_comment, in_single, in_double = _strip_comment(line, in_single, in_double)
        trimmed = no_comment.strip(" \t")
        if not trimmed and not continuing:
            continue

        num_bs = _count_trailing_backslashes(trimmed)
        if num_bs % 2 == 1:
            buffer += trimmed[:-1]
            continuing = True
        else:
            buffer += trimmed
            logical_lines.append(buffer.strip(" \t"))
            buffer = ""
            continuing = False

    if continuing:
        raise ConfigError("Line continuation at end of file")

    return logical_lines


def _unescape_double_quoted(s: str) -> tuple[str, set[int]]:
    out: list[str] = []
    escaped_dollars: set[int] = set()
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == '"':
            raise ConfigError("Unescaped double quote in string")
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
    content = content.strip(" \t")
    if not content:
        return []
    elements: list[str] = []
    current: list[str] = []
    depth = 0
    brace_depth = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(content):
        ch = content[i]
        if ch == "\\" and in_double:
            current.append(content[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "$" and i + 1 < len(content) and content[i + 1] == "{":
                brace_depth += 1
                current.append("${")
                i += 2
                continue
            elif ch == "}" and brace_depth > 0:
                brace_depth -= 1
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth < 0:
                    raise ConfigError("Unbalanced brackets in array")
            elif ch == "," and depth == 0 and brace_depth == 0:
                elem = "".join(current).strip(" \t")
                if not elem:
                    raise ConfigError("Empty element in array")
                elements.append(elem)
                current = []
                i += 1
                continue
        current.append(ch)
        i += 1

    if in_single or in_double or depth != 0 or brace_depth != 0:
        raise ConfigError("Unterminated string, interpolation, or bracket in array")

    last = "".join(current).strip(" \t")
    if last:
        elements.append(last)
    return elements


def _coerce_unquoted(val: str) -> Any:
    if not val:
        return ""

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

    if NUM_LIKE_RE.match(val):
        raise ConfigError(f"Invalid numeric literal: {val}")

    if any(c.isspace() or c in ('"', "'", "[", "]") for c in val):
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
            sec_str = line[1:-1].strip(" \t")
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
            key_part = line[: eq_idx - 1]
            val_part = line[eq_idx + 1 :]
            is_raw = True
        else:
            key_part = line[:eq_idx]
            val_part = line[eq_idx + 1 :]
            is_raw = False

        key = key_part.strip(" \t")
        val_str = val_part.strip(" \t")

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
                resolve_node(path + (k,), v)
            return node

        return node

    def _lookup_and_resolve(path: tuple[str, ...]) -> tuple[bool, Any]:
        curr: Any = root
        for idx, part in enumerate(path):
            if not isinstance(curr, dict) or part not in curr:
                return False, None
            nxt = curr[part]
            subpath = path[: idx + 1]
            if isinstance(nxt, _RawValue):
                nxt = resolve_node(subpath, nxt)
            curr = nxt
        if isinstance(curr, dict):
            resolve_node(path, curr)
        return True, curr

    def resolve_ref(ref_str: str, section: tuple[str, ...]) -> Any:
        if not ref_str:
            raise ConfigError("Empty reference")
        parts = tuple(ref_str.split("."))
        for p in parts:
            if not IDENT_RE.match(p):
                raise ConfigError(f"Invalid reference path: {ref_str}")

        if len(parts) == 1 and section:
            local_path = section + parts
            found, val = _lookup_and_resolve(local_path)
            if found:
                return copy.deepcopy(val) if isinstance(val, (dict, list)) else val

        found, val = _lookup_and_resolve(parts)
        if not found:
            raise ConfigError(f"Undefined reference: {ref_str}")
        return copy.deepcopy(val) if isinstance(val, (dict, list)) else val

    def interpolate_string(
        s: str,
        section: tuple[str, ...],
        escaped_dollars: set[int] | None = None,
        is_quoted: bool = False,
    ) -> tuple[bool, Any]:
        if escaped_dollars is None:
            escaped_dollars = set()

        tokens: list[tuple[str, str]] = []
        lit_buf: list[str] = []
        i = 0
        while i < len(s):
            if (
                s[i] == "$"
                and i not in escaped_dollars
                and i + 1 < len(s)
                and s[i + 1] == "{"
            ):
                if lit_buf:
                    tokens.append(("lit", "".join(lit_buf)))
                    lit_buf = []
                end_idx = s.find("}", i + 2)
                if end_idx == -1:
                    raise ConfigError(f"Unclosed interpolation in: {s}")
                expr = s[i + 2 : end_idx]
                if not expr:
                    raise ConfigError("Empty interpolation")
                tokens.append(("ref", expr))
                i = end_idx + 1
            else:
                lit_buf.append(s[i])
                i += 1

        if lit_buf:
            tokens.append(("lit", "".join(lit_buf)))

        if not any(kind == "ref" for kind, _ in tokens):
            return False, s

        if not is_quoted and len(tokens) == 1 and tokens[0][0] == "ref":
            expr = tokens[0][1]
            if not expr.startswith("ENV:"):
                val = resolve_ref(expr, section)
                return True, val

        out: list[str] = []
        for kind, content in tokens:
            if kind == "lit":
                out.append(content)
            else:
                if content.startswith("ENV:"):
                    env_spec = content[4:]
                    if ":-" in env_spec:
                        var_name, default = env_spec.split(":-", 1)
                        if not IDENT_RE.match(var_name):
                            raise ConfigError(f"Invalid environment variable name: {var_name}")
                        val = env.get(var_name, default)
                    else:
                        var_name = env_spec
                        if not IDENT_RE.match(var_name):
                            raise ConfigError(f"Invalid environment variable name: {var_name}")
                        if var_name not in env:
                            raise ConfigError(f"Missing environment variable: {var_name}")
                        val = env[var_name]
                    out.append(val)
                else:
                    val = resolve_ref(content, section)
                    out.append(_format_scalar(val))

        return False, "".join(out)

    def evaluate_expr(expr: str, is_raw_assign: bool, section: tuple[str, ...]) -> Any:
        expr = expr.strip(" \t")
        if not expr:
            raise ConfigError("Empty expression")

        if expr.startswith('"'):
            if not expr.endswith('"') or len(expr) < 2:
                raise ConfigError("Unterminated double-quoted string")
            inner, escaped_dollars = _unescape_double_quoted(expr[1:-1])
            if is_raw_assign:
                return inner
            _, interpolated = interpolate_string(
                inner, section, escaped_dollars, is_quoted=True
            )
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

        is_direct, val = interpolate_string(expr, section, is_quoted=False)
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

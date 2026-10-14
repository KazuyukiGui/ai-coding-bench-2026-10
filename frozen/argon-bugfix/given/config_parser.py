import re
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""
    pass


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
INT_RE = re.compile(r"^[+-]?(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|[0-9][0-9_]*)$")
FLOAT_RE = re.compile(r"^[+-]?(?:[0-9][0-9_]*\.[0-9_]*|\.[0-9_]+)(?:[eE][+-]?[0-9_]+)?$|^[+-]?[0-9][0-9_]*[eE][+-]?[0-9_]+$")


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
    raw_lines = text.splitlines()
    logical_lines: list[str] = []
    buffer = ""
    continuing = False

    for line in raw_lines:
        clean = _strip_comment(line).strip()
        if not clean and not continuing:
            continue

        if clean.endswith("\\"):
            clean = clean[:-1].rstrip()
            buffer += clean
            continuing = True
        else:
            buffer += clean
            logical_lines.append(buffer)
            buffer = ""
            continuing = False

    if continuing:
        logical_lines.append(buffer)

    return logical_lines


def _unescape_double_quoted(s: str, is_raw_assign: bool) -> str:
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
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
                if is_raw_assign:
                    out.append("$")
                else:
                    out.append("\\$")
            else:
                raise ConfigError(f"Invalid escape sequence: \\{nxt}")
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


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

    if INT_RE.match(val):
        try:
            return int(val, 0)
        except ValueError:
            pass

    if FLOAT_RE.match(val):
        try:
            return float(val)
        except ValueError:
            pass

    if any(c.isspace() or c in ('"', "'") for c in val):
        raise ConfigError(f"Invalid unquoted string: {val}")

    return val


def _lookup_path(root: dict[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    curr: Any = root
    for part in path:
        if not isinstance(curr, dict) or part not in curr:
            return False, None
        curr = curr[part]
    return True, curr


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

        is_raw = False
        if ":=" in line:
            key_part, val_part = line.split(":=", 1)
            is_raw = True
        elif "=" in line:
            key_part, val_part = line.split("=", 1)
        else:
            raise ConfigError(f"Invalid syntax in line: {line}")

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
        if not isinstance(node, _RawValue):
            return node
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

    def interpolate_string(s: str, section: tuple[str, ...]) -> tuple[bool, Any]:
        # Returns (is_direct_single_ref, value)
        pattern = re.compile(r"(?<!\\)\$\{([^}]*)\}")
        matches = list(pattern.finditer(s))
        if not matches:
            return False, s.replace("\\$", "$")

        if len(matches) == 1 and matches[0].span() == (0, len(s)):
            expr = matches[0].group(1)
            if not expr.startswith("ENV:"):
                val = resolve_ref(expr, section)
                return True, val

        out = []
        last_idx = 0
        for m in matches:
            out.append(s[last_idx:m.start()].replace("\\$", "$"))
            expr = m.group(1)
            if not expr:
                raise ConfigError("Empty interpolation")
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
            last_idx = m.end()

        out.append(s[last_idx:].replace("\\$", "$"))
        return False, "".join(out)

    def resolve_ref(ref_str: str, section: tuple[str, ...]) -> Any:
        if not ref_str:
            raise ConfigError("Empty reference")
        parts = tuple(ref_str.split("."))
        if len(parts) == 1 and section:
            local_path = section + parts
            found, val = _lookup_path(root, local_path)
            if found:
                return resolve_node(local_path, val)

        found, val = _lookup_path(root, parts)
        if not found:
            raise ConfigError(f"Undefined reference: {ref_str}")
        return resolve_node(parts, val)

    def evaluate_expr(expr: str, is_raw_assign: bool, section: tuple[str, ...]) -> Any:
        expr = expr.strip()
        if not expr:
            raise ConfigError("Empty expression")

        if expr.startswith('"'):
            if not expr.endswith('"') or len(expr) < 2:
                raise ConfigError("Unterminated double-quoted string")
            inner = _unescape_double_quoted(expr[1:-1], is_raw_assign)
            if is_raw_assign:
                return inner
            _, interpolated = interpolate_string(inner, section)
            if not isinstance(interpolated, str):
                return _format_scalar(interpolated)
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

        is_direct, val = interpolate_string(expr, section)
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

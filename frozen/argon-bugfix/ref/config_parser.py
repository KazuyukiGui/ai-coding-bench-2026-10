import copy
import re
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""
    pass


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
INT_RE = re.compile(r"^[+-]?(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|[0-9][0-9_]*)$")
FLOAT_RE = re.compile(
    r"^[+-]?(?:[0-9][0-9_]*\.[0-9_]*|\.[0-9_]+)(?:[eE][+-]?[0-9_]+)?$"
    r"|^[+-]?[0-9][0-9_]*[eE][+-]?[0-9_]+$"
)


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


def _has_line_continuation(s: str) -> bool:
    count = 0
    i = len(s) - 1
    while i >= 0 and s[i] == "\\":
        count += 1
        i -= 1
    return count % 2 == 1


def _join_continuation_lines(text: str) -> list[str]:
    raw_lines = text.splitlines()
    logical_lines: list[str] = []
    buffer = ""
    continuing = False

    for line in raw_lines:
        clean = _strip_comment(line).strip()
        if not clean and not continuing:
            continue

        if _has_line_continuation(clean):
            clean = clean[:-1]
            buffer += clean
            continuing = True
        else:
            buffer += clean
            if buffer:
                logical_lines.append(buffer)
            buffer = ""
            continuing = False

    if continuing:
        raise ConfigError("Unexpected end of file after line continuation")

    return logical_lines


def _check_double_quoted(expr: str, is_raw_assign: bool) -> str:
    """ダブルクォート文字列の構文とエスケープを検証し、内部表現に変換する。
    通常代入時の \\$ は後続の変数展開と区別するため \\x00 に一時置換する。
    """
    if len(expr) < 2 or not expr.startswith('"'):
        raise ConfigError("Invalid double-quoted string")

    out = []
    i = 1
    closed = False
    while i < len(expr):
        ch = expr[i]
        if ch == '"':
            if i != len(expr) - 1:
                raise ConfigError("Unexpected characters after closing double quote")
            closed = True
            break
        if ch == "\\":
            if i + 1 >= len(expr) - 1 and expr[-1] == '"' and i + 1 == len(expr) - 1:
                # 最後の " がエスケープされている場合は閉じクォートがない
                raise ConfigError("Unterminated double-quoted string")
            if i + 1 >= len(expr):
                raise ConfigError("Unterminated escape in double-quoted string")
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
                if is_raw_assign:
                    out.append("$")
                else:
                    out.append("\x00")
            else:
                raise ConfigError(f"Invalid escape sequence: \\{nxt}")
            i += 2
        else:
            out.append(ch)
            i += 1

    if not closed:
        raise ConfigError("Unterminated double-quoted string")
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
    saw_comma = False

    while i < len(content):
        ch = content[i]
        if ch == "\\" and in_double:
            if i + 1 >= len(content):
                raise ConfigError("Unterminated escape in array")
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
                saw_comma = True
                i += 1
                continue
        current.append(ch)
        i += 1

    if in_single or in_double or depth != 0:
        raise ConfigError("Unterminated string or bracket in array")

    last = "".join(current).strip()
    if last:
        elements.append(last)
    elif saw_comma and not elements:
        raise ConfigError("Empty element in array")

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
            raise ConfigError(f"Invalid integer literal: {val}")

    if FLOAT_RE.match(val):
        try:
            return float(val)
        except ValueError:
            raise ConfigError(f"Invalid float literal: {val}")

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


def _find_assignment_operator(line: str) -> tuple[str, str, bool]:
    idx_raw = line.find(":=")
    idx_eq = line.find("=")
    if idx_eq == -1:
        raise ConfigError(f"Invalid syntax in line: {line}")

    if idx_raw != -1 and idx_raw <= idx_eq:
        return line[:idx_raw], line[idx_raw + 2:], True
    return line[:idx_eq], line[idx_eq + 1:], False


def _validate_ref_syntax(ref_str: str) -> tuple[str, ...]:
    if not ref_str:
        raise ConfigError("Empty reference")
    parts = tuple(ref_str.split("."))
    for p in parts:
        if not IDENT_RE.match(p):
            raise ConfigError(f"Invalid reference path: {ref_str}")
    return parts


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    if env is None:
        env = {}

    lines = _join_continuation_lines(text)
    root: dict[str, Any] = {}
    current_section: tuple[str, ...] = ()

    for line in lines:
        if line.startswith("["):
            if not line.endswith("]"):
                raise ConfigError(f"Invalid section header: {line}")
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

        key_part, val_part, is_raw = _find_assignment_operator(line)
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
        elif isinstance(node, dict):
            resolving.add(path)
            try:
                walk_and_resolve(node, path)
            finally:
                resolving.remove(path)
            return node
        return node

    def resolve_ref(ref_str: str, section: tuple[str, ...]) -> Any:
        parts = _validate_ref_syntax(ref_str)
        if len(parts) == 1 and section:
            local_path = section + parts
            found, val = _lookup_path(root, local_path)
            if found:
                return resolve_node(local_path, val)

        found, val = _lookup_path(root, parts)
        if not found:
            raise ConfigError(f"Undefined reference: {ref_str}")
        return resolve_node(parts, val)

    def resolve_env(env_spec: str) -> str:
        if ":-" in env_spec:
            var_name, default = env_spec.split(":-", 1)
            if not var_name:
                raise ConfigError("Empty environment variable name")
            return env.get(var_name, default)
        else:
            var_name = env_spec
            if not var_name:
                raise ConfigError("Empty environment variable name")
            if var_name not in env:
                raise ConfigError(f"Missing environment variable: {var_name}")
            return env[var_name]

    def interpolate(s: str, section: tuple[str, ...], is_quoted: bool) -> tuple[bool, Any]:
        """文字列 s 内の ${...} を展開する。
        戻り値: (単一変数参照により型をそのまま引き継ぐか, 展開結果の値)
        """
        out: list[str] = []
        i = 0
        tokens: list[tuple[str, str]] = []  # ("lit", str) or ("ref", expr)

        while i < len(s):
            idx = s.find("$", i)
            if idx == -1:
                tokens.append(("lit", s[i:]))
                break
            if idx > i:
                tokens.append(("lit", s[i:idx]))

            if idx + 1 < len(s) and s[idx + 1] == "{":
                end_idx = s.find("}", idx + 2)
                if end_idx == -1:
                    raise ConfigError("Unclosed interpolation '${'")
                expr = s[idx + 2:end_idx]
                if not expr or "{" in expr:
                    raise ConfigError(f"Invalid interpolation expression: {expr}")
                tokens.append(("ref", expr))
                i = end_idx + 1
            else:
                tokens.append(("lit", "$"))
                i = idx + 1

        if (
            not is_quoted
            and len(tokens) == 1
            and tokens[0][0] == "ref"
            and not tokens[0][1].startswith("ENV:")
        ):
            val = resolve_ref(tokens[0][1], section)
            return True, copy.deepcopy(val)

        for kind, content in tokens:
            if kind == "lit":
                out.append(content.replace("\x00", "$"))
            else:
                if content.startswith("ENV:"):
                    out.append(resolve_env(content[4:]))
                else:
                    val = resolve_ref(content, section)
                    out.append(_format_scalar(val))

        return False, "".join(out)

    def evaluate_expr(expr: str, is_raw_assign: bool, section: tuple[str, ...]) -> Any:
        expr = expr.strip()
        if not expr:
            raise ConfigError("Empty expression")

        if expr.startswith('"'):
            inner = _check_double_quoted(expr, is_raw_assign)
            if is_raw_assign:
                return inner
            _, res = interpolate(inner, section, is_quoted=True)
            return res

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

        if "\\" in expr:
            # クォートなしの値では \$ のようなエスケープは仕様上定義されていない
            pass

        is_direct, val = interpolate(expr, section, is_quoted=False)
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

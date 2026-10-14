=== FILE: config_parser.py ===
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


# --- Regular Expressions for Validation ---

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_ENV_VAR_RE = re.compile(r"^[A-Za-z0-9_]+$")
_INT_RE = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)$")
_FLOAT_RE = re.compile(
    r"^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+(?:[eE][+-]?[0-9]+)?|[eE][+-]?[0-9]+)$"
)


# --- AST Nodes ---

class Expr:
    pass


@dataclass(frozen=True)
class LiteralExpr(Expr):
    value: int | float | bool | str | None


@dataclass(frozen=True)
class RefExpr(Expr):
    path: list[str]


@dataclass(frozen=True)
class EnvRefExpr(Expr):
    var_name: str
    default: str | None = None


@dataclass(frozen=True)
class InterpStringExpr(Expr):
    parts: list[str | RefExpr | EnvRefExpr]


@dataclass(frozen=True)
class ListExpr(Expr):
    elements: list[Expr]


@dataclass(frozen=True)
class BinaryAddExpr(Expr):
    left: Expr
    right: Expr


# --- Block Tree Node ---

@dataclass
class BlockNode:
    parent: BlockNode | None = None
    entries: dict[str, BlockNode | Expr] = field(default_factory=dict)
    own_keys: set[str] = field(default_factory=set)
    parent_path: list[str] | None = None
    inheritance_resolved: bool = False


# --- Lexer ---

@dataclass(frozen=True)
class Token:
    type: str
    value: Any
    start: int
    end: int


def _is_ascii_alpha(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _is_ascii_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_ident_start(ch: str) -> bool:
    return _is_ascii_alpha(ch) or ch == "_"


def _is_ident_Part(ch: str) -> bool:
    return _is_ascii_alpha(ch) or _is_ascii_digit(ch) or ch in ("_", "-")


def _parse_interpolation_content(content: str) -> RefExpr | EnvRefExpr:
    if not content or "\n" in content or "\r" in content:
        raise ConfigError("Invalid interpolation syntax")

    if content.startswith("env:"):
        rest = content[4:]
        if ":-" in rest:
            var_name, default_val = rest.split(":-", 1)
            if "${" in default_val:
                raise ConfigError("Nested interpolation in env default is not supported")
        else:
            var_name = rest
            default_val = None

        if not _ENV_VAR_RE.match(var_name):
            raise ConfigError(f"Invalid environment variable name: {var_name!r}")
        return EnvRefExpr(var_name=var_name, default=default_val)

    parts = content.split(".")
    for part in parts:
        if not _IDENT_RE.match(part):
            raise ConfigError(f"Invalid reference path in '${{{content}}}'")
    return RefExpr(path=parts)


def _tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(text)

    single_char_tokens = {
        ".": "DOT",
        "=": "EQUALS",
        ":": "COLON",
        ";": "SEMI",
        ",": "COMMA",
        "{": "LBRACE",
        "}": "RBRACE",
        "[": "LBRACKET",
        "]": "RBRACKET",
        "+": "PLUS",
        "-": "MINUS",
    }

    while i < n:
        ch = text[i]

        # Whitespace
        if ch in (" ", "\t"):
            i += 1
            continue

        # Newlines
        if ch == "\n":
            tokens.append(Token("NEWLINE", "\n", i, i + 1))
            i += 1
            continue
        if ch == "\r":
            if i + 1 < n and text[i + 1] == "\n":
                tokens.append(Token("NEWLINE", "\r\n", i, i + 2))
                i += 2
                continue
            raise ConfigError("Unexpected carriage return '\\r'")

        # Comments
        if ch == "#" or (ch == "/" and i + 1 < n and text[i + 1] == "/"):
            while i < n and text[i] != "\n" and not (
                text[i] == "\r" and i + 1 < n and text[i + 1] == "\n"
            ):
                i += 1
            continue

        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            end_idx = text.find("*/", i + 2)
            if end_idx == -1:
                raise ConfigError("Unclosed block comment")
            i = end_idx + 2
            continue

        # Single-character punctuation
        if ch in single_char_tokens:
            tokens.append(Token(single_char_tokens[ch], ch, i, i + 1))
            i += 1
            continue

        # String literal
        if ch == '"':
            start = i
            i += 1
            parts: list[str | RefExpr | EnvRefExpr] = []
            buf: list[str] = []
            closed = False

            while i < n:
                c = text[i]
                if c in ("\n", "\r"):
                    raise ConfigError("Unescaped newline in string literal")
                if c == '"':
                    if buf or not parts:
                        parts.append("".join(buf))
                    i += 1
                    closed = True
                    break
                if c == "\\":
                    if i + 1 >= n:
                        raise ConfigError("Unclosed string literal after escape")
                    esc = text[i + 1]
                    if esc == '"':
                        buf.append('"')
                    elif esc == "\\":
                        buf.append("\\")
                    elif esc == "n":
                        buf.append("\n")
                    elif esc == "t":
                        buf.append("\t")
                    elif esc == "r":
                        buf.append("\r")
                    elif esc == "$":
                        buf.append("$")
                    else:
                        raise ConfigError(f"Invalid escape sequence '\\{esc}'")
                    i += 2
                    continue
                if c == "$" and i + 1 < n and text[i + 1] == "{":
                    if buf:
                        parts.append("".join(buf))
                        buf.clear()
                    i += 2
                    interp_start = i
                    while i < n and text[i] != "}":
                        if text[i] in ("\n", "\r", '"'):
                            raise ConfigError("Unclosed interpolation in string literal")
                        if text[i] == "$" and i + 1 < n and text[i + 1] == "{":
                            raise ConfigError("Nested '${...}' is not supported")
                        i += 1
                    if i >= n:
                        raise ConfigError("Unclosed interpolation in string literal")
                    interp_content = text[interp_start:i]
                    parts.append(_parse_interpolation_content(interp_content))
                    i += 1  # consume '}'
                    continue

                buf.append(c)
                i += 1

            if not closed:
                raise ConfigError("Unclosed string literal")
            tokens.append(Token("STRING", parts, start, i))
            continue

        # Standalone reference ${...}
        if ch == "$":
            if i + 1 >= n or text[i + 1] != "{":
                raise ConfigError("Unexpected '$'")
            start = i
            i += 2
            interp_start = i
            while i < n and text[i] != "}":
                if text[i] in ("\n", "\r"):
                    raise ConfigError("Unclosed '${...}' reference")
                if text[i] == "$" and i + 1 < n and text[i + 1] == "{":
                    raise ConfigError("Nested '${...}' is not supported")
                i += 1
            if i >= n:
                raise ConfigError("Unclosed '${...}' reference")
            interp_content = text[interp_start:i]
            ref_ast = _parse_interpolation_content(interp_content)
            i += 1  # consume '}'
            tokens.append(Token("REF", ref_ast, start, i))
            continue

        # Identifier
        if _is_ident_start(ch):
            start = i
            i += 1
            while i < n and _is_ident_Part(text[i]):
                i += 1
            tokens.append(Token("IDENT", text[start:i], start, i))
            continue

        # Number (unsigned; leading +/- handled by parser)
        if _is_ascii_digit(ch):
            start = i
            i += 1
            while i < n:
                c = text[i]
                if _is_ascii_alpha(c) or _is_ascii_digit(c) or c in (".", "_"):
                    i += 1
                elif c in ("+", "-") and text[i - 1] in ("e", "E"):
                    i += 1
                else:
                    break
            tokens.append(Token("NUMBER", text[start:i], start, i))
            continue

        raise ConfigError(f"Unexpected character: {ch!r}")

    tokens.append(Token("EOF", None, n, n))
    return tokens


# --- Parser ---

def _parse_number_literal(raw: str) -> LiteralExpr:
    if _INT_RE.match(raw):
        return LiteralExpr(int(raw))
    if _FLOAT_RE.match(raw):
        return LiteralExpr(float(raw))
    raise ConfigError(f"Invalid number literal: {raw!r}")


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def current(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        if tok.type != "EOF":
            self.pos += 1
        return tok

    def skip_newlines(self) -> None:
        while self.current().type == "NEWLINE":
            self.advance()

    def parse_path(self) -> list[str]:
        tok = self.current()
        if tok.type != "IDENT":
            raise ConfigError(f"Expected identifier in path, got {tok.type}")
        self.advance()
        segments = [tok.value]
        prev_end = tok.end

        while self.current().type == "DOT":
            dot_tok = self.current()
            if dot_tok.start != prev_end:
                raise ConfigError("Unexpected whitespace before '.' in path")
            self.advance()
            next_tok = self.current()
            if next_tok.type != "IDENT" or next_tok.start != dot_tok.end:
                raise ConfigError("Expected identifier immediately after '.' in path")
            self.advance()
            segments.append(next_tok.value)
            prev_end = next_tok.end

        return segments

    def parse_config_root(self) -> BlockNode:
        root = BlockNode()
        self.parse_statement_list(root, inside_block=False)
        if self.current().type != "EOF":
            raise ConfigError("Unexpected token at top level")
        return root

    def parse_statement_list(self, block: BlockNode, inside_block: bool) -> None:
        while True:
            while self.current().type in ("NEWLINE", "SEMI"):
                self.advance()

            tok = self.current()
            if tok.type == "EOF":
                if inside_block:
                    raise ConfigError("Unclosed block '{'")
                break
            if tok.type == "RBRACE":
                if not inside_block:
                    raise ConfigError("Unexpected '}'")
                break

            path = self.parse_path()
            tok = self.current()

            if tok.type == "EQUALS":
                self.advance()
                expr = self.parse_expr()
                self._assign_value(block, path, expr)
                self._require_statement_separator(inside_block)
            elif tok.type in ("COLON", "LBRACE", "NEWLINE"):
                parent_path: list[str] | None = None
                if tok.type == "COLON":
                    self.advance()
                    parent_path = self.parse_path()

                self.skip_newlines()
                if self.current().type != "LBRACE":
                    raise ConfigError("Expected '{' for block definition")
                self.advance()  # consume '{'

                target_block = self._get_or_create_block(block, path)
                if parent_path is not None:
                    if target_block.parent_path is not None:
                        raise ConfigError(
                            "Multiple inheritance specifications on the same block"
                        )
                    target_block.parent_path = parent_path

                self.parse_statement_list(target_block, inside_block=True)

                if self.current().type != "RBRACE":
                    raise ConfigError("Expected '}' at end of block")
                self.advance()  # consume '}'
                self._require_statement_separator(inside_block)
            else:
                raise ConfigError(f"Expected '=' or '{{' after path, got {tok.type}")

    def _require_statement_separator(self, inside_block: bool) -> None:
        tok = self.current()
        if tok.type in ("NEWLINE", "SEMI"):
            self.advance()
        elif tok.type == "EOF":
            return
        elif inside_block and tok.type == "RBRACE":
            return
        else:
            raise ConfigError(
                f"Expected newline or ';' after statement, got {tok.type}"
            )

    def _get_or_create_block(self, start_block: BlockNode, path: list[str]) -> BlockNode:
        curr = start_block
        for seg in path:
            existing = curr.entries.get(seg)
            if existing is None:
                new_block = BlockNode(parent=curr)
                curr.entries[seg] = new_block
                curr.own_keys.add(seg)
                curr = new_block
            elif isinstance(existing, BlockNode):
                curr.own_keys.add(seg)
                curr = existing
            else:
                raise ConfigError(
                    f"Type conflict: cannot redefine non-dict key {seg!r} as block"
                )
        return curr

    def _assign_value(
        self, start_block: BlockNode, path: list[str], expr: Expr
    ) -> None:
        curr = self._get_or_create_block(start_block, path[:-1])
        last_key = path[-1]
        existing = curr.entries.get(last_key)
        if isinstance(existing, BlockNode):
            raise ConfigError(
                f"Type conflict: cannot overwrite block {last_key!r} with value"
            )
        curr.entries[last_key] = expr
        curr.own_keys.add(last_key)

    def parse_expr(self) -> Expr:
        left = self.parse_term()
        while self.current().type == "PLUS":
            self.advance()  # consume '+'
            self.skip_newlines()
            right = self.parse_term()
            left = BinaryAddExpr(left=left, right=right)
        return left

    def parse_term(self) -> Expr:
        tok = self.current()

        if tok.type in ("PLUS", "MINUS"):
            self.advance()
            num_tok = self.current()
            if num_tok.type != "NUMBER" or num_tok.start != tok.end:
                raise ConfigError("Expected number immediately after sign")
            self.advance()
            return _parse_number_literal(tok.value + num_tok.value)

        if tok.type == "NUMBER":
            self.advance()
            return _parse_number_literal(tok.value)

        if tok.type == "STRING":
            self.advance()
            parts: list[str | RefExpr | EnvRefExpr] = tok.value
            if len(parts) == 1 and isinstance(parts[0], str):
                return LiteralExpr(parts[0])
            return InterpStringExpr(parts=parts)

        if tok.type == "REF":
            self.advance()
            return tok.value

        if tok.type == "IDENT":
            self.advance()
            if self.current().type == "DOT":
                raise ConfigError("Bare path is not allowed as a value")
            if tok.value == "true":
                return LiteralExpr(True)
            if tok.value == "false":
                return LiteralExpr(False)
            if tok.value == "null":
                return LiteralExpr(None)
            raise ConfigError(f"Unexpected identifier {tok.value!r} in value position")

        if tok.type == "LBRACKET":
            self.advance()  # consume '['
            elements: list[Expr] = []
            self.skip_newlines()
            if self.current().type == "RBRACKET":
                self.advance()
                return ListExpr(elements=elements)

            while True:
                elem = self.parse_expr()
                elements.append(elem)
                self.skip_newlines()
                sep = self.current()
                if sep.type == "COMMA":
                    self.advance()
                    self.skip_newlines()
                    if self.current().type == "RBRACKET":
                        self.advance()
                        return ListExpr(elements=elements)
                elif sep.type == "RBRACKET":
                    self.advance()
                    return ListExpr(elements=elements)
                else:
                    raise ConfigError("Expected ',' or ']' in list literal")

        raise ConfigError(f"Unexpected token {tok.type} in expression")


# --- Inheritance Resolution ---

def _is_ancestor(ancestor: BlockNode, node: BlockNode) -> bool:
    curr = node.parent
    while curr is not None:
        if curr is ancestor:
            return True
        curr = curr.parent
    return False


def _deep_copy_node(
    node: BlockNode | Expr, new_parent: BlockNode
) -> BlockNode | Expr:
    if isinstance(node, Expr):
        return node
    copied = BlockNode(parent=new_parent, inheritance_resolved=True)
    for k, v in node.entries.items():
        copied.entries[k] = _deep_copy_node(v, copied)
        copied.own_keys.add(k)
    return copied


def _merge_inherited_into_child(
    base_block: BlockNode, child_block: BlockNode, from_direct_inheritance: bool
) -> None:
    """
    Merges resolved `base_block` as a lower-priority base under `child_block`.
    Preserves `child_block` and its existing sub-BlockNode instances in-place.
    """
    new_entries: dict[str, BlockNode | Expr] = {}

    for k, base_val in base_block.entries.items():
        if k not in child_block.entries:
            new_entries[k] = _deep_copy_node(base_val, child_block)
            if from_direct_inheritance:
                child_block.own_keys.add(k)
        else:
            child_val = child_block.entries[k]
            if isinstance(base_val, BlockNode) and isinstance(child_val, BlockNode):
                _merge_inherited_into_child(base_val, child_val, from_direct_inheritance)
                new_entries[k] = child_val
                if from_direct_inheritance:
                    child_block.own_keys.add(k)
            elif isinstance(base_val, Expr) and isinstance(child_val, Expr):
                if k in child_block.own_keys:
                    new_entries[k] = child_val
                else:
                    new_entries[k] = base_val
                    if from_direct_inheritance:
                        child_block.own_keys.add(k)
            else:
                raise ConfigError(
                    f"Type conflict in inheritance for key {k!r}: cannot merge dict and non-dict"
                )

    for k, child_val in child_block.entries.items():
        if k not in new_entries:
            new_entries[k] = child_val

    child_block.entries = new_entries


class _InheritanceResolver:
    def __init__(self) -> None:
        self.resolving_self: set[int] = set()
        self.resolving_subtree: set[int] = set()

    def resolve_all(self, root: BlockNode) -> None:
        self.resolve_subtree(root)

    def resolve_self_and_ancestors(self, block: BlockNode) -> None:
        if block.parent is not None:
            self.resolve_self_and_ancestors(block.parent)

        if block.inheritance_resolved:
            return

        if block.parent_path is None:
            block.inheritance_resolved = True
            return

        block_id = id(block)
        if block_id in self.resolving_self:
            raise ConfigError("Circular block inheritance detected")

        self.resolving_self.add(block_id)
        try:
            target = self._lookup_parent_block(block, block.parent_path)
            if (
                target is block
                or _is_ancestor(target, block)
                or _is_ancestor(block, target)
            ):
                raise ConfigError(
                    "Block cannot inherit from itself, its ancestor, or its descendant"
                )

            self.resolve_subtree(target)
            _merge_inherited_into_child(
                target, block, from_direct_inheritance=True
            )
            block.inheritance_resolved = True
        finally:
            self.resolving_self.remove(block_id)

    def resolve_subtree(self, block: BlockNode) -> None:
        self.resolve_self_and_ancestors(block)

        block_id = id(block)
        if block_id in self.resolving_subtree:
            raise ConfigError("Circular block inheritance detected")

        self.resolving_subtree.add(block_id)
        try:
            for child in list(block.entries.values()):
                if isinstance(child, BlockNode):
                    self.resolve_subtree(child)
        finally:
            self.resolving_subtree.remove(block_id)

    def _lookup_parent_block(
        self, child_block: BlockNode, path: list[str]
    ) -> BlockNode:
        head = path[0]
        tail = path[1:]

        scope = child_block.parent
        while scope is not None:
            self.resolve_self_and_ancestors(scope)
            if head in scope.entries:
                break
            scope = scope.parent

        if scope is None:
            raise ConfigError(f"Undefined parent block reference: {'.'.join(path)!r}")

        curr = scope.entries[head]
        if not isinstance(curr, BlockNode):
            raise ConfigError(
                f"Parent reference {'.'.join(path)!r} does not point to a block"
            )
        self.resolve_self_and_ancestors(curr)

        for seg in tail:
            if seg not in curr.entries:
                raise ConfigError(
                    f"Undefined parent block reference: {'.'.join(path)!r}"
                )
            nxt = curr.entries[seg]
            if not isinstance(nxt, BlockNode):
                raise ConfigError(
                    f"Parent reference {'.'.join(path)!r} does not point to a block"
                )
            curr = nxt
            self.resolve_self_and_ancestors(curr)

        return curr


# --- Expression Evaluator ---

def _copy_value(val: Any) -> Any:
    if isinstance(val, list):
        return [_copy_value(item) for item in val]
    return val


class _Evaluator:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.evaluating: set[tuple[int, str]] = set()
        self.cache: dict[tuple[int, str], Any] = {}

    def evaluate_block(self, block: BlockNode) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, node in block.entries.items():
            if isinstance(node, BlockNode):
                result[key] = self.evaluate_block(node)
            else:
                result[key] = _copy_value(self. evaluate_key(block, key))
        return result

    def evaluate_key(self, block: BlockNode, key: str) -> Any:
        state_key = (id(block), key)
        if state_key in self.cache:
            return self.cache[state_key]

        if state_key in self.evaluating:
            raise ConfigError(f"Circular variable reference involving {key!r}")

        node = block.entries.get(key)
        if not isinstance(node, Expr):
            raise ConfigError(f"Key {key!r} is not an expression")

        self.evaluating.add(state_key)
        try:
            val = self.eval_expr(node, block)
            self.cache[state_key] = val
            return val
        finally:
            self.evaluating.remove(state_key)

    def eval_expr(self, expr: Expr, scope_block: BlockNode) -> Any:
        if isinstance(expr, LiteralExpr):
            return expr.value

        if isinstance(expr, EnvRefExpr):
            return self._eval_env_ref(expr)

        if isinstance(expr, RefExpr):
            return self._eval_var_ref(expr, scope_block)

        if isinstance(expr, InterpStringExpr):
            out: list[str] = []
            for part in expr.parts:
                if isinstance(part, str):
                    out.append(part)
                else:
                    val = self.eval_expr(part, scope_block)
                    out.append(self._format_interpolated(val))
            return "".join(out)

        if isinstance(expr, ListExpr):
            return [_copy_value(self.eval_expr(el, scope_block)) for el in expr.elements]

        if isinstance(expr, BinaryAddExpr):
            left_val = self.eval_expr(expr.left, scope_block)
            right_val = self.eval_expr(expr.right, scope_block)
            return self._eval_add(left_val, right_val)

        raise ConfigError("Unknown expression type")

    def _eval_env_ref(self, expr: EnvRefExpr) -> str:
        if expr.default is None:
            if expr.var_name not in self.env:
                raise ConfigError(f"Undefined environment variable: {expr.var_name!r}")
            return self.env[expr.var_name]
        else:
            val = self.env.get(expr.var_name, "")
            return val if val != "" else expr.default

    def _eval_var_ref(self, expr: RefExpr, scope_block: BlockNode) -> Any:
        head = expr.path[0]
        tail = expr.path[1:]

        curr_scope: BlockNode | None = scope_block
        while curr_scope is not None:
            if head in curr_scope.entries:
                break
            curr_scope = curr_scope.parent

        if curr_scope is None:
            raise ConfigError(f"Undefined variable reference: {'.'.join(expr.path)!r}")

        if not tail:
            target = curr_scope.entries[head]
            if isinstance(target, BlockNode):
                raise ConfigError(
                    f"Cannot reference block {head!r} as a value"
                )
            return _copy_value(self.evaluate_key(curr_scope, head))

        curr_node = curr_scope.entries[head]
        for seg in tail[:-1]:
            if not isinstance(curr_node, BlockNode) or seg not in curr_node.entries:
                raise ConfigError(
                    f"Invalid path reference: {'.'.join(expr.path)!r}"
                )
            curr_node = curr_node.entries[seg]

        last_seg = tail[-1]
        if not isinstance(curr_node, BlockNode) or last_seg not in curr_node.entries:
            raise ConfigError(
                f"Undefined variable reference: {'.'.join(expr.path)!r}"
            )

        target_node = curr_node.entries[last_seg]
        if isinstance(target_node, BlockNode):
            raise ConfigError(
                f"Cannot reference block {'.'.join(expr.path)!r} as a value"
            )
        return _copy_value(self.evaluate_key(curr_node, last_seg))

    @staticmethod
    def _format_interpolated(val: Any) -> str:
        if isinstance(val, str):
            return val
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, (int, float)):
            return str(val)
        if val is None:
            return "null"
        raise ConfigError(
            f"Cannot interpolate value of type {type(val).__name__} into string"
        )

    @staticmethod
    def _eval_add(left: Any, right: Any) -> Any:
        left_is_num = isinstance(left, (int, float)) and not isinstance(left, bool)
        right_is_num = isinstance(right, (int, float)) and not isinstance(right, bool)

        if left_is_num and right_is_num:
            return left + right
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        if isinstance(left, list) and isinstance(right, list):
            return _copy_value(left) + _copy_value(right)

        raise ConfigError(
            f"Unsupported operand types for +: {type(left).__name__} and {type(right).__name__}"
        )


# --- Public API ---

def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    """
    HCL Lite 形式の文字列 text を解析・評価し、結果の辞書を返す。
    env は環境変数の辞書であり、省略時または None の場合は空辞書として扱う。
    （os.environ は参照してはならない）
    """
    if not isinstance(text, str):
        raise ConfigError("Input text must be a string")

    env_dict: dict[str, str] = {} if env is None else dict(env)

    tokens = _tokenize(text)
    parser = _Parser(tokens)
    root = parser.parse_config_root()

    resolver = _InheritanceResolver()
    resolver.resolve_all(root)

    evaluator = _Evaluator(env_dict)
    return evaluator.evaluate_block(root)
=== END ===

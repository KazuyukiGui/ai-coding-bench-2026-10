=== FILE: config_parser.py ===
from dataclasses import dataclass
from enum import Enum, auto
import re
from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


class TokenType(Enum):
    IDENT = auto()
    RAW_NUMBER = auto()
    STRING = auto()
    REF = auto()
    DOT = auto()
    EQUALS = auto()
    COLON = auto()
    SEMICOLON = auto()
    COMMA = auto()
    PLUS = auto()
    MINUS = auto()
    LBRACE = auto()
    RBRACE = auto()
    LBRACKET = auto()
    RBRACKET = auto()
    NEWLINE = auto()
    EOF = auto()


@dataclass
class Token:
    type: TokenType
    value: Any
    start: int
    end: int


@dataclass
class LiteralNode:
    value: int | float | bool | None


@dataclass
class VarRefNode:
    path: list[str]


@dataclass
class EnvRefNode:
    var_name: str
    default: str | None


@dataclass
class StringNode:
    parts: list[str | VarRefNode | EnvRefNode]


@dataclass
class ListNode:
    elements: list["ExprNode"]


TermNode = LiteralNode | VarRefNode | EnvRefNode | StringNode | ListNode


@dataclass
class ExprNode:
    terms: list[TermNode]


class BlockNode:
    def __init__(
        self,
        name: str,
        parent: "BlockNode | None",
        full_path: tuple[str, ...],
    ) -> None:
        self.name = name
        self.parent = parent
        self.full_path = full_path
        self.base_children: dict[str, BlockNode | ExprNode] = {}
        self.own_children: dict[str, BlockNode | ExprNode] = {}
        self.inherit_spec: list[str] | None = None
        self.children: dict[str, BlockNode | ExprNode] | None = None
        self.self_resolved: bool = False
        self.deep_resolved: bool = False


_ESCAPE_MAP: dict[str, str] = {
    '"': '"',
    "\\": "\\",
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "$": "$",
}

_PATH_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*$")
_ENV_VAR_RE = re.compile(r"^[A-Za-z0-9_]+$")
_INT_RE = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)$")
_FLOAT_RE = re.compile(
    r"^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+(?:[eE][+-]?[0-9]+)?|[eE][+-]?[0-9]+)$"
)

_SINGLE_CHAR_TOKENS: dict[str, TokenType] = {
    ".": TokenType.DOT,
    "=": TokenType.EQUALS,
    ":": TokenType.COLON,
    ";": TokenType.SEMICOLON,
    ",": TokenType.COMMA,
    "+": TokenType.PLUS,
    "-": TokenType.MINUS,
    "{": TokenType.LBRACE,
    "}": TokenType.RBRACE,
    "[": TokenType.LBRACKET,
    "]": TokenType.RBRACKET,
}


def _is_ident_start(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_"


def _is_ident_part(ch: str) -> bool:
    return (
        ("a" <= ch <= "z")
        or ("A" <= ch <= "Z")
        or ("0" <= ch <= "9")
        or ch in ("_", "-")
    )


def _is_num_char(ch: str) -> bool:
    return (
        ("0" <= ch <= "9")
        or ("a" <= ch <= "z")
        or ("A" <= ch <= "Z")
        or ch in ("_", ".")
    )


def _parse_ref_content(content: str) -> VarRefNode | EnvRefNode:
    if content.startswith("env:"):
        rest = content[4:]
        if ":-" in rest:
            var_name, default_val = rest.split(":-", 1)
        else:
            var_name, default_val = rest, None
        if not _ENV_VAR_RE.match(var_name):
            raise ConfigError(f"Invalid environment variable name: {var_name!r}")
        return EnvRefNode(var_name=var_name, default=default_val)
    else:
        if not _PATH_RE.match(content):
            raise ConfigError(f"Invalid reference path: {content!r}")
        return VarRefNode(path=content.split("."))


def _tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    pos = 0
    n = len(text)

    while pos < n:
        ch = text[pos]

        # Whitespace
        if ch in (" ", "\t"):
            pos += 1
            continue

        # Newlines
        if ch == "\n":
            tokens.append(Token(TokenType.NEWLINE, "\n", pos, pos + 1))
            pos += 1
            continue
        if ch == "\r":
            if pos + 1 < n and text[pos + 1] == "\n":
                tokens.append(Token(TokenType.NEWLINE, "\r\n", pos, pos + 2))
                pos += 2
                continue
            raise ConfigError("Unexpected carriage return without newline")

        # Line comments
        if ch == "#" or (ch == "/" and pos + 1 < n and text[pos + 1] == "/"):
            while pos < n and text[pos] != "\n" and text[pos : pos + 2] != "\r\n":
                if text[pos] == "\r":
                    raise ConfigError("Unexpected carriage return in comment")
                pos += 1
            continue

        # Block comments
        if ch == "/" and pos + 1 < n and text[pos + 1] == "*":
            end_idx = text.find("*/", pos + 2)
            if end_idx == -1:
                raise ConfigError("Unclosed block comment")
            pos = end_idx + 2
            continue

        # String literal
        if ch == '"':
            start = pos
            pos += 1
            parts: list[str | VarRefNode | EnvRefNode] = []
            buf: list[str] = []
            while True:
                if pos >= n:
                    raise ConfigError("Unclosed string literal")
                c = text[pos]
                if c in ("\n", "\r"):
                    raise ConfigError("Newline in string literal is not allowed")
                if c == '"':
                    pos += 1
                    if buf:
                        parts.append("".join(buf))
                    break
                if c == "\\":
                    pos += 1
                    if pos >= n:
                        raise ConfigError("Unclosed escape sequence in string")
                    esc = text[pos]
                    if esc not in _ESCAPE_MAP:
                        raise ConfigError(f"Invalid escape sequence: \\{esc}")
                    buf.append(_ESCAPE_MAP[esc])
                    pos += 1
                elif c == "$" and pos + 1 < n and text[pos + 1] == "{":
                    if buf:
                        parts.append("".join(buf))
                        buf = []
                    pos += 2
                    interp_buf: list[str] = []
                    while True:
                        if pos >= n or text[pos] in ("\n", "\r", '"'):
                            raise ConfigError("Unclosed interpolation in string")
                        if text[pos] == "}":
                            pos += 1
                            break
                        if text[pos] == "\\":
                            pos += 1
                            if pos >= n:
                                raise ConfigError(
                                    "Unclosed escape sequence in interpolation"
                                )
                            esc = text[pos]
                            if esc not in _ESCAPE_MAP:
                                raise ConfigError(f"Invalid escape sequence: \\{esc}")
                            interp_buf.append(_ESCAPE_MAP[esc])
                            pos += 1
                        elif (
                            text[pos] == "$"
                            and pos + 1 < n
                            and text[pos + 1] == "{"
                        ):
                            raise ConfigError("Nested interpolation is not supported")
                        else:
                            interp_buf.append(text[pos])
                            pos += 1
                    parts.append(_parse_ref_content("".join(interp_buf)))
                else:
                    buf.append(c)
                    pos += 1
            tokens.append(Token(TokenType.STRING, parts, start, pos))
            continue

        # Standalone reference ${...}
        if ch == "$":
            if pos + 1 >= n or text[pos + 1] != "{":
                raise ConfigError("Unexpected '$' outside of reference")
            start = pos
            pos += 2
            ref_buf: list[str] = []
            while True:
                if pos >= n or text[pos] in ("\n", "\r"):
                    raise ConfigError("Unclosed reference")
                if text[pos] == "}":
                    pos += 1
                    break
                if text[pos] == "$" and pos + 1 < n and text[pos + 1] == "{":
                    raise ConfigError("Nested reference is not supported")
                ref_buf.append(text[pos])
                pos += 1
            ref_node = _parse_ref_content("".join(ref_buf))
            tokens.append(Token(TokenType.REF, ref_node, start, pos))
            continue

        # Identifiers
        if _is_ident_start(ch):
            start = pos
            pos += 1
            while pos < n and _is_ident_part(text[pos]):
                pos += 1
            tokens.append(Token(TokenType.IDENT, text[start:pos], start, pos))
            continue

        # Numbers
        if "0" <= ch <= "9":
            start = pos
            while pos < n:
                if _is_num_char(text[pos]):
                    pos += 1
                elif (
                    text[pos] in ("+", "-")
                    and pos > start
                    and text[pos - 1] in ("e", "E")
                ):
                    pos += 1
                else:
                    break
            tokens.append(Token(TokenType.RAW_NUMBER, text[start:pos], start, pos))
            continue

        # Single-character symbols
        if ch in _SINGLE_CHAR_TOKENS:
            tokens.append(Token(_SINGLE_CHAR_TOKENS[ch], ch, pos, pos + 1))
            pos += 1
            continue

        raise ConfigError(f"Unexpected character: {ch!r}")

    tokens.append(Token(TokenType.EOF, None, n, n))
    return tokens


def _parse_number(raw: str) -> int | float:
    if _INT_RE.match(raw):
        return int(raw)
    if _FLOAT_RE.match(raw):
        return float(raw)
    raise ConfigError(f"Invalid number literal: {raw!r}")


class _Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    def current(self) -> Token:
        return self.tokens[self.pos]

    def advance(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def parse_root(self) -> BlockNode:
        root = BlockNode(name="", parent=None, full_path=())
        self.parse_statements(root, inside_block=False)
        return root

    def parse_statements(self, current_block: BlockNode, inside_block: bool) -> None:
        while True:
            while self.current().type in (TokenType.NEWLINE, TokenType.SEMICOLON):
                self.advance()

            tok = self.current()
            if tok.type == TokenType.EOF:
                if inside_block:
                    raise ConfigError("Unclosed block '{'")
                return

            if tok.type == TokenType.RBRACE:
                if not inside_block:
                    raise ConfigError("Unexpected '}'")
                return

            path = self.parse_path()
            tok = self.current()

            if tok.type == TokenType.EQUALS:
                self.advance()  # consume '='
                expr = self.parse_expr()
                self._check_statement_end(inside_block)
                self._assign_expr(current_block, path, expr)
            elif tok.type in (
                TokenType.COLON,
                TokenType.LBRACE,
                TokenType.NEWLINE,
            ):
                parent_path: list[str] | None = None
                if tok.type == TokenType.COLON:
                    self.advance()  # consume ':'
                    parent_path = self.parse_path()

                while self.current().type == TokenType.NEWLINE:
                    self.advance()

                if self.current().type != TokenType.LBRACE:
                    raise ConfigError("Expected '{' to start block")
                self.advance()  # consume '{'

                target_block = self._ensure_block(current_block, path)
                if parent_path is not None:
                    if target_block.inherit_spec is not None:
                        raise ConfigError(
                            f"Multiple inheritance specifications for block '{'.'.join(path)}'"
                        )
                    target_block.inherit_spec = parent_path

                self.parse_statements(target_block, inside_block=True)

                if self.current().type != TokenType.RBRACE:
                    raise ConfigError("Expected '}' to close block")
                self.advance()  # consume '}'
                self._check_statement_end(inside_block)
            else:
                raise ConfigError(
                    f"Expected '=' or '{{' after path, got {tok.type.name}"
                )

    def _check_statement_end(self, inside_block: bool) -> None:
        tok = self.current()
        if tok.type in (TokenType.NEWLINE, TokenType.SEMICOLON):
            self.advance()
            return
        if tok.type == TokenType.EOF and not inside_block:
            return
        if tok.type == TokenType.RBRACE and inside_block:
            return
        raise ConfigError(
            f"Expected newline or ';' after statement, got {tok.type.name}"
        )

    def parse_path(self) -> list[str]:
        tok = self.current()
        if tok.type != TokenType.IDENT:
            raise ConfigError(f"Expected identifier in path, got {tok.type.name}")
        self.advance()
        parts = [tok.value]
        while self.current().type == TokenType.DOT:
            self.advance()  # consume '.'
            next_tok = self.current()
            if next_tok.type != TokenType.IDENT:
                raise ConfigError("Expected identifier after '.' in path")
            self.advance()
            parts.append(next_tok.value)
        return parts

    def parse_expr(self) -> ExprNode:
        terms = [self.parse_term()]
        while self.current().type == TokenType.PLUS:
            self.advance()  # consume '+'
            while self.current().type == TokenType.NEWLINE:
                self.advance()
            terms.append(self.parse_term())
        return ExprNode(terms=terms)

    def parse_term(self) -> TermNode:
        tok = self.current()

        if tok.type == TokenType.STRING:
            self.advance()
            return StringNode(parts=tok.value)

        if tok.type == TokenType.RAW_NUMBER:
            self.advance()
            return LiteralNode(value=_parse_number(tok.value))

        if tok.type in (TokenType.PLUS, TokenType.MINUS):
            sign_tok = self.advance()
            num_tok = self.current()
            if num_tok.type != TokenType.RAW_NUMBER or sign_tok.end != num_tok.start:
                raise ConfigError("Expected number immediately after sign")
            self.advance()
            return LiteralNode(value=_parse_number(sign_tok.value + num_tok.value))

        if tok.type == TokenType.IDENT:
            self.advance()
            if tok.value == "true":
                return LiteralNode(value=True)
            if tok.value == "false":
                return LiteralNode(value=False)
            if tok.value == "null":
                return LiteralNode(value=None)
            raise ConfigError(f"Unexpected identifier in expression: {tok.value!r}")

        if tok.type == TokenType.REF:
            self.advance()
            return tok.value

        if tok.type == TokenType.LBRACKET:
            return self.parse_list()

        raise ConfigError(f"Unexpected token in expression: {tok.type.name}")

    def parse_list(self) -> ListNode:
        self.advance()  # consume '['
        while self.current().type == TokenType.NEWLINE:
            self.advance()

        elements: list[ExprNode] = []
        if self.current().type == TokenType.RBRACKET:
            self.advance()
            return ListNode(elements=elements)

        while True:
            elements.append(self.parse_expr())
            while self.current().type == TokenType.NEWLINE:
                self.advance()

            if self.current().type == TokenType.COMMA:
                self.advance()  # consume ','
                while self.current().type == TokenType.NEWLINE:
                    self.advance()
                if self.current().type == TokenType.RBRACKET:
                    self.advance()
                    break
            elif self.current().type == TokenType.RBRACKET:
                self.advance()
                break
            else:
                raise ConfigError("Expected ',' or ']' in list literal")

        return ListNode(elements=elements)

    def _ensure_block(self, start_block: BlockNode, path: list[str]) -> BlockNode:
        curr = start_block
        for part in path:
            if part in curr.own_children:
                existing = curr.own_children[part]
                if not isinstance(existing, BlockNode):
                    raise ConfigError(
                        f"Type conflict: '{part}' is already defined as a non-block"
                    )
                curr = existing
            else:
                new_block = BlockNode(
                    name=part,
                    parent=curr,
                    full_path=curr.full_path + (part,),
                )
                curr.own_children[part] = new_block
                curr = new_block
        return curr

    def _assign_expr(
        self, start_block: BlockNode, path: list[str], expr: ExprNode
    ) -> None:
        curr = self._ensure_block(start_block, path[:-1])
        last_key = path[-1]
        if last_key in curr.own_children and isinstance(
            curr.own_children[last_key], BlockNode
        ):
            raise ConfigError(
                f"Type conflict: '{last_key}' is already defined as a block"
            )
        curr.own_children[last_key] = expr


def _clone_resolved_node(
    node: BlockNode | ExprNode,
    new_parent: BlockNode,
    key: str,
) -> BlockNode | ExprNode:
    if isinstance(node, ExprNode):
        return node
    new_block = BlockNode(
        name=key,
        parent=new_parent,
        full_path=new_parent.full_path + (key,),
    )
    assert node.children is not None
    new_block.children = {
        k: _clone_resolved_node(v, new_block, k) for k, v in node.children.items()
    }
    new_block.self_resolved = True
    new_block.deep_resolved = True
    return new_block


def _merge_resolved_into_resolved(
    target_block: BlockNode,
    base_dict: dict[str, BlockNode | ExprNode],
    over_dict: dict[str, BlockNode | ExprNode],
) -> None:
    for k, v in over_dict.items():
        if k not in base_dict:
            base_dict[k] = _clone_resolved_node(v, target_block, k)
        else:
            existing = base_dict[k]
            if isinstance(existing, ExprNode) and isinstance(v, ExprNode):
                base_dict[k] = v
            elif isinstance(existing, BlockNode) and isinstance(v, BlockNode):
                assert existing.children is not None
                assert v.children is not None
                _merge_resolved_into_resolved(existing, existing.children, v.children)
            else:
                raise ConfigError(f"Type conflict on key '{k}' during merge")


def _merge_own_into_resolved(
    target_block: BlockNode,
    base_dict: dict[str, BlockNode | ExprNode],
    own_dict: dict[str, BlockNode | ExprNode],
) -> None:
    for k, v in own_dict.items():
        if k not in base_dict:
            base_dict[k] = v
        else:
            existing = base_dict[k]
            if isinstance(existing, ExprNode) and isinstance(v, ExprNode):
                base_dict[k] = v
            elif isinstance(existing, BlockNode) and isinstance(v, BlockNode):
                assert existing.children is not None
                if v.base_children:
                    _merge_resolved_into_resolved(v, v.base_children, existing.children)
                else:
                    v.base_children = {
                        ck: _clone_resolved_node(cv, v, ck)
                        for ck, cv in existing.children.items()
                    }
                base_dict[k] = v
            else:
                raise ConfigError(f"Type conflict on key '{k}' between parent and child")


class _InheritanceResolver:
    def __init__(self) -> None:
        self.resolving_self: set[tuple[str, ...]] = set()
        self.resolving_deep: set[tuple[str, ...]] = set()

    def resolve_self(self, block: BlockNode) -> None:
        if block.self_resolved:
            return
        if block.full_path in self.resolving_self:
            raise ConfigError("Circular block inheritance detected")
        self.resolving_self.add(block.full_path)

        current_dict: dict[str, BlockNode | ExprNode] = {
            k: _clone_resolved_node(v, block, k)
            for k, v in block.base_children.items()
        }

        if block.inherit_spec is not None:
            assert block.parent is not None
            parent_target = self.lookup_parent_block(block.parent, block.inherit_spec)
            b_path = block.full_path
            t_path = parent_target.full_path
            if (
                b_path == t_path
                or (len(t_path) < len(b_path) and b_path[: len(t_path)] == t_path)
                or (len(b_path) < len(t_path) and t_path[: len(b_path)] == b_path)
            ):
                raise ConfigError(
                    "Block cannot inherit from itself, its ancestor, or its descendant"
                )

            self.resolve_deep(parent_target)
            assert parent_target.children is not None
            _merge_resolved_into_resolved(block, current_dict, parent_target.children)

        _merge_own_into_resolved(block, current_dict, block.own_children)

        block.children = current_dict
        block.self_resolved = True
        self.resolving_self.remove(block.full_path)

    def resolve_deep(self, block: BlockNode) -> None:
        if block.deep_resolved:
            return
        if block.full_path in self.resolving_deep:
            raise ConfigError("Circular block inheritance detected")
        self.resolving_deep.add(block.full_path)

        self.resolve_self(block)
        assert block.children is not None
        for child in block.children.values():
            if isinstance(child, BlockNode):
                self.resolve_deep(child)

        block.deep_resolved = True
        self.resolving_deep.remove(block.full_path)

    def lookup_parent_block(
        self, origin_scope: BlockNode, path: list[str]
    ) -> BlockNode:
        head = path[0]
        tail = path[1:]

        curr: BlockNode | None = origin_scope
        found_block: BlockNode | None = None
        while curr is not None:
            self.resolve_self(curr)
            assert curr.children is not None
            if head in curr.children:
                found_block = curr
                break
            curr = curr.parent

        if found_block is None:
            raise ConfigError(f"Undefined parent block: {'.'.join(path)}")

        assert found_block.children is not None
        node = found_block.children[head]
        if not isinstance(node, BlockNode):
            raise ConfigError(f"Parent path '{head}' is not a block")

        for part in tail:
            self.resolve_self(node)
            assert node.children is not None
            if part not in node.children:
                raise ConfigError(f"Undefined parent block: {'.'.join(path)}")
            node = node.children[part]
            if not isinstance(node, BlockNode):
                raise ConfigError(f"Parent path '{'.'.join(path)}' is not a block")

        return node


class _Evaluator:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.cache: dict[tuple[tuple[str, ...], str], Any] = {}
        self.evaluating: set[tuple[tuple[str, ...], str]] = set()

    def evaluate_block(self, block: BlockNode) -> dict[str, Any]:
        assert block.children is not None
        result: dict[str, Any] = {}
        for key, child in block.children.items():
            if isinstance(child, BlockNode):
                result[key] = self.evaluate_block(child)
            else:
                result[key] = self.eval_key(block, key)
        return result

    def eval_key(self, block: BlockNode, key: str) -> Any:
        node_id = (block.full_path, key)
        if node_id in self.cache:
            val = self.cache[node_id]
            return list(val) if isinstance(val, list) else val
        if node_id in self.evaluating:
            raise ConfigError(
                f"Circular reference detected at '{'.'.join(block.full_path + (key,))}'"
            )

        self.evaluating.add(node_id)
        assert block.children is not None
        expr = block.children[key]
        assert isinstance(expr, ExprNode)
        val = self.eval_expr(expr, block)
        self.evaluating.remove(node_id)
        self.cache[node_id] = val
        return list(val) if isinstance(val, list) else val

    def eval_expr(self, expr: ExprNode, scope: BlockNode) -> Any:
        acc = self.eval_term(expr.terms[0], scope)
        for term in expr.terms[1:]:
            right = self.eval_term(term, scope)
            acc = self._add_values(acc, right)
        return acc

    def eval_term(self, term: TermNode, scope: BlockNode) -> Any:
        if isinstance(term, LiteralNode):
            return term.value
        if isinstance(term, VarRefNode):
            return self.eval_var_ref(term, scope)
        if isinstance(term, EnvRefNode):
            return self.eval_env_ref(term)
        if isinstance(term, StringNode):
            out: list[str] = []
            for part in term.parts:
                if isinstance(part, str):
                    out.append(part)
                elif isinstance(part, VarRefNode):
                    val = self.eval_var_ref(part, scope)
                    out.append(self._format_interpolated(val))
                elif isinstance(part, EnvRefNode):
                    out.append(self.eval_env_ref(part))
            return "".join(out)
        if isinstance(term, ListNode):
            return [self.eval_expr(elem, scope) for elem in term.elements]
        raise ConfigError("Unknown term node")

    def eval_var_ref(self, ref: VarRefNode, scope: BlockNode) -> Any:
        head = ref.path[0]
        tail = ref.path[1:]

        curr: BlockNode | None = scope
        found_block: BlockNode | None = None
        while curr is not None:
            assert curr.children is not None
            if head in curr.children:
                found_block = curr
                break
            curr = curr.parent

        if found_block is None:
            raise ConfigError(f"Undefined variable reference: {'.'.join(ref.path)}")

        assert found_block.children is not None
        if not tail:
            target = found_block.children[head]
            if isinstance(target, BlockNode):
                raise ConfigError(f"Cannot reference block '{head}' as a value")
            return self.eval_key(found_block, head)

        node = found_block.children[head]
        if not isinstance(node, BlockNode):
            raise ConfigError(
                f"Cannot traverse non-block '{head}' in reference '{'.'.join(ref.path)}'"
            )

        for part in tail[:-1]:
            assert node.children is not None
            if part not in node.children:
                raise ConfigError(f"Undefined variable reference: {'.'.join(ref.path)}")
            node = node.children[part]
            if not isinstance(node, BlockNode):
                raise ConfigError(
                    f"Cannot traverse non-block '{part}' in reference '{'.'.join(ref.path)}'"
                )

        last_key = tail[-1]
        assert node.children is not None
        if last_key not in node.children:
            raise ConfigError(f"Undefined variable reference: {'.'.join(ref.path)}")
        target = node.children[last_key]
        if isinstance(target, BlockNode):
            raise ConfigError(
                f"Cannot reference block '{'.'.join(ref.path)}' as a value"
            )

        return self.eval_key(node, last_key)

    def eval_env_ref(self, ref: EnvRefNode) -> str:
        if ref.default is None:
            if ref.var_name not in self.env:
                raise ConfigError(f"Undefined environment variable: {ref.var_name}")
            return self.env[ref.var_name]
        val = self.env.get(ref.var_name, "")
        if val != "":
            return val
        return ref.default

    @staticmethod
    def _format_interpolated(val: Any) -> str:
        if isinstance(val, str):
            return val
        if isinstance(val, bool):
            return "true" if val else "false"
        if val is None:
            return "null"
        if isinstance(val, (int, float)):
            return str(val)
        raise ConfigError(
            f"Cannot interpolate value of type {type(val).__name__} into string"
        )

    @staticmethod
    def _add_values(left: Any, right: Any) -> Any:
        if (
            isinstance(left, (int, float))
            and not isinstance(left, bool)
            and isinstance(right, (int, float))
            and not isinstance(right, bool)
        ):
            return left + right
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        if isinstance(left, list) and isinstance(right, list):
            return left + right
        raise ConfigError(
            f"Unsupported operand types for +: {type(left).__name__} and {type(right).__name__}"
        )


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    env_dict: dict[str, str] = {} if env is None else env
    tokens = _tokenize(text)
    parser = _Parser(tokens)
    root = parser.parse_root()

    resolver = _InheritanceResolver()
    resolver.resolve_deep(root)

    evaluator = _Evaluator(env_dict)
    return evaluator.evaluate_block(root)
=== END ===

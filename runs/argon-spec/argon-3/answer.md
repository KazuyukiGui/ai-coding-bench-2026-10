=== FILE: config_parser.py ===
import re
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


# --- Regular Expressions ---

_UNSIGNED_INT_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
_UNSIGNED_FLOAT_RE = re.compile(
    r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+(?:[eE][+-]?[0-9]+)?|[eE][+-]?[0-9]+)$"
)
_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")
_ENV_VAR_RE = re.compile(r"^[A-Za-z0-9_]+$")


# --- AST Nodes ---

class ExprNode:
    pass


@dataclass(frozen=True)
class LiteralNode(ExprNode):
    value: int | float | bool | None


@dataclass(frozen=True)
class ListNode(ExprNode):
    elements: list[ExprNode]


@dataclass(frozen=True)
class BinOpAddNode(ExprNode):
    left: ExprNode
    right: ExprNode


@dataclass(frozen=True)
class RefNode(ExprNode):
    path: list[str]


@dataclass(frozen=True)
class EnvRefNode(ExprNode):
    var_name: str
    default: str | None


@dataclass(frozen=True)
class StringNode(ExprNode):
    parts: list[str | RefNode | EnvRefNode]


class Stmt:
    pass


@dataclass
class AssignStmt(Stmt):
    path: list[str]
    expr: ExprNode


@dataclass
class BlockStmt(Stmt):
    path: list[str]
    inherit_path: list[str] | None
    body: list[Stmt]


# --- Lexer ---

class TokenType(Enum):
    IDENT = auto()
    NUMBER = auto()
    STRING = auto()
    REF = auto()
    DOT = auto()
    EQUALS = auto()
    COLON = auto()
    SEMI = auto()
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


def _parse_interpolation_content(content: str) -> RefNode | EnvRefNode:
    if not content:
        raise ConfigError("Empty reference '${}'")
    if content.startswith("env:"):
        rest = content[4:]
        if ":-" in rest:
            var_name, default = rest.split(":-", 1)
            if not _ENV_VAR_RE.match(var_name):
                raise ConfigError(f"Invalid environment variable name: {var_name!r}")
            if "${" in default:
                raise ConfigError("Nested interpolation in env default is not allowed")
            return EnvRefNode(var_name=var_name, default=default)
        else:
            var_name = rest
            if not _ENV_VAR_RE.match(var_name):
                raise ConfigError(f"Invalid environment variable name: {var_name!r}")
            return EnvRefNode(var_name=var_name, default=None)
    else:
        parts = content.split(".")
        if not parts or any(not _IDENT_RE.match(p) for p in parts):
            raise ConfigError(f"Invalid reference path: {content!r}")
        return RefNode(path=parts)


def _tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    n = len(text)
    i = 0

    single_char_tokens = {
        ".": TokenType.DOT,
        "=": TokenType.EQUALS,
        ":": TokenType.COLON,
        ";": TokenType.SEMI,
        ",": TokenType.COMMA,
        "+": TokenType.PLUS,
        "-": TokenType.MINUS,
        "{": TokenType.LBRACE,
        "}": TokenType.RBRACE,
        "[": TokenType.LBRACKET,
        "]": TokenType.RBRACKET,
    }

    while i < n:
        ch = text[i]

        # Whitespace
        if ch in (" ", "\t"):
            i += 1
            continue

        # Newlines
        if ch == "\n":
            tokens.append(Token(TokenType.NEWLINE, "\n", i, i + 1))
            i += 1
            continue
        if ch == "\r":
            if i + 1 < n and text[i + 1] == "\n":
                tokens.append(Token(TokenType.NEWLINE, "\r\n", i, i + 2))
                i += 2
                continue
            raise ConfigError("Standalone '\\r' is not allowed")

        # Line comment with '#'
        if ch == "#":
            i += 1
            while i < n and text[i] not in ("\n", "\r"):
                i += 1
            continue

        # Comments starting with '/'
        if ch == "/":
            if i + 1 < n and text[i + 1] == "/":
                i += 2
                while i < n and text[i] not in ("\n", "\r"):
                    i += 1
                continue
            elif i + 1 < n and text[i + 1] == "*":
                comment_start = i
                i += 2
                has_newline = False
                closed = False
                while i < n:
                    if text[i] == "*" and i + 1 < n and text[i + 1] == "/":
                        i += 2
                        closed = True
                        break
                    if text[i] == "\n":
                        has_newline = True
                    elif text[i] == "\r":
                        if i + 1 < n and text[i + 1] == "\n":
                            has_newline = True
                            i += 1
                        else:
                            raise ConfigError("Standalone '\\r' is not allowed")
                    i += 1
                if not closed:
                    raise ConfigError("Unclosed block comment '/*'")
                if has_newline:
                    tokens.append(Token(TokenType.NEWLINE, "\n", comment_start, i))
                continue
            else:
                raise ConfigError(f"Unexpected character '/' at position {i}")

        # Single-character tokens
        if ch in single_char_tokens:
            tokens.append(Token(single_char_tokens[ch], ch, i, i + 1))
            i += 1
            continue

        # String literal
        if ch == '"':
            start = i
            i += 1
            parts: list[str | RefNode | EnvRefNode] = []
            buf: list[str] = []
            closed = False
            while i < n:
                c = text[i]
                if c == '"':
                    if buf:
                        parts.append("".join(buf))
                    i += 1
                    closed = True
                    break
                if c in ("\n", "\r"):
                    raise ConfigError("Raw newline inside string literal is not allowed")
                if c == "\\":
                    i += 1
                    if i >= n:
                        raise ConfigError("Unterminated escape sequence in string literal")
                    esc = text[i]
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
                        raise ConfigError(f"Invalid escape sequence '\\{esc}' in string literal")
                    i += 1
                elif c == "$" and i + 1 < n and text[i + 1] == "{":
                    if buf:
                        parts.append("".join(buf))
                        buf = []
                    i += 2
                    ref_start = i
                    while i < n and text[i] != "}":
                        if text[i] in ("\n", "\r", '"'):
                            raise ConfigError("Unterminated interpolation in string literal")
                        i += 1
                    if i >= n:
                        raise ConfigError("Unterminated interpolation in string literal")
                    ref_content = text[ref_start:i]
                    parts.append(_parse_interpolation_content(ref_content))
                    i += 1
                else:
                    buf.append(c)
                    i += 1
            if not closed:
                raise ConfigError("Unterminated string literal")
            tokens.append(Token(TokenType.STRING, StringNode(parts), start, i))
            continue

        # Standalone reference ${...}
        if ch == "$":
            if i + 1 >= n or text[i + 1] != "{":
                raise ConfigError(f"Unexpected '$' at position {i}")
            start = i
            i += 2
            ref_start = i
            while i < n and text[i] != "}":
                if text[i] in ("\n", "\r"):
                    raise ConfigError("Unterminated reference '${...}'")
                i += 1
            if i >= n:
                raise ConfigError("Unterminated reference '${...}'")
            ref_content = text[ref_start:i]
            ref_node = _parse_interpolation_content(ref_content)
            i += 1
            tokens.append(Token(TokenType.REF, ref_node, start, i))
            continue

        # Numbers
        if ch.isdigit():
            start = i
            while i < n:
                c = text[i]
                if c.isalnum() or c in ("_", "."):
                    i += 1
                elif c in ("+", "-") and text[i - 1] in ("e", "E"):
                    i += 1
                else:
                    break
            raw = text[start:i]
            if _UNSIGNED_INT_RE.match(raw):
                val: int | float = int(raw)
            elif _UNSIGNED_FLOAT_RE.match(raw):
                val = float(raw)
            else:
                raise ConfigError(f"Invalid number literal: {raw!r}")
            tokens.append(Token(TokenType.NUMBER, val, start, i))
            continue

        # Identifiers
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < n and (text[i].isalnum() or text[i] in ("_", "-")):
                i += 1
            ident = text[start:i]
            tokens.append(Token(TokenType.IDENT, ident, start, i))
            continue

        raise ConfigError(f"Unexpected character {ch!r} at position {i}")

    tokens.append(Token(TokenType.EOF, None, n, n))
    return tokens


# --- Parser ---

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

    def skip_newlines(self) -> None:
        while self.current().type == TokenType.NEWLINE:
            self.advance()

    def skip_separators(self) -> None:
        while self.current().type in (TokenType.NEWLINE, TokenType.SEMI):
            self.advance()

    def parse(self) -> list[Stmt]:
        return self.parse_statement_list(stop_at_rbrace=False)

    def parse_statement_list(self, stop_at_rbrace: bool) -> list[Stmt]:
        stmts: list[Stmt] = []
        while True:
            self.skip_separators()
            tok = self.current()
            if tok.type == TokenType.EOF:
                if stop_at_rbrace:
                    raise ConfigError("Unclosed block '{'")
                return stmts
            if tok.type == TokenType.RBRACE:
                if not stop_at_rbrace:
                    raise ConfigError("Unexpected '}'")
                self.advance()
                return stmts

            stmt = self.parse_statement()
            stmts.append(stmt)

            # After a statement (assignment or block), require separator, EOF, or RBRACE
            next_tok = self.current()
            if next_tok.type in (TokenType.NEWLINE, TokenType.SEMI):
                self.advance()
            elif next_tok.type == TokenType.EOF:
                if stop_at_rbrace:
                    raise ConfigError("Unclosed block '{'")
            elif next_tok.type == TokenType.RBRACE and stop_at_rbrace:
                pass
            else:
                raise ConfigError(
                    f"Expected newline or ';' after statement, got {next_tok.type.name}"
                )

    def parse_path(self) -> list[str]:
        first = self.current()
        if first.type != TokenType.IDENT:
            raise ConfigError(f"Expected identifier in path, got {first.type.name}")
        self.advance()
        path = [first.value]
        prev_end = first.end

        while self.current().type == TokenType.DOT:
            dot_tok = self.current()
            if dot_tok.start != prev_end:
                raise ConfigError("Whitespace is not allowed before '.' in path")
            self.advance()
            ident_tok = self.current()
            if ident_tok.type != TokenType.IDENT or ident_tok.start != dot_tok.end:
                raise ConfigError("Expected adjacent identifier after '.' in path")
            self.advance()
            path.append(ident_tok.value)
            prev_end = ident_tok.end

        return path

    def parse_statement(self) -> Stmt:
        path = self.parse_path()
        tok = self.current()

        if tok.type == TokenType.EQUALS:
            self.advance()
            expr = self.parse_expr()
            return AssignStmt(path=path, expr=expr)

        inherit_path: list[str] | None = None
        if tok.type == TokenType.COLON:
            self.advance()
            inherit_path = self.parse_path()

        self.skip_newlines()
        if self.current().type != TokenType.LBRACE:
            raise ConfigError(
                f"Expected '=' or '{{' after path, got {self.current().type.name}"
            )
        self.advance()
        body = self.parse_statement_list(stop_at_rbrace=True)
        return BlockStmt(path=path, inherit_path=inherit_path, body=body)

    def parse_expr(self) -> ExprNode:
        left = self.parse_term()
        while self.current().type == TokenType.PLUS:
            self.advance()
            self.skip_newlines()
            right = self.parse_term()
            left = BinOpAddNode(left=left, right=right)
        return left

    def parse_term(self) -> ExprNode:
        tok = self.current()

        if tok.type == TokenType.STRING:
            self.advance()
            return tok.value

        if tok.type == TokenType.REF:
            self.advance()
            return tok.value

        if tok.type == TokenType.NUMBER:
            self.advance()
            return LiteralNode(tok.value)

        if tok.type in (TokenType.PLUS, TokenType.MINUS):
            sign_tok = self.advance()
            num_tok = self.current()
            if num_tok.type != TokenType.NUMBER or num_tok.start != sign_tok.end:
                raise ConfigError("Expected number immediately after sign")
            self.advance()
            val = num_tok.value if sign_tok.type == TokenType.PLUS else -num_tok.value
            if isinstance(val, int) and val == 0:
                val = 0
            return LiteralNode(val)

        if tok.type == TokenType.IDENT:
            if tok.value == "true":
                self.advance()
                return LiteralNode(True)
            if tok.value == "false":
                self.advance()
                return LiteralNode(False)
            if tok.value == "null":
                self.advance()
                return LiteralNode(None)
            raise ConfigError(f"Unexpected identifier {tok.value!r} in expression")

        if tok.type == TokenType.LBRACKET:
            self.advance()
            self.skip_newlines()
            elements: list[ExprNode] = []
            if self.current().type == TokenType.RBRACKET:
                self.advance()
                return ListNode(elements)

            while True:
                elem = self.parse_expr()
                elements.append(elem)
                self.skip_newlines()
                sep = self.current()
                if sep.type == TokenType.COMMA:
                    self.advance()
                    self.skip_newlines()
                    if self.current().type == TokenType.RBRACKET:
                        self.advance()
                        break
                elif sep.type == TokenType.RBRACKET:
                    self.advance()
                    break
                else:
                    raise ConfigError(
                        f"Expected ',' or ']' in list literal, got {sep.type.name}"
                    )
            return ListNode(elements)

        raise ConfigError(f"Unexpected token {tok.type.name} in expression")


# --- Block Tree Construction & Inheritance Resolution ---

class _EvalState(Enum):
    UNVISITED = auto()
    EVALUATING = auto()
    EVALUATED = auto()


@dataclass
class BlockNode:
    parent: "BlockNode | None" = None
    name: str | None = None
    children: dict[str, "BlockNode | ExprNode"] = field(default_factory=dict)
    inherit_path: list[str] | None = None
    deferred_bases: list["BlockNode"] = field(default_factory=list)
    step1_done: bool = False
    full_done: bool = False
    eval_states: dict[str, _EvalState] = field(default_factory=dict)
    eval_cache: dict[str, Any] = field(default_factory=dict)


def _populate_block(block: BlockNode, stmts: list[Stmt]) -> None:
    for stmt in stmts:
        if isinstance(stmt, AssignStmt):
            curr = block
            for seg in stmt.path[:-1]:
                existing = curr.children.get(seg)
                if existing is None:
                    nxt = BlockNode(parent=curr, name=seg)
                    curr.children[seg] = nxt
                    curr = nxt
                elif isinstance(existing, BlockNode):
                    curr = existing
                else:
                    raise ConfigError(
                        f"Type conflict: cannot traverse through non-block key {seg!r}"
                    )
            last_seg = stmt.path[-1]
            existing_last = curr.children.get(last_seg)
            if isinstance(existing_last, BlockNode):
                raise ConfigError(
                    f"Type conflict: cannot overwrite block {last_seg!r} with value"
                )
            curr.children[last_seg] = stmt.expr

        elif isinstance(stmt, BlockStmt):
            curr = block
            for seg in stmt.path:
                existing = curr.children.get(seg)
                if existing is None:
                    nxt = BlockNode(parent=curr, name=seg)
                    curr.children[seg] = nxt
                    curr = nxt
                elif isinstance(existing, BlockNode):
                    curr = existing
                else:
                    raise ConfigError(
                        f"Type conflict: cannot define block on non-block key {seg!r}"
                    )
            if stmt.inherit_path is not None:
                if curr.inherit_path is not None:
                    raise ConfigError(
                        f"Multiple inheritance definitions for block {'.'.join(stmt.path)!r}"
                    )
                curr.inherit_path = stmt.inherit_path
            _populate_block(curr, stmt.body)


def _is_ancestor(ancestor: BlockNode, node: BlockNode) -> bool:
    curr = node.parent
    while curr is not None:
        if curr is ancestor:
            return True
        curr = curr.parent
    return False


def _deep_copy_block(src: BlockNode, new_parent: BlockNode) -> BlockNode:
    copied = BlockNode(parent=new_parent, name=src.name)
    copied.step1_done = True
    copied.full_done = True
    for k, v in src.children.items():
        if isinstance(v, BlockNode):
            copied.children[k] = _deep_copy_block(v, copied)
        else:
            copied.children[k] = v
    return copied


def _merge_base_into_target(base: BlockNode, target: BlockNode) -> None:
    """Merges resolved `base` block as low-priority base underneath `target`."""
    new_children: dict[str, BlockNode | ExprNode] = {}
    for k, base_val in base.children.items():
        if k not in target.children:
            if isinstance(base_val, BlockNode):
                new_children[k] = _deep_copy_block(base_val, target)
            else:
                new_children[k] = base_val
        else:
            target_val = target.children[k]
            if isinstance(base_val, BlockNode) and isinstance(target_val, BlockNode):
                if target_val.inherit_path is not None and not target_val.step1_done:
                    target_val.deferred_bases.append(base_val)
                else:
                    _merge_base_into_target(base_val, target_val)
                new_children[k] = target_val
            elif isinstance(base_val, ExprNode) and isinstance(target_val, ExprNode):
                new_children[k] = target_val
            else:
                raise ConfigError(
                    f"Type conflict during inheritance merge on key {k!r}"
                )

    for k, target_val in target.children.items():
        if k not in new_children:
            new_children[k] = target_val

    target.children = new_children


def _resolve_all_inheritance(root: BlockNode) -> None:
    resolving_step1: set[int] = set()
    resolving_full: set[int] = set()

    def ensure_ancestors_step1(node: BlockNode) -> None:
        ancestors: list[BlockNode] = []
        curr = node.parent
        while curr is not None:
            ancestors.append(curr)
            curr = curr.parent
        for anc in reversed(ancestors):
            resolve_step1(anc)

    def lookup_parent_block(start_scope: BlockNode | None, path: list[str]) -> BlockNode:
        head = path[0]
        tail = path[1:]
        scope = start_scope
        found_scope: BlockNode | None = None

        while scope is not None:
            resolve_step1(scope)
            if head in scope.children:
                found_scope = scope
                break
            scope = scope.parent

        if found_scope is None:
            raise ConfigError(f"Undefined parent block reference: {'.'.join(path)!r}")

        curr = found_scope.children[head]
        if not isinstance(curr, BlockNode):
            raise ConfigError(
                f"Parent reference {'.'.join(path)!r} points to non-block"
            )

        for seg in tail:
            resolve_step1(curr)
            if seg not in curr.children:
                raise ConfigError(
                    f"Undefined parent block reference: {'.'.join(path)!r}"
                )
            nxt = curr.children[seg]
            if not isinstance(nxt, BlockNode):
                raise ConfigError(
                    f"Parent reference {'.'.join(path)!r} points to non-block"
                )
            curr = nxt

        return curr

    def resolve_step1(node: BlockNode) -> None:
        if node.step1_done:
            return
        node_id = id(node)
        if node_id in resolving_step1:
            raise ConfigError("Circular block inheritance detected")

        ensure_ancestors_step1(node)
        resolving_step1.add(node_id)

        if node.inherit_path is not None:
            parent_block = lookup_parent_block(node.parent, node.inherit_path)
            if (
                parent_block is node
                or _is_ancestor(parent_block, node)
                or _is_ancestor(node, parent_block)
            ):
                raise ConfigError(
                    "Block cannot inherit from itself, its ancestor, or its descendant"
                )
            resolve_full(parent_block)
            _merge_base_into_target(parent_block, node)

        if node.deferred_bases:
            for base_block in node.deferred_bases:
                _merge_base_into_target(base_block, node)
            node.deferred_bases.clear()

        resolving_step1.remove(node_id)
        node.step1_done = True

    def resolve_full(node: BlockNode) -> None:
        if node.full_done:
            return
        node_id = id(node)
        if node_id in resolving_full:
            raise ConfigError("Circular block inheritance detected")

        resolving_full.add(node_id)
        resolve_step1(node)

        for child in list(node.children.values()):
            if isinstance(child, BlockNode):
                resolve_full(child)

        resolving_full.remove(node_id)
        node.full_done = True

    resolve_full(root)


# --- Evaluator ---

class _Evaluator:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env

    def evaluate_block(self, block: BlockNode) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, child in block.children.items():
            if isinstance(child, BlockNode):
                result[key] = self.evaluate_block(child)
            else:
                result[key] = self.evaluate_key(block, key)
        return result

    def evaluate_key(self, block: BlockNode, key: str) -> Any:
        state = block.eval_states.get(key, _EvalState.UNVISITED)
        if state == _EvalState.EVALUATED:
            return block.eval_cache[key]
        if state == _EvalState.EVALUATING:
            raise ConfigError(f"Circular variable reference detected for key {key!r}")

        block.eval_states[key] = _EvalState.EVALUATING
        target = block.children[key]
        if not isinstance(target, ExprNode):
            raise ConfigError(f"Cannot evaluate block {key!r} as value")

        val = self.eval_expr(target, block)
        block.eval_cache[key] = val
        block.eval_states[key] = _EvalState.EVALUATED
        return val

    def resolve_ref(self, scope_block: BlockNode, path: list[str]) -> Any:
        head = path[0]
        tail = path[1:]

        curr_scope: BlockNode | None = scope_block
        found_scope: BlockNode | None = None
        while curr_scope is not None:
            if head in curr_scope.children:
                found_scope = curr_scope
                break
            curr_scope = curr_scope.parent

        if found_scope is None:
            raise ConfigError(f"Undefined variable reference: {'.'.join(path)!r}")

        if not tail:
            target = found_scope.children[head]
            if isinstance(target, BlockNode):
                raise ConfigError(
                    f"Cannot reference block {'.'.join(path)!r} as a value"
                )
            return self.evaluate_key(found_scope, head)

        curr_node = found_scope.children[head]
        for seg in tail[:-1]:
            if not isinstance(curr_node, BlockNode):
                raise ConfigError(
                    f"Cannot traverse non-block in reference {'.'.join(path)!r}"
                )
            if seg not in curr_node.children:
                raise ConfigError(f"Undefined variable reference: {'.'.join(path)!r}")
            curr_node = curr_node.children[seg]

        if not isinstance(curr_node, BlockNode):
            raise ConfigError(
                f"Cannot traverse non-block in reference {'.'.join(path)!r}"
            )
        last_seg = tail[-1]
        if last_seg not in curr_node.children:
            raise ConfigError(f"Undefined variable reference: {'.'.join(path)!r}")

        final_target = curr_node.children[last_seg]
        if isinstance(final_target, BlockNode):
            raise ConfigError(
                f"Cannot reference block {'.'.join(path)!r} as a value"
            )
        return self.evaluate_key(curr_node, last_seg)

    def resolve_env(self, node: EnvRefNode) -> str:
        if node.default is None:
            if node.var_name not in self.env:
                raise ConfigError(f"Environment variable {node.var_name!r} is not set")
            return self.env[node.var_name]
        else:
            val = self.env.get(node.var_name, "")
            return val if val != "" else node.default

    def eval_expr(self, expr: ExprNode, scope: BlockNode) -> Any:
        if isinstance(expr, LiteralNode):
            return expr.value

        if isinstance(expr, RefNode):
            val = self.resolve_ref(scope, expr.path)
            if isinstance(val, list):
                return list(val)
            return val

        if isinstance(expr, EnvRefNode):
            return self.resolve_env(expr)

        if isinstance(expr, StringNode):
            out: list[str] = []
            for part in expr.parts:
                if isinstance(part, str):
                    out.append(part)
                elif isinstance(part, EnvRefNode):
                    out.append(self.resolve_env(part))
                elif isinstance(part, RefNode):
                    val = self.resolve_ref(scope, part.path)
                    if val is None:
                        out.append("null")
                    elif isinstance(val, bool):
                        out.append("true" if val else "false")
                    elif isinstance(val, (int, float)):
                        out.append(str(val))
                    elif isinstance(val, str):
                        out.append(val)
                    else:
                        raise ConfigError(
                            f"Cannot interpolate value of type {type(val).__name__} into string"
                        )
            return "".join(out)

        if isinstance(expr, ListNode):
            return [self.eval_expr(elem, scope) for elem in expr.elements]

        if isinstance(expr, BinOpAddNode):
            left_val = self.eval_expr(expr.left, scope)
            right_val = self.eval_expr(expr.right, scope)

            if (
                isinstance(left_val, (int, float))
                and not isinstance(left_val, bool)
                and isinstance(right_val, (int, float))
                and not isinstance(right_val, bool)
            ):
                return left_val + right_val

            if isinstance(left_val, str) and isinstance(right_val, str):
                return left_val + right_val

            if isinstance(left_val, list) and isinstance(right_val, list):
                return left_val + right_val

            raise ConfigError(
                f"Unsupported operand types for +: {type(left_val).__name__} and {type(right_val).__name__}"
            )

        raise ConfigError(f"Unknown expression node: {expr!r}")


# --- Public API ---

def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    if not isinstance(text, str):
        raise ConfigError("Input text must be a string")
    env_dict: dict[str, str] = {} if env is None else dict(env)

    tokens = _tokenize(text)
    parser = _Parser(tokens)
    stmts = parser.parse()

    root = BlockNode()
    _populate_block(root, stmts)
    _resolve_all_inheritance(root)

    evaluator = _Evaluator(env_dict)
    return evaluator.evaluate_block(root)
=== END ===

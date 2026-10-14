from typing import Any
from dataclasses import dataclass, field
import re


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


# --- Lexer ---

@dataclass
class Token:
    type: str
    value: Any
    line: int
    col: int


IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_-]*')
NUMBER_RE = re.compile(
    r'^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(text)
    line = 1
    col = 1

    while i < n:
        ch = text[i]

        # Whitespace (spaces and tabs)
        if ch in (' ', '\t'):
            i += 1
            col += 1
            continue

        # Newlines
        if ch == '\r':
            if i + 1 < n and text[i + 1] == '\n':
                i += 2
            else:
                i += 1
            tokens.append(Token('NEWLINE', '\n', line, col))
            line += 1
            col = 1
            continue
        if ch == '\n':
            i += 1
            tokens.append(Token('NEWLINE', '\n', line, col))
            line += 1
            col = 1
            continue

        # Comments
        if ch == '#' or (ch == '/' and i + 1 < n and text[i + 1] == '/'):
            while i < n and text[i] not in ('\n', '\r'):
                i += 1
                col += 1
            continue

        if ch == '/' and i + 1 < n and text[i + 1] == '*':
            start_line, start_col = line, col
            i += 2
            col += 2
            closed = False
            while i < n:
                if text[i] == '*' and i + 1 < n and text[i + 1] == '/':
                    i += 2
                    col += 2
                    closed = True
                    break
                if text[i] == '\r':
                    if i + 1 < n and text[i + 1] == '\n':
                        i += 2
                    else:
                        i += 1
                    line += 1
                    col = 1
                elif text[i] == '\n':
                    i += 1
                    line += 1
                    col = 1
                else:
                    i += 1
                    col += 1
            if not closed:
                raise ConfigError(f"Unclosed block comment at {start_line}:{start_col}")
            continue

        # Single-char punctuation
        if ch in '{}[],=;:':
            tokens.append(Token(ch, ch, line, col))
            i += 1
            col += 1
            continue

        # Dot
        if ch == '.':
            tokens.append(Token('.', '.', line, col))
            i += 1
            col += 1
            continue

        # String literal
        if ch == '"':
            start_line, start_col = line, col
            i += 1
            col += 1
            parts: list[tuple[str, str]] = []  # ('LIT', str) or ('INTERP', str)
            buf: list[str] = []
            closed = False
            while i < n:
                c = text[i]
                if c in ('\n', '\r'):
                    raise ConfigError(f"Unterminated string literal at {start_line}:{start_col}")
                if c == '"':
                    i += 1
                    col += 1
                    closed = True
                    break
                if c == '\\':
                    if i + 1 >= n:
                        raise ConfigError(f"Unterminated escape in string at {line}:{col}")
                    esc = text[i + 1]
                    if esc == '"':
                        buf.append('"')
                    elif esc == '\\':
                        buf.append('\\')
                    elif esc == 'n':
                        buf.append('\n')
                    elif esc == 't':
                        buf.append('\t')
                    elif esc == 'r':
                        buf.append('\r')
                    elif esc == '$':
                        buf.append('$')
                    else:
                        raise ConfigError(f"Invalid escape sequence \\{esc} at {line}:{col}")
                    i += 2
                    col += 2
                    continue
                if c == '$' and i + 1 < n and text[i + 1] == '{':
                    if buf:
                        parts.append(('LIT', ''.join(buf)))
                        buf = []
                    i += 2
                    col += 2
                    interp_buf: list[str] = []
                    found_close = False
                    while i < n:
                        if text[i] in ('\n', '\r'):
                            raise ConfigError(f"Unterminated interpolation at {line}:{col}")
                        if text[i] == '}':
                            i += 1
                            col += 1
                            found_close = True
                            break
                        interp_buf.append(text[i])
                        i += 1
                        col += 1
                    if not found_close:
                        raise ConfigError(f"Unterminated interpolation at {start_line}:{start_col}")
                    interp_content = ''.join(interp_buf)
                    if not interp_content:
                        raise ConfigError(f"Empty interpolation at {line}:{col}")
                    parts.append(('INTERP', interp_content))
                    continue
                buf.append(c)
                i += 1
                col += 1
            if not closed:
                raise ConfigError(f"Unterminated string literal at {start_line}:{start_col}")
            if buf or not parts:
                parts.append(('LIT', ''.join(buf)))
            tokens.append(Token('STRING', parts, start_line, start_col))
            continue

        # Reference ${...}
        if ch == '$' and i + 1 < n and text[i + 1] == '{':
            start_line, start_col = line, col
            i += 2
            col += 2
            ref_buf: list[str] = []
            found_close = False
            while i < n:
                if text[i] in ('\n', '\r'):
                    raise ConfigError(f"Newline in reference at {start_line}:{start_col}")
                if text[i] == '}':
                    i += 1
                    col += 1
                    found_close = True
                    break
                ref_buf.append(text[i])
                i += 1
                col += 1
            if not found_close:
                raise ConfigError(f"Unterminated reference at {start_line}:{start_col}")
            ref_content = ''.join(ref_buf)
            if not ref_content:
                raise ConfigError(f"Empty reference at {start_line}:{start_col}")
            tokens.append(Token('REF', ref_content, start_line, start_col))
            continue

        # Numbers or '+' operator
        if ch in '+-' or ch.isdigit():
            # Determine if '+' is binary operator or unary sign on number
            # Wait: in our grammar, '+' can be binary operator between terms, OR leading sign of a number term.
            # If previous meaningful token (ignoring NEWLINE) can end a term, '+' is binary operator!
            prev_tok = None
            for t in reversed(tokens):
                if t.type != 'NEWLINE':
                    prev_tok = t
                    break
            is_after_term = prev_tok is not None and prev_tok.type in (
                'NUMBER', 'STRING', 'IDENT', 'REF', ']'
            )
            if ch == '+' and (is_after_term or not (i + 1 < n and text[i + 1].isdigit())):
                tokens.append(Token('+', '+', line, col))
                i += 1
                col += 1
                continue

            # Otherwise try matching a number literal
            sub = text[i:]
            # Check for invalid leading zeros like 01, -01, +01
            m_invalid_zero = re.match(r'^[+-]?0[0-9]+', sub)
            if m_invalid_zero:
                raise ConfigError(f"Invalid leading zero in number at {line}:{col}")
            m = NUMBER_RE.match(sub)
            if not m:
                raise ConfigError(f"Invalid number literal at {line}:{col}")
            num_str = m.group(0)
            after_idx = i + len(num_str)
            # Check trailing invalid characters like `123abc` or `1.2.3` or `5.`
            if after_idx < n and (text[after_idx].isalpha() or text[after_idx] in ('_', '.')):
                raise ConfigError(f"Invalid characters after number at {line}:{col}")
            if '.' in num_str or 'e' in num_str or 'E' in num_str:
                val: int | float = float(num_str)
            else:
                val = int(num_str)
            tokens.append(Token('NUMBER', val, line, col))
            i += len(num_str)
            col += len(num_str)
            continue

        # Identifiers / Keywords
        m_ident = IDENT_RE.match(text[i:])
        if m_ident:
            ident_str = m_ident.group(0)
            tokens.append(Token('IDENT', ident_str, line, col))
            i += len(ident_str)
            col += len(ident_str)
            continue

        raise ConfigError(f"Unexpected character {ch!r} at {line}:{col}")

    tokens.append(Token('EOF', None, line, col))
    return tokens


# --- AST Definitions ---

@dataclass
class ExprNode:
    terms: list['TermNode']


class TermNode:
    pass


@dataclass
class LiteralNode(TermNode):
    value: Any  # int, float, bool, None


@dataclass
class StringNode(TermNode):
    parts: list[tuple[str, Any]]  # ('LIT', str) or ('REF', RefSpec)


@dataclass
class ListNode(TermNode):
    elements: list[ExprNode]


@dataclass
class RefSpec:
    kind: str  # 'VAR' or 'ENV'
    path: list[str] = field(default_factory=list)
    env_var: str = ""
    has_default: bool = False
    default_val: str = ""


@dataclass
class RefNode(TermNode):
    spec: RefSpec


@dataclass
class BlockScope:
    parent_scope: 'BlockScope | None' = None
    inherit_paths: list[list[str]] = field(default_factory=list)
    # key -> BlockScope or ExprNode
    entries: dict[str, 'BlockScope | ExprNode'] = field(default_factory=dict)
    # Track whether a key was explicitly set as a value or block in THIS scope
    key_kinds: dict[str, str] = field(default_factory=dict)  # 'BLOCK' or 'EXPR'

    def clone_for_child(self, new_parent: 'BlockScope | None') -> 'BlockScope':
        new_scope = BlockScope(parent_scope=new_parent)
        new_scope.inherit_paths = [list(p) for p in self.inherit_paths]
        for k, v in self.entries.items():
            new_scope.key_kinds[k] = self.key_kinds[k]
            if isinstance(v, BlockScope):
                new_scope.entries[k] = v.clone_for_child(new_scope)
            else:
                new_scope.entries[k] = v
        return new_scope


def parse_ref_content(content: str) -> RefSpec:
    if content.startswith('env:'):
        rest = content[4:]
        if ':-' in rest:
            var_name, default_val = rest.split(':-', 1)
            has_default = True
        else:
            var_name = rest
            default_val = ""
            has_default = False
        if not re.match(r'^[A-Za-z0-9_]+$', var_name):
            raise ConfigError(f"Invalid environment variable name: {var_name!r}")
        if '${' in default_val:
            raise ConfigError("Nested interpolation in env default is not supported")
        return RefSpec(
            kind='ENV',
            env_var=var_name,
            has_default=has_default,
            default_val=default_val,
        )
    else:
        if not content or content.startswith('.') or content.endswith('.') or '..' in content:
            raise ConfigError(f"Invalid reference path: {content!r}")
        parts = content.split('.')
        for p in parts:
            if not IDENT_RE.match(p) or IDENT_RE.match(p).group(0) != p:
                raise ConfigError(f"Invalid identifier {p!r} in reference {content!r}")
        return RefSpec(kind='VAR', path=parts)


# --- Parser ---

class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def current(self) -> Token:
        return self.tokens[self.pos]

    def consume(self, expected_type: str | None = None) -> Token:
        tok = self.current()
        if expected_type is not None and tok.type != expected_type:
            raise ConfigError(
                f"Expected {expected_type}, got {tok.type} at {tok.line}:{tok.col}"
            )
        self.pos += 1
        return tok

    def skip_newlines(self) -> None:
        while self.current().type == 'NEWLINE':
            self.pos += 1

    def skip_separators(self) -> None:
        while self.current().type in ('NEWLINE', ';'):
            self.pos += 1

    def parse_root(self) -> BlockScope:
        root = BlockScope(parent_scope=None)
        self.skip_separators()
        while self.current().type != 'EOF':
            self.parse_statement(root)
            if self.current().type not in ('NEWLINE', ';', 'EOF'):
                tok = self.current()
                raise ConfigError(
                    f"Expected newline or ';' after statement, got {tok.type} at {tok.line}:{tok.col}"
                )
            self.skip_separators()
        return root

    def parse_path(self) -> list[str]:
        parts: list[str] = []
        tok = self.consume('IDENT')
        parts.append(tok.value)
        while self.current().type == '.':
            self.consume('.')
            if self.current().type != 'IDENT':
                t = self.current()
                raise ConfigError(f"Expected identifier after '.', got {t.type} at {t.line}:{t.col}")
            parts.append(self.consume('IDENT').value)
        return parts

    def ensure_subscope(self, scope: BlockScope, path: list[str]) -> BlockScope:
        curr = scope
        for part in path:
            if part in curr.entries:
                if curr.key_kinds[part] != 'BLOCK':
                    raise ConfigError(f"Type conflict: {part!r} is already defined as a value")
                sub = curr.entries[part]
                assert isinstance(sub, BlockScope)
                curr = sub
            else:
                sub = BlockScope(parent_scope=curr)
                curr.entries[part] = sub
                curr.key_kinds[part] = 'BLOCK'
                curr = sub
        return curr

    def parse_statement(self, scope: BlockScope) -> None:
        path = self.parse_path()
        tok = self.current()

        if tok.type == '=':
            self.consume('=')
            expr = self.parse_expr()
            target_scope = self.ensure_subscope(scope, path[:-1])
            last_key = path[-1]
            if last_key in target_scope.entries and target_scope.key_kinds[last_key] == 'BLOCK':
                raise ConfigError(f"Type conflict: cannot overwrite block {last_key!r} with a value")
            target_scope.entries[last_key] = expr
            target_scope.key_kinds[last_key] = 'EXPR'
            return

        # Otherwise it must be a block definition (with optional inheritance and optional newlines before '{')
        parent_path: list[str] | None = None
        if tok.type == ':':
            self.consume(':')
            parent_path = self.parse_path()

        self.skip_newlines()
        if self.current().type != '{':
            t = self.current()
            raise ConfigError(f"Expected '=' or '{{' after path, got {t.type} at {t.line}:{t.col}")
        self.consume('{')

        block_scope = self.ensure_subscope(scope, path)
        if parent_path is not None:
            if block_scope.inherit_paths:
                raise ConfigError(f"Multiple inheritance specifications for block {'.'.join(path)}")
            block_scope.inherit_paths.append(parent_path)

        self.skip_separators()
        while self.current().type != '}':
            if self.current().type == 'EOF':
                raise ConfigError("Unclosed '{' before end of file")
            self.parse_statement(block_scope)
            if self.current().type not in ('NEWLINE', ';', '}'):
                t = self.current()
                raise ConfigError(
                    f"Expected separator or '}}' after statement in block, got {t.type} at {t.line}:{t.col}"
                )
            self.skip_separators()
        self.consume('}')

    def parse_expr(self) -> ExprNode:
        terms = [self.parse_term()]
        # '+' cannot be preceded by a newline, only followed by optional newlines
        while self.current().type == '+':
            self.consume('+')
            self.skip_newlines()
            terms.append(self.parse_term())
        return ExprNode(terms=terms)

    def parse_term(self) -> TermNode:
        tok = self.current()
        if tok.type == 'NUMBER':
            self.consume('NUMBER')
            return LiteralNode(tok.value)
        if tok.type == 'IDENT':
            self.consume('IDENT')
            if tok.value == 'true':
                return LiteralNode(True)
            if tok.value == 'false':
                return LiteralNode(False)
            if tok.value == 'null':
                return LiteralNode(None)
            raise ConfigError(f"Unexpected identifier {tok.value!r} in expression at {tok.line}:{tok.col}")
        if tok.type == 'STRING':
            self.consume('STRING')
            parsed_parts: list[tuple[str, Any]] = []
            for kind, val in tok.value:
                if kind == 'LIT':
                    parsed_parts.append(('LIT', val))
                else:
                    parsed_parts.append(('REF', parse_ref_content(val)))
            return StringNode(parts=parsed_parts)
        if tok.type == 'REF':
            self.consume('REF')
            return RefNode(spec=parse_ref_content(tok.value))
        if tok.type == '[':
            return self.parse_list()

        raise ConfigError(f"Unexpected token {tok.type} in expression at {tok.line}:{tok.col}")

    def parse_list(self) -> ListNode:
        self.consume('[')
        self.skip_newlines()
        elements: list[ExprNode] = []
        while self.current().type != ']':
            if self.current().type == 'EOF':
                raise ConfigError("Unclosed '[' before end of file")
            elements.append(self.parse_expr())
            self.skip_newlines()
            if self.current().type == ',':
                self.consume(',')
                self.skip_newlines()
                if self.current().type == ',':
                    t = self.current()
                    raise ConfigError(f"Unexpected ',' in list at {t.line}:{t.col}")
            elif self.current().type == ']':
                break
            else:
                t = self.current()
                raise ConfigError(f"Expected ',' or ']' in list, got {t.type} at {t.line}:{t.col}")
        self.consume(']')
        return ListNode(elements=elements)


# --- Evaluator ---

class Evaluator:
    def __init__(self, root: BlockScope, env: dict[str, str]):
        self.root = root
        self.env = env
        self.resolving_inheritance: set[int] = set()
        self.resolved_inheritance: set[int] = set()
        # (id(scope), key) currently being evaluated
        self.evaluating_keys: set[tuple[int, str]] = set()
        self.evaluated_cache: dict[tuple[int, str], Any] = {}

    def resolve_all_inheritance(self, scope: BlockScope) -> None:
        self._resolve_scope_inheritance(scope)
        for k, v in list(scope.entries.items()):
            if isinstance(v, BlockScope):
                self.resolve_all_inheritance(v)

    def _is_ancestor_or_self(self, target: BlockScope, candidate: BlockScope) -> bool:
        curr: BlockScope | None = candidate
        while curr is not None:
            if curr is target:
                return True
            curr = curr.parent_scope
        return False

    def _resolve_scope_inheritance(self, scope: BlockScope) -> None:
        sid = id(scope)
        if sid in self.resolved_inheritance:
            return
        if sid in self.resolving_inheritance:
            raise ConfigError("Circular block inheritance detected")

        self.resolving_inheritance.add(sid)

        # Ensure ancestors have their inheritance resolved first so lexical lookup works accurately
        if scope.parent_scope is not None and id(scope.parent_scope) not in self.resolved_inheritance:
            # Only resolve parent if not currently in resolving_inheritance; if it is, that's fine
            # as long as parent finished merging its own parents before descending.
            pass

        if scope.inherit_paths:
            parent_path = scope.inherit_paths[0]
            if scope.parent_scope is None:
                raise ConfigError("Root cannot inherit")
            base_scope = self.lookup_block(scope.parent_scope, parent_path)
            if self._is_ancestor_or_self(scope, base_scope) or self._is_ancestor_or_self(base_scope, scope):
                raise ConfigError("Cannot inherit from self or ancestor/descendant block")
            self._resolve_scope_inheritance(base_scope)
            # Also recursively resolve any child blocks inside base_scope
            for v in list(base_scope.entries.values()):
                if isinstance(v, BlockScope):
                    self.resolve_all_inheritance(v)

            self._merge_from_parent(scope, base_scope)

        self.resolving_inheritance.remove(sid)
        self.resolved_inheritance.add(sid)

    def _merge_from_parent(self, child: BlockScope, parent: BlockScope) -> None:
        for k, pv in parent.entries.items():
            p_kind = parent.key_kinds[k]
            if k not in child.entries:
                child.key_kinds[k] = p_kind
                if isinstance(pv, BlockScope):
                    child.entries[k] = pv.clone_for_child(child)
                else:
                    child.entries[k] = pv
            else:
                c_kind = child.key_kinds[k]
                if p_kind != c_kind:
                    raise ConfigError(f"Type conflict in inheritance for key {k!r}")
                if p_kind == 'BLOCK':
                    c_sub = child.entries[k]
                    assert isinstance(c_sub, BlockScope) and isinstance(pv, BlockScope)
                    # Resolve child sub-block's own inheritance if any before merging parent sub-block
                    self._resolve_scope_inheritance(c_sub)
                    self._merge_from_parent(c_sub, pv)
                else:
                    # Child expression overrides parent expression
                    pass

    def lookup_block(self, start_scope: BlockScope, path: list[str]) -> BlockScope:
        head = path[0]
        curr_scope: BlockScope | None = start_scope
        found_scope: BlockScope | None = None

        while curr_scope is not None:
            # Make sure curr_scope's inheritance is resolved so all its keys are present
            if id(curr_scope) not in self.resolved_inheritance and id(curr_scope) not in self.resolving_inheritance:
                self._resolve_scope_inheritance(curr_scope)
            if head in curr_scope.entries:
                found_scope = curr_scope
                break
            curr_scope = curr_scope.parent_scope

        if found_scope is None:
            raise ConfigError(f"Undefined block reference: {'.'.join(path)}")

        node: BlockScope | ExprNode = found_scope.entries[head]
        for part in path[1:]:
            if not isinstance(node, BlockScope):
                raise ConfigError(f"Cannot traverse non-block in {'.'.join(path)}")
            if id(node) not in self.resolved_inheritance and id(node) not in self.resolving_inheritance:
                self._resolve_scope_inheritance(node)
            if part not in node.entries:
                raise ConfigError(f"Undefined key {part!r} in block reference {'.'.join(path)}")
            node = node.entries[part]

        if not isinstance(node, BlockScope):
            raise ConfigError(f"Reference {'.'.join(path)} does not point to a block")
        return node

    def lookup_value(self, start_scope: BlockScope, path: list[str]) -> Any:
        head = path[0]
        curr_scope: BlockScope | None = start_scope
        found_scope: BlockScope | None = None

        while curr_scope is not None:
            if head in curr_scope.entries:
                found_scope = curr_scope
                break
            curr_scope = curr_scope.parent_scope

        if found_scope is None:
            raise ConfigError(f"Undefined variable reference: {'.'.join(path)}")

        curr = found_scope
        for part in path[:-1]:
            entry = curr.entries.get(part)
            if not isinstance(entry, BlockScope):
                raise ConfigError(f"Cannot traverse non-block {part!r} in {'.'.join(path)}")
            curr = entry

        last_key = path[-1]
        if last_key not in curr.entries:
            raise ConfigError(f"Undefined variable reference: {'.'.join(path)}")

        target = curr.entries[last_key]
        if isinstance(target, BlockScope):
            raise ConfigError(f"Cannot reference block {'.'.join(path)} as a value")

        return self.eval_key(curr, last_key)

    def eval_key(self, scope: BlockScope, key: str) -> Any:
        cache_key = (id(scope), key)
        if cache_key in self.evaluated_cache:
            val = self.evaluated_cache[cache_key]
            return list(val) if isinstance(val, list) else val
        if cache_key in self.evaluating_keys:
            raise ConfigError(f"Circular variable reference involving {key!r}")

        self.evaluating_keys.add(cache_key)
        expr = scope.entries[key]
        assert isinstance(expr, ExprNode)
        val = self.eval_expr(scope, expr)
        self.evaluating_keys.remove(cache_key)
        self.evaluated_cache[cache_key] = val
        return list(val) if isinstance(val, list) else val

    def eval_expr(self, scope: BlockScope, expr: ExprNode) -> Any:
        result = self.eval_term(scope, expr.terms[0])
        for term in expr.terms[1:]:
            right = self.eval_term(scope, term)
            result = self.apply_plus(result, right)
        return result

    def apply_plus(self, left: Any, right: Any) -> Any:
        # Reject bools explicitly since isinstance(True, int) is True in Python
        if isinstance(left, bool) or isinstance(right, bool):
            raise ConfigError("Cannot use '+' operator with boolean values")
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left + right
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        if isinstance(left, list) and isinstance(right, list):
            return left + right
        raise ConfigError(
            f"Type mismatch for '+' operator: {type(left).__name__} and {type(right).__name__}"
        )

    def eval_ref_spec(self, scope: BlockScope, spec: RefSpec) -> Any:
        if spec.kind == 'ENV':
            if spec.has_default:
                val = self.env.get(spec.env_var, "")
                return val if val != "" else spec.default_val
            else:
                if spec.env_var not in self.env:
                    raise ConfigError(f"Undefined environment variable: {spec.env_var}")
                return self.env[spec.env_var]
        else:
            return self.lookup_value(scope, spec.path)

    def eval_term(self, scope: BlockScope, term: TermNode) -> Any:
        if isinstance(term, LiteralNode):
            return term.value
        if isinstance(term, RefNode):
            return self.eval_ref_spec(scope, term.spec)
        if isinstance(term, ListNode):
            return [self.eval_expr(scope, el) for el in term.elements]
        if isinstance(term, StringNode):
            out: list[str] = []
            for kind, part in term.parts:
                if kind == 'LIT':
                    out.append(part)
                else:
                    val = self.eval_ref_spec(scope, part)
                    out.append(self.format_for_interpolation(val))
            return ''.join(out)
        raise ConfigError("Unknown term node")

    def format_for_interpolation(self, val: Any) -> str:
        if val is None:
            return "null"
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, (int, float, str)):
            return str(val)
        raise ConfigError(f"Cannot interpolate {type(val).__name__} into string")

    def evaluate_scope_to_dict(self, scope: BlockScope) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in scope.entries.items():
            if isinstance(v, BlockScope):
                result[k] = self.evaluate_scope_to_dict(v)
            else:
                result[k] = self.eval_key(scope, k)
        return result


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    if not isinstance(text, str):
        raise ConfigError("Config text must be a string")
    env_dict = dict(env) if env is not None else {}
    tokens = tokenize(text)
    parser = Parser(tokens)
    root_scope = parser.parse_root()
    evaluator = Evaluator(root_scope, env_dict)
    evaluator.resolve_all_inheritance(root_scope)
    return evaluator.evaluate_scope_to_dict(root_scope)

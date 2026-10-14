=== FILE: config_parser.py ===
import copy
import re
import sys
from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


_IDENT_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*')
_NUM_RE = re.compile(r'[+-]?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?')
_ENV_NAME_RE = re.compile(r'[A-Za-z0-9_]+')
_NUM_TAIL_CHARS = frozenset(
    'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.'
)
_ESCAPES = {'"': '"', '\\': '\\', 'n': '\n', 't': '\t', 'r': '\r', '$': '$'}


def _is_digit(c: str) -> bool:
    return c != '' and '0' <= c <= '9'


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0
        self.n = len(text)

    def error(self, msg: str, pos: int | None = None):
        p = self.pos if pos is None else pos
        line = self.text.count('\n', 0, p) + 1
        col = p - (self.text.rfind('\n', 0, p) + 1) + 1
        raise ConfigError(f"{msg} (line {line}, column {col})")

    def peek(self, off: int = 0) -> str:
        p = self.pos + off
        return self.text[p] if p < self.n else ''

    def at_eof(self) -> bool:
        return self.pos >= self.n

    # --- whitespace / comments ---

    def skip_ws(self):
        t = self.text
        while self.pos < self.n:
            c = t[self.pos]
            if c == ' ' or c == '\t':
                self.pos += 1
            elif c == '#' or t.startswith('//', self.pos):
                end = t.find('\n', self.pos)
                self.pos = self.n if end < 0 else end
            elif t.startswith('/*', self.pos):
                end = t.find('*/', self.pos + 2)
                if end < 0:
                    self.error('unterminated block comment')
                self.pos = end + 2
            else:
                break

    def skip_ws_nl(self):
        while True:
            self.skip_ws()
            c = self.peek()
            if c == '\n':
                self.pos += 1
            elif c == '\r':
                if self.peek(1) == '\n':
                    self.pos += 2
                else:
                    self.error('unexpected carriage return')
            else:
                return

    def skip_spaces(self):
        while self.peek() in (' ', '\t') and not self.at_eof():
            self.pos += 1

    # --- statements ---

    def parse_file(self):
        return self.parse_stmts(False)

    def parse_stmts(self, in_block: bool):
        stmts = []
        while True:
            while True:
                self.skip_ws_nl()
                if self.peek() == ';':
                    self.pos += 1
                    continue
                break
            if self.at_eof():
                if in_block:
                    self.error("unterminated block, expected '}'")
                break
            if self.peek() == '}':
                if in_block:
                    break
                self.error("unexpected '}'")
            stmts.append(self.parse_stmt())
            self.skip_ws()
            c = self.peek()
            if self.at_eof() or c in ('\n', '\r', ';'):
                continue
            if c == '}' and in_block:
                continue
            self.error('expected newline or ; after statement')
        return stmts

    def parse_stmt(self):
        start = self.pos
        path = self.parse_path()
        self.skip_ws()
        if self.peek() == '=':
            self.pos += 1
            self.skip_ws()
            expr = self.parse_expr()
            return ('assign', path, expr, start)
        self.skip_ws_nl()
        parent = None
        if self.peek() == ':':
            self.pos += 1
            self.skip_ws()
            parent = self.parse_path()
            self.skip_ws_nl()
        if self.peek() != '{':
            self.error("expected '=' or '{'")
        self.pos += 1
        body = self.parse_stmts(True)
        self.pos += 1  # '}'
        return ('block', path, parent, body, start)

    def parse_ident(self) -> str:
        m = _IDENT_RE.match(self.text, self.pos)
        if not m:
            self.error('expected identifier')
        self.pos = m.end()
        return m.group()

    def parse_path(self) -> tuple:
        parts = [self.parse_ident()]
        while self.peek() == '.':
            self.pos += 1
            parts.append(self.parse_ident())
        return tuple(parts)

    # --- expressions ---

    def parse_expr(self):
        terms = [self.parse_term()]
        while True:
            self.skip_ws()
            if self.peek() == '+':
                self.pos += 1
                self.skip_ws_nl()
                terms.append(self.parse_term())
            else:
                return ('expr', terms)

    def parse_term(self):
        c = self.peek()
        if c == '"':
            return self.parse_string()
        if c == '[':
            return self.parse_list()
        if c == '$' and self.peek(1) == '{':
            self.pos += 2
            return self.parse_ref_body()
        if _is_digit(c) or (c in ('+', '-') and c != '' and _is_digit(self.peek(1))):
            return self.parse_number()
        m = _IDENT_RE.match(self.text, self.pos)
        if m:
            word = m.group()
            if word == 'true':
                self.pos = m.end()
                return ('lit', True)
            if word == 'false':
                self.pos = m.end()
                return ('lit', False)
            if word == 'null':
                self.pos = m.end()
                return ('lit', None)
            self.error(f'unexpected identifier {word!r}')
        self.error('expected value')

    def parse_number(self):
        m = _NUM_RE.match(self.text, self.pos)
        if not m:
            self.error('invalid number')
        end = m.end()
        if end < self.n and self.text[end] in _NUM_TAIL_CHARS:
            self.error('invalid number')
        s = m.group()
        self.pos = end
        if m.group(2) or m.group(3):
            return ('lit', float(s))
        return ('lit', int(s))

    def parse_string(self):
        start = self.pos
        t = self.text
        self.pos += 1
        parts = []
        buf = []
        while True:
            if self.pos >= self.n:
                self.error('unterminated string literal', start)
            c = t[self.pos]
            if c == '"':
                self.pos += 1
                break
            if c == '\n' or c == '\r':
                self.error('newline in string literal')
            if c == '\\':
                nc = self.peek(1)
                if nc == '' or nc not in _ESCAPES:
                    self.error('invalid escape sequence')
                buf.append(_ESCAPES[nc])
                self.pos += 2
                continue
            if c == '$' and self.peek(1) == '{':
                if buf:
                    parts.append(''.join(buf))
                    buf = []
                self.pos += 2
                parts.append(self.parse_ref_body())
                continue
            buf.append(c)
            self.pos += 1
        if buf:
            parts.append(''.join(buf))
        return ('str', parts)

    def parse_ref_body(self):
        t = self.text
        if t.startswith('env:', self.pos):
            self.pos += 4
            m = _ENV_NAME_RE.match(t, self.pos)
            if not m:
                self.error('invalid environment variable name')
            name = m.group()
            self.pos = m.end()
            if self.peek() == '}':
                self.pos += 1
                return ('env', name, None)
            if t.startswith(':-', self.pos):
                self.pos += 2
                start = self.pos
                while True:
                    if self.pos >= self.n:
                        self.error("unterminated reference, expected '}'")
                    c = t[self.pos]
                    if c == '}':
                        break
                    if c == '\n' or c == '\r':
                        self.error("unterminated reference, expected '}'")
                    self.pos += 1
                default = t[start:self.pos]
                self.pos += 1
                return ('env', name, default)
            self.error('invalid environment variable reference')
        self.skip_spaces()
        path = self.parse_path()
        self.skip_spaces()
        if self.peek() != '}':
            self.error("expected '}' in reference")
        self.pos += 1
        return ('ref', path)

    def parse_list(self):
        self.pos += 1
        items = []
        self.skip_ws_nl()
        if self.peek() == ']':
            self.pos += 1
            return ('list', items)
        while True:
            items.append(self.parse_expr())
            self.skip_ws_nl()
            c = self.peek()
            if c == ',':
                self.pos += 1
                self.skip_ws_nl()
                if self.peek() == ']':
                    self.pos += 1
                    return ('list', items)
                continue
            if c == ']':
                self.pos += 1
                return ('list', items)
            self.error("expected ',' or ']' in list")


# ---------------------------------------------------------------------------
# Structure / evaluation
# ---------------------------------------------------------------------------

_PENDING, _ACTIVE, _DONE = 0, 1, 2


class _Node:
    __slots__ = ('children', 'parent', 'inherit', 'state', 'deep_state')

    def __init__(self, parent):
        self.children = {}
        self.parent = parent
        self.inherit = None
        self.state = _PENDING
        self.deep_state = _PENDING


class _Leaf:
    __slots__ = ('expr', 'parent', 'state', 'value')

    def __init__(self, expr, parent):
        self.expr = expr
        self.parent = parent
        self.state = _PENDING
        self.value = None


def _is_ancestor(a, b) -> bool:
    p = b.parent
    while p is not None:
        if p is a:
            return True
        p = p.parent
    return False


def _fmt(path) -> str:
    return '.'.join(path)


class _Evaluator:
    def __init__(self, env: dict[str, str]):
        self.env = env
        self.root = _Node(None)

    # --- build ---

    def _child_node(self, node, key):
        cur = node.children.get(key)
        if cur is None:
            cur = _Node(node)
            node.children[key] = cur
            return cur
        if not isinstance(cur, _Node):
            raise ConfigError(f'{key!r} is already defined as a non-block value')
        return cur

    def build(self, stmts, node):
        for st in stmts:
            if st[0] == 'assign':
                _, path, expr, _ = st
                cur = node
                for k in path[:-1]:
                    cur = self._child_node(cur, k)
                k = path[-1]
                if isinstance(cur.children.get(k), _Node):
                    raise ConfigError(f'{_fmt(path)!r} is already defined as a block')
                cur.children[k] = _Leaf(expr, cur)
            else:
                _, path, parent, body, _ = st
                cur = node
                for k in path:
                    cur = self._child_node(cur, k)
                if parent is not None:
                    if cur.inherit is not None:
                        raise ConfigError(f'block {_fmt(path)!r} has multiple inheritance specifications')
                    cur.inherit = parent
                self.build(body, cur)

    # --- inheritance ---

    def _find_block(self, start, path):
        self._ensure(start)
        scope = start
        while scope is not None:
            if path[0] in scope.children:
                break
            scope = scope.parent
        else:
            raise ConfigError(f'undefined inheritance parent {_fmt(path)!r}')
        cur = scope.children[path[0]]
        for k in path[1:]:
            if not isinstance(cur, _Node):
                raise ConfigError(f'undefined inheritance parent {_fmt(path)!r}')
            self._ensure(cur)
            if k not in cur.children:
                raise ConfigError(f'undefined inheritance parent {_fmt(path)!r}')
            cur = cur.children[k]
        if not isinstance(cur, _Node):
            raise ConfigError(f'inheritance parent {_fmt(path)!r} is not a block')
        self._ensure(cur)
        return cur

    def _ensure(self, node):
        if node.state == _DONE:
            return
        if node.state == _ACTIVE:
            raise ConfigError('circular inheritance detected')
        if node.parent is not None:
            self._ensure(node.parent)
        if node.state == _DONE:
            return
        node.state = _ACTIVE
        if node.inherit is not None:
            target = self._find_block(node.parent, node.inherit)
            if target is node or _is_ancestor(target, node) or _is_ancestor(node, target):
                raise ConfigError(f'circular inheritance from {_fmt(node.inherit)!r}')
            self._resolve_deep(target)
            self._merge_inherited(node, target)
        node.state = _DONE

    def _resolve_deep(self, node):
        if node.deep_state == _DONE:
            return
        if node.deep_state == _ACTIVE:
            raise ConfigError('circular inheritance detected')
        node.deep_state = _ACTIVE
        self._ensure(node)
        for child in list(node.children.values()):
            if isinstance(child, _Node):
                self._resolve_deep(child)
        node.deep_state = _DONE

    def _clone(self, item, parent):
        if isinstance(item, _Leaf):
            return _Leaf(item.expr, parent)
        n = _Node(parent)
        n.state = _DONE
        n.deep_state = _DONE
        n.children = {k: self._clone(v, n) for k, v in item.children.items()}
        return n

    def _merge_inherited(self, dst, src):
        new = {}
        for k, sv in src.children.items():
            if k not in dst.children:
                new[k] = self._clone(sv, dst)
                continue
            dv = dst.children[k]
            if isinstance(dv, _Node) and isinstance(sv, _Node):
                self._merge_inherited(dv, sv)
                new[k] = dv
            elif isinstance(dv, _Leaf) and isinstance(sv, _Leaf):
                new[k] = dv
            else:
                raise ConfigError(f'type conflict on inherited key {k!r}')
        for k, dv in dst.children.items():
            if k not in new:
                new[k] = dv
        dst.children = new

    # --- evaluation ---

    def _eval_leaf(self, leaf):
        if leaf.state == _DONE:
            return leaf.value
        if leaf.state == _ACTIVE:
            raise ConfigError('circular reference detected')
        leaf.state = _ACTIVE
        value = self._eval_expr(leaf.expr, leaf.parent)
        leaf.value = value
        leaf.state = _DONE
        return value

    def _lookup(self, path, scope):
        s = scope
        while s is not None:
            if path[0] in s.children:
                break
            s = s.parent
        else:
            raise ConfigError(f'undefined reference {_fmt(path)!r}')
        cur = s.children[path[0]]
        for k in path[1:]:
            if not isinstance(cur, _Node) or k not in cur.children:
                raise ConfigError(f'undefined reference {_fmt(path)!r}')
            cur = cur.children[k]
        if isinstance(cur, _Node):
            raise ConfigError(f'reference {_fmt(path)!r} points to a block')
        return self._eval_leaf(cur)

    def _eval_env(self, name, default):
        if default is None:
            if name not in self.env:
                raise ConfigError(f'undefined environment variable {name!r}')
            return str(self.env[name])
        v = self.env.get(name)
        if v is None or v == '':
            return default
        return str(v)

    @staticmethod
    def _to_str(v):
        if isinstance(v, bool):
            return 'true' if v else 'false'
        if v is None:
            return 'null'
        if isinstance(v, str):
            return v
        if isinstance(v, (int, float)):
            return str(v)
        raise ConfigError('cannot interpolate list or block into string')

    def _eval_term(self, term, scope):
        kind = term[0]
        if kind == 'lit':
            return term[1]
        if kind == 'str':
            out = []
            for part in term[1]:
                if isinstance(part, str):
                    out.append(part)
                elif part[0] == 'ref':
                    out.append(self._to_str(self._lookup(part[1], scope)))
                else:
                    out.append(self._eval_env(part[1], part[2]))
            return ''.join(out)
        if kind == 'list':
            return [self._eval_expr(e, scope) for e in term[1]]
        if kind == 'ref':
            return self._lookup(term[1], scope)
        if kind == 'env':
            return self._eval_env(term[1], term[2])
        raise ConfigError(f'unknown term {kind!r}')

    @staticmethod
    def _add(a, b):
        a_num = isinstance(a, (int, float)) and not isinstance(a, bool)
        b_num = isinstance(b, (int, float)) and not isinstance(b, bool)
        if a_num and b_num:
            return a + b
        if isinstance(a, str) and isinstance(b, str):
            return a + b
        if isinstance(a, list) and isinstance(b, list):
            return a + b
        raise ConfigError(f'unsupported operand types for +: {type(a).__name__} and {type(b).__name__}')

    def _eval_expr(self, expr, scope):
        terms = expr[1]
        value = self._eval_term(terms[0], scope)
        for t in terms[1:]:
            value = self._add(value, self._eval_term(t, scope))
        return value

    def _to_dict(self, node):
        out = {}
        for k, v in node.children.items():
            if isinstance(v, _Node):
                out[k] = self._to_dict(v)
            else:
                out[k] = copy.deepcopy(self._eval_leaf(v))
        return out

    def run(self, stmts):
        self.build(stmts, self.root)
        self._resolve_deep(self.root)
        return self._to_dict(self.root)


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    """
    HCL Lite 形式の文字列 text を解析・評価し、結果の辞書を返す。
    env は環境変数の辞書であり、省略時または None の場合は空辞書として扱う。
    （os.environ は参照してはならない）
    """
    if env is None:
        env = {}
    if sys.getrecursionlimit() < 10000:
        sys.setrecursionlimit(10000)
    try:
        stmts = _Parser(text).parse_file()
        return _Evaluator(env).run(stmts)
    except RecursionError:
        raise ConfigError('configuration is nested too deeply') from None
=== END ===
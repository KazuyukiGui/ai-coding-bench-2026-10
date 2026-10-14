=== FILE: config_parser.py ===
import re
import sys
from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


_IDENT_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_\-]*')
_NUM_RE = re.compile(r'([0-9]+)(\.[0-9]+)?([eE][+-]?[0-9]+)?')
_PATH_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_\-]*(?:\.[A-Za-z_][A-Za-z0-9_\-]*)*')
_ENV_RE = re.compile(r'([A-Za-z0-9_]+)(?::-(.*))?', re.DOTALL)

_SINGLE = {
    '.': 'DOT', '=': 'EQ', '{': 'LBRACE', '}': 'RBRACE', '[': 'LBRACK',
    ']': 'RBRACK', ',': 'COMMA', ':': 'COLON', ';': 'SEMI', '+': 'PLUS',
    '-': 'MINUS',
}
_ESCAPES = {'"': '"', '\\': '\\', 'n': '\n', 't': '\t', 'r': '\r', '$': '$'}


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

class _Token:
    __slots__ = ('type', 'value', 'start', 'end')

    def __init__(self, type_, value, start, end):
        self.type = type_
        self.value = value
        self.start = start
        self.end = end


def _line_of(text, pos):
    return text.count('\n', 0, pos) + 1


def _parse_ref_content(content):
    stripped = content.lstrip(' \t')
    if stripped.startswith('env:'):
        m = _ENV_RE.fullmatch(stripped[4:])
        if not m:
            raise ConfigError(f"invalid environment reference: ${{{content}}}")
        return ('env', m.group(1), m.group(2))
    path = content.strip(' \t')
    if not _PATH_RE.fullmatch(path):
        raise ConfigError(f"invalid reference: ${{{content}}}")
    return ('ref', path.split('.'))


def _lex_string(text, i):
    """i points at the opening quote. Returns (ast, end_index)."""
    n = len(text)
    j = i + 1
    parts = []
    buf = []
    while True:
        if j >= n:
            raise ConfigError(f"line {_line_of(text, i)}: unterminated string")
        ch = text[j]
        if ch == '"':
            j += 1
            break
        if ch == '\n' or ch == '\r':
            raise ConfigError(f"line {_line_of(text, j)}: newline in string literal")
        if ch == '\\':
            nxt = text[j + 1] if j + 1 < n else ''
            if nxt not in _ESCAPES:
                raise ConfigError(f"line {_line_of(text, j)}: invalid escape sequence '\\{nxt}'")
            buf.append(_ESCAPES[nxt])
            j += 2
        elif ch == '$' and text[j + 1:j + 2] == '{':
            k = text.find('}', j + 2)
            if k == -1:
                raise ConfigError(f"line {_line_of(text, j)}: unterminated interpolation")
            content = text[j + 2:k]
            if '\n' in content or '\r' in content:
                raise ConfigError(f"line {_line_of(text, j)}: unterminated interpolation")
            if buf:
                parts.append(''.join(buf))
                buf = []
            parts.append(_parse_ref_content(content))
            j = k + 1
        else:
            buf.append(ch)
            j += 1
    if buf:
        parts.append(''.join(buf))
    if all(isinstance(p, str) for p in parts):
        return ('lit', ''.join(parts)), j
    return ('str', parts), j


def _tokenize(text):
    toks = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == ' ' or c == '\t':
            i += 1
            continue
        if c == '\n':
            toks.append(_Token('NL', None, i, i + 1))
            i += 1
            continue
        if c == '\r':
            if i + 1 < n and text[i + 1] == '\n':
                toks.append(_Token('NL', None, i, i + 2))
                i += 2
            else:
                i += 1
            continue
        if c == '#' or text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j == -1 else j
            continue
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            if j == -1:
                raise ConfigError(f"line {_line_of(text, i)}: unterminated block comment")
            if '\n' in text[i + 2:j]:
                toks.append(_Token('NL', None, i, j + 2))
            i = j + 2
            continue
        if c.isascii() and (c.isalpha() or c == '_'):
            m = _IDENT_RE.match(text, i)
            toks.append(_Token('IDENT', m.group(), i, m.end()))
            i = m.end()
            continue
        if '0' <= c <= '9':
            m = _NUM_RE.match(text, i)
            intpart, frac, exp = m.groups()
            if len(intpart) > 1 and intpart[0] == '0':
                raise ConfigError(f"line {_line_of(text, i)}: invalid number with leading zero")
            e = m.end()
            if e < n and (text[e].isalnum() or text[e] in '_.'):
                raise ConfigError(f"line {_line_of(text, i)}: invalid number literal")
            s = m.group()
            val = float(s) if (frac or exp) else int(s)
            toks.append(_Token('NUM', val, i, e))
            i = e
            continue
        if c == '"':
            ast, j = _lex_string(text, i)
            toks.append(_Token('STR', ast, i, j))
            i = j
            continue
        if c == '$':
            if text[i + 1:i + 2] != '{':
                raise ConfigError(f"line {_line_of(text, i)}: unexpected '$'")
            j = text.find('}', i + 2)
            if j == -1 or '\n' in text[i + 2:j] or '\r' in text[i + 2:j]:
                raise ConfigError(f"line {_line_of(text, i)}: unterminated reference")
            toks.append(_Token('REF', _parse_ref_content(text[i + 2:j]), i, j + 1))
            i = j + 1
            continue
        if c in _SINGLE:
            toks.append(_Token(_SINGLE[c], c, i, i + 1))
            i += 1
            continue
        raise ConfigError(f"line {_line_of(text, i)}: unexpected character {c!r}")
    toks.append(_Token('EOF', None, n, n))
    return toks


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, text, toks):
        self.text = text
        self.toks = toks
        self.pos = 0

    def peek(self):
        return self.toks[self.pos]

    def advance(self):
        t = self.toks[self.pos]
        if t.type != 'EOF':
            self.pos += 1
        return t

    def error(self, msg, tok=None):
        tok = tok or self.peek()
        return ConfigError(f"line {_line_of(self.text, tok.start)}: {msg}")

    def expect(self, tp):
        t = self.peek()
        if t.type != tp:
            raise self.error(f"expected {tp}, got {t.type}")
        return self.advance()

    def skip_nl(self):
        while self.peek().type == 'NL':
            self.pos += 1

    def parse_body(self, in_block):
        stmts = []
        while True:
            t = self.peek()
            if t.type in ('NL', 'SEMI'):
                self.advance()
                continue
            if t.type == 'EOF':
                if in_block:
                    raise self.error("unclosed block")
                break
            if t.type == 'RBRACE':
                if not in_block:
                    raise self.error("unexpected '}'")
                break
            stmts.append(self.parse_statement())
            t = self.peek()
            if t.type in ('NL', 'SEMI'):
                self.advance()
            elif t.type == 'EOF' or (t.type == 'RBRACE' and in_block):
                pass
            else:
                raise self.error(f"unexpected token {t.type} after statement")
        return stmts

    def parse_statement(self):
        path = self.parse_path()
        if self.peek().type == 'EQ':
            self.advance()
            expr = self.parse_expr()
            return ('assign', path, expr)
        parent = None
        if self.peek().type == 'COLON':
            self.advance()
            parent = self.parse_path()
        self.skip_nl()
        self.expect('LBRACE')
        body = self.parse_body(True)
        self.expect('RBRACE')
        return ('block', path, parent, body)

    def parse_path(self):
        parts = [self.expect('IDENT').value]
        while self.peek().type == 'DOT':
            self.advance()
            parts.append(self.expect('IDENT').value)
        return parts

    def parse_expr(self):
        terms = [self.parse_term()]
        while self.peek().type == 'PLUS':
            self.advance()
            self.skip_nl()
            terms.append(self.parse_term())
        if len(terms) == 1:
            return terms[0]
        return ('add', terms)

    def parse_term(self):
        t = self.peek()
        if t.type in ('PLUS', 'MINUS'):
            self.advance()
            num = self.peek()
            if num.type != 'NUM' or num.start != t.end:
                raise self.error("invalid sign", t)
            self.advance()
            return ('lit', -num.value if t.type == 'MINUS' else num.value)
        if t.type == 'NUM':
            self.advance()
            return ('lit', t.value)
        if t.type == 'STR' or t.type == 'REF':
            self.advance()
            return t.value
        if t.type == 'IDENT':
            if t.value == 'true':
                self.advance()
                return ('lit', True)
            if t.value == 'false':
                self.advance()
                return ('lit', False)
            if t.value == 'null':
                self.advance()
                return ('lit', None)
            raise self.error(f"unexpected identifier '{t.value}' in expression")
        if t.type == 'LBRACK':
            return self.parse_list()
        raise self.error(f"unexpected token {t.type} in expression")

    def parse_list(self):
        self.expect('LBRACK')
        items = []
        self.skip_nl()
        if self.peek().type == 'RBRACK':
            self.advance()
            return ('list', items)
        while True:
            items.append(self.parse_expr())
            self.skip_nl()
            t = self.peek()
            if t.type == 'COMMA':
                self.advance()
                self.skip_nl()
                if self.peek().type == 'RBRACK':
                    self.advance()
                    break
            elif t.type == 'RBRACK':
                self.advance()
                break
            else:
                raise self.error(f"unexpected token {t.type} in list")
        return ('list', items)


# ---------------------------------------------------------------------------
# Tree / evaluation
# ---------------------------------------------------------------------------

class _Node:
    __slots__ = ('entries', 'parent', 'inherit', 'state')

    def __init__(self, parent):
        self.entries = {}
        self.parent = parent
        self.inherit = None
        # 0: unresolved, 1: merging, 2: merged, 3: full-resolving, 4: done
        self.state = 0


class _Leaf:
    __slots__ = ('expr', 'container', 'state', 'value')

    def __init__(self, expr, container):
        self.expr = expr
        self.container = container
        self.state = 0
        self.value = None


def _descend(node, path):
    cur = node
    for k in path:
        ex = cur.entries.get(k)
        if ex is None:
            ex = _Node(cur)
            cur.entries[k] = ex
        elif not isinstance(ex, _Node):
            raise ConfigError(f"'{k}' is already defined as a non-block value")
        cur = ex
    return cur


def _build(node, stmts):
    for st in stmts:
        if st[0] == 'assign':
            _, path, expr = st
            cur = _descend(node, path[:-1])
            k = path[-1]
            if isinstance(cur.entries.get(k), _Node):
                raise ConfigError(f"'{k}' is already defined as a block")
            cur.entries[k] = _Leaf(expr, cur)
        else:
            _, path, parent, body = st
            cur = _descend(node, path)
            if parent is not None:
                if cur.inherit is not None:
                    raise ConfigError(f"multiple inheritance for '{'.'.join(path)}'")
                cur.inherit = parent
            _build(cur, body)


def _clone(v, parent):
    if isinstance(v, _Node):
        n = _Node(parent)
        n.state = 4
        for k, c in v.entries.items():
            n.entries[k] = _clone(c, n)
        return n
    return _Leaf(v.expr, parent)


def _merge_under(dst, src):
    for k, sv in src.entries.items():
        dv = dst.entries.get(k)
        if dv is None:
            dst.entries[k] = _clone(sv, dst)
        elif isinstance(dv, _Node):
            if not isinstance(sv, _Node):
                raise ConfigError(f"type conflict on inherited key '{k}'")
            _merge_under(dv, sv)
        elif isinstance(sv, _Node):
            raise ConfigError(f"type conflict on inherited key '{k}'")


def _is_ancestor(a, b):
    p = b.parent
    while p is not None:
        if p is a:
            return True
        p = p.parent
    return False


def _copy_val(v):
    if type(v) is list:
        return [_copy_val(x) for x in v]
    return v


def _to_str(v):
    if v is True:
        return 'true'
    if v is False:
        return 'false'
    if v is None:
        return 'null'
    if type(v) is str:
        return v
    if type(v) in (int, float):
        return str(v)
    raise ConfigError("cannot interpolate list or block into string")


class _Evaluator:
    def __init__(self, env):
        self.env = env

    def lookup(self, scope, path, structural):
        head = path[0]
        s = scope
        while s is not None:
            if structural:
                self.merge_inherit(s)
            if head in s.entries:
                break
            s = s.parent
        else:
            raise ConfigError(f"undefined reference '{'.'.join(path)}'")
        cur = s.entries[head]
        for k in path[1:]:
            if not isinstance(cur, _Node):
                raise ConfigError(f"cannot resolve '{'.'.join(path)}': not a block")
            if structural:
                self.merge_inherit(cur)
            nxt = cur.entries.get(k)
            if nxt is None:
                raise ConfigError(f"undefined reference '{'.'.join(path)}'")
            cur = nxt
        return cur

    def merge_inherit(self, node):
        if node.state >= 2:
            return
        if node.state == 1:
            raise ConfigError("circular inheritance detected")
        node.state = 1
        if node.inherit is not None:
            target = self.lookup(node.parent, node.inherit, True)
            if not isinstance(target, _Node):
                raise ConfigError(f"inheritance target '{'.'.join(node.inherit)}' is not a block")
            if target is node or _is_ancestor(target, node) or _is_ancestor(node, target):
                raise ConfigError(f"circular inheritance of '{'.'.join(node.inherit)}'")
            self.full_resolve(target)
            _merge_under(node, target)
        node.state = 2

    def full_resolve(self, node):
        self.merge_inherit(node)
        if node.state == 4:
            return
        if node.state == 3:
            raise ConfigError("circular inheritance detected")
        node.state = 3
        for v in list(node.entries.values()):
            if isinstance(v, _Node):
                self.full_resolve(v)
        node.state = 4

    def eval_leaf(self, leaf):
        if leaf.state == 2:
            return leaf.value
        if leaf.state == 1:
            raise ConfigError("circular reference detected")
        leaf.state = 1
        v = self.eval_expr(leaf.expr, leaf.container)
        leaf.value = v
        leaf.state = 2
        return v

    def eval_ref(self, path, scope):
        t = self.lookup(scope, path, False)
        if isinstance(t, _Node):
            raise ConfigError(f"reference '{'.'.join(path)}' points to a block")
        return _copy_val(self.eval_leaf(t))

    def eval_env(self, name, default):
        if default is None:
            if name not in self.env:
                raise ConfigError(f"undefined environment variable '{name}'")
            return self.env[name]
        val = self.env.get(name)
        if val is None or val == '':
            return default
        return val

    def eval_expr(self, e, scope):
        kind = e[0]
        if kind == 'lit':
            return e[1]
        if kind == 'list':
            return [self.eval_expr(x, scope) for x in e[1]]
        if kind == 'ref':
            return self.eval_ref(e[1], scope)
        if kind == 'env':
            return self.eval_env(e[1], e[2])
        if kind == 'str':
            out = []
            for p in e[1]:
                if isinstance(p, str):
                    out.append(p)
                elif p[0] == 'env':
                    out.append(self.eval_env(p[1], p[2]))
                else:
                    out.append(_to_str(self.eval_ref(p[1], scope)))
            return ''.join(out)
        if kind == 'add':
            acc = self.eval_expr(e[1][0], scope)
            for term in e[1][1:]:
                acc = self.add(acc, self.eval_expr(term, scope))
            return acc
        raise ConfigError(f"unknown expression kind {kind}")

    @staticmethod
    def add(a, b):
        ta, tb = type(a), type(b)
        if ta in (int, float) and tb in (int, float):
            return a + b
        if ta is str and tb is str:
            return a + b
        if ta is list and tb is list:
            return a + b
        raise ConfigError(f"unsupported operand types for +: {ta.__name__} and {tb.__name__}")

    def to_dict(self, node):
        out = {}
        for k, v in node.entries.items():
            if isinstance(v, _Node):
                out[k] = self.to_dict(v)
            else:
                out[k] = _copy_val(self.eval_leaf(v))
        return out


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    """
    HCL Lite 形式の文字列 text を解析・評価し、結果の辞書を返す。
    env は環境変数の辞書であり、省略時または None の場合は空辞書として扱う。
    （os.environ は参照してはならない）
    """
    if env is None:
        env = {}
    old_limit = sys.getrecursionlimit()
    if old_limit < 30000:
        sys.setrecursionlimit(30000)
    try:
        toks = _tokenize(text)
        parser = _Parser(text, toks)
        stmts = parser.parse_body(False)
        root = _Node(None)
        _build(root, stmts)
        ev = _Evaluator(env)
        ev.full_resolve(root)
        return ev.to_dict(root)
    except RecursionError:
        raise ConfigError("configuration is too deeply nested or recursive") from None
    finally:
        sys.setrecursionlimit(old_limit)
=== END ===
=== FILE: config_parser.py ===
import re
import sys
from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


_IDENT_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*')
_PATH_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*\Z')
_NUM_RE = re.compile(r'[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?')
_INT_PART_RE = re.compile(r'[0-9]+')
_ENV_NAME_RE = re.compile(r'[A-Za-z0-9_]+')

_ESCAPES = {'"': '"', '\\': '\\', 'n': '\n', 't': '\t', 'r': '\r', '$': '$'}
_PUNCT = '=:{}[],;+-.'

_PENDING = 0
_ACTIVE = 1
_DONE = 2


def _is_ident_start(ch: str) -> bool:
    return ch == '_' or ('a' <= ch <= 'z') or ('A' <= ch <= 'Z')


def _is_ident_char(ch: str) -> bool:
    return _is_ident_start(ch) or ('0' <= ch <= '9') or ch == '-'


def _line_of(text: str, pos: int) -> int:
    return text.count('\n', 0, pos) + 1


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------

class _Tok:
    __slots__ = ('kind', 'value', 'pos')

    def __init__(self, kind, value, pos):
        self.kind = kind
        self.value = value
        self.pos = pos


def _parse_ref(content: str):
    if content.startswith('env:'):
        rest = content[4:]
        m = _ENV_NAME_RE.match(rest)
        if not m:
            raise ConfigError(f"invalid environment variable reference: ${{{content}}}")
        name = m.group()
        after = rest[m.end():]
        if after == '':
            return ('env', name, None)
        if after.startswith(':-'):
            return ('env', name, after[2:])
        raise ConfigError(f"invalid environment variable reference: ${{{content}}}")
    s = content.strip(' \t')
    if not _PATH_RE.match(s):
        raise ConfigError(f"invalid reference path: ${{{content}}}")
    return ('ref', s.split('.'))


def _lex_string(text: str, i: int):
    n = len(text)
    start = i
    i += 1
    parts = []
    buf = []
    while True:
        if i >= n:
            raise ConfigError(f"line {_line_of(text, start)}: unterminated string literal")
        c = text[i]
        if c == '"':
            i += 1
            break
        if c == '\n' or c == '\r':
            raise ConfigError(f"line {_line_of(text, i)}: newline in string literal")
        if c == '\\':
            if i + 1 >= n:
                raise ConfigError(f"line {_line_of(text, i)}: unterminated string literal")
            d = text[i + 1]
            if d not in _ESCAPES:
                raise ConfigError(f"line {_line_of(text, i)}: invalid escape sequence \\{d}")
            buf.append(_ESCAPES[d])
            i += 2
        elif c == '$' and i + 1 < n and text[i + 1] == '{':
            j = text.find('}', i + 2)
            if j < 0:
                raise ConfigError(f"line {_line_of(text, i)}: unterminated interpolation")
            content = text[i + 2:j]
            if '\n' in content or '\r' in content:
                raise ConfigError(f"line {_line_of(text, i)}: newline in interpolation")
            if buf:
                parts.append(''.join(buf))
                buf = []
            parts.append(_parse_ref(content))
            i = j + 1
        else:
            buf.append(c)
            i += 1
    if buf:
        parts.append(''.join(buf))
    return parts, i


def _tokenize(text: str) -> list:
    toks = []
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == ' ' or c == '\t':
            i += 1
        elif c == '\n':
            toks.append(_Tok('NL', None, i))
            i += 1
        elif c == '\r':
            if i + 1 < n and text[i + 1] == '\n':
                toks.append(_Tok('NL', None, i))
                i += 2
            else:
                raise ConfigError(f"line {_line_of(text, i)}: unexpected carriage return")
        elif c == '#' or text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            if j < 0:
                raise ConfigError(f"line {_line_of(text, i)}: unterminated block comment")
            if '\n' in text[i + 2:j]:
                toks.append(_Tok('NL', None, i))
            i = j + 2
        elif c == '"':
            parts, j = _lex_string(text, i)
            toks.append(_Tok('STR', parts, i))
            i = j
        elif c == '$':
            if not text.startswith('${', i):
                raise ConfigError(f"line {_line_of(text, i)}: unexpected character '$'")
            j = text.find('}', i + 2)
            if j < 0:
                raise ConfigError(f"line {_line_of(text, i)}: unterminated reference")
            content = text[i + 2:j]
            if '\n' in content or '\r' in content:
                raise ConfigError(f"line {_line_of(text, i)}: newline in reference")
            toks.append(_Tok('REF', _parse_ref(content), i))
            i = j + 1
        elif '0' <= c <= '9':
            m = _NUM_RE.match(text, i)
            s = m.group()
            j = m.end()
            if j < n and (text[j] == '.' or _is_ident_char(text[j])):
                raise ConfigError(f"line {_line_of(text, i)}: invalid number literal")
            int_part = _INT_PART_RE.match(s).group()
            if len(int_part) > 1 and int_part[0] == '0':
                raise ConfigError(f"line {_line_of(text, i)}: leading zeros are not allowed")
            if '.' in s or 'e' in s or 'E' in s:
                val = float(s)
            else:
                val = int(s)
            toks.append(_Tok('NUM', val, i))
            i = j
        elif _is_ident_start(c):
            m = _IDENT_RE.match(text, i)
            toks.append(_Tok('IDENT', m.group(), i))
            i = m.end()
        elif c in _PUNCT:
            toks.append(_Tok(c, None, i))
            i += 1
        else:
            raise ConfigError(f"line {_line_of(text, i)}: unexpected character {c!r}")
    toks.append(_Tok('EOF', None, n))
    return toks


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, text: str, toks: list):
        self.text = text
        self.toks = toks
        self.i = 0

    def _err(self, msg, tok=None):
        if tok is None:
            tok = self.toks[self.i]
        return ConfigError(f"line {_line_of(self.text, tok.pos)}: {msg}")

    def peek(self):
        return self.toks[self.i]

    def advance(self):
        t = self.toks[self.i]
        if t.kind != 'EOF':
            self.i += 1
        return t

    def expect(self, kind):
        t = self.peek()
        if t.kind != kind:
            raise self._err(f"expected {kind!r}, got {t.kind!r}")
        return self.advance()

    def skip_nl(self):
        while self.peek().kind == 'NL':
            self.i += 1

    def parse_file(self):
        return self.parse_stmts(top=True)

    def parse_stmts(self, top: bool):
        stmts = []
        while True:
            t = self.peek()
            if t.kind in ('NL', ';'):
                self.advance()
                continue
            if t.kind == 'EOF':
                if top:
                    break
                raise self._err("unexpected end of input, expected '}'")
            if t.kind == '}':
                if top:
                    raise self._err("unexpected '}'")
                break
            stmts.append(self.parse_stmt())
            t = self.peek()
            if t.kind not in ('NL', ';', 'EOF', '}'):
                raise self._err("expected newline or ';' after statement")
        return stmts

    def parse_path(self):
        parts = [self.expect('IDENT').value]
        while self.peek().kind == '.':
            self.advance()
            parts.append(self.expect('IDENT').value)
        return parts

    def parse_stmt(self):
        path = self.parse_path()
        t = self.peek()
        if t.kind == '=':
            self.advance()
            expr = self.parse_expr()
            return ('assign', path, expr)
        parent = None
        if t.kind == ':':
            self.advance()
            parent = self.parse_path()
        self.skip_nl()
        self.expect('{')
        body = self.parse_stmts(top=False)
        self.expect('}')
        return ('block', path, parent, body)

    def parse_expr(self):
        terms = [self.parse_term()]
        while self.peek().kind == '+':
            self.advance()
            self.skip_nl()
            terms.append(self.parse_term())
        if len(terms) == 1:
            return terms[0]
        return ('add', terms)

    def parse_term(self):
        t = self.advance()
        k = t.kind
        if k == 'STR':
            return ('str', t.value)
        if k == 'NUM':
            return ('lit', t.value)
        if k == '+' or k == '-':
            nt = self.peek()
            if nt.kind == 'NUM' and nt.pos == t.pos + 1:
                self.advance()
                return ('lit', -nt.value if k == '-' else nt.value)
            raise self._err("invalid signed number", t)
        if k == 'IDENT':
            if t.value == 'true':
                return ('lit', True)
            if t.value == 'false':
                return ('lit', False)
            if t.value == 'null':
                return ('lit', None)
            raise self._err(f"unexpected identifier {t.value!r} in expression", t)
        if k == '[':
            return self.parse_list()
        if k == 'REF':
            return t.value
        raise self._err(f"unexpected token {k!r} in expression", t)

    def parse_list(self):
        items = []
        self.skip_nl()
        if self.peek().kind == ']':
            self.advance()
            return ('list', items)
        while True:
            items.append(self.parse_expr())
            self.skip_nl()
            t = self.peek()
            if t.kind == ',':
                self.advance()
                self.skip_nl()
                if self.peek().kind == ']':
                    self.advance()
                    break
                continue
            if t.kind == ']':
                self.advance()
                break
            raise self._err("expected ',' or ']' in list")
        return ('list', items)


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

class _Dict:
    __slots__ = ('entries', 'parent', 'inherit', 'state')

    def __init__(self, parent):
        self.entries = {}
        self.parent = parent
        self.inherit = None
        self.state = _PENDING


class _Value:
    __slots__ = ('expr', 'scope', 'state', 'value')

    def __init__(self, expr, scope):
        self.expr = expr
        self.scope = scope
        self.state = _PENDING
        self.value = None


def _descend(d: _Dict, keys) -> _Dict:
    for k in keys:
        ex = d.entries.get(k)
        if ex is None:
            new = _Dict(d)
            d.entries[k] = new
            d = new
        elif isinstance(ex, _Dict):
            d = ex
        else:
            raise ConfigError(f"key {k!r} is not a block")
    return d


def _build(stmts, d: _Dict):
    for st in stmts:
        if st[0] == 'assign':
            _, path, expr = st
            cur = _descend(d, path[:-1])
            last = path[-1]
            if isinstance(cur.entries.get(last), _Dict):
                raise ConfigError(f"cannot overwrite block {'.'.join(path)!r} with a value")
            cur.entries[last] = _Value(expr, cur)
        else:
            _, path, parent, body = st
            cur = _descend(d, path)
            if parent is not None:
                if cur.inherit is not None:
                    raise ConfigError(f"block {'.'.join(path)!r} has multiple inheritance declarations")
                cur.inherit = parent
            _build(body, cur)


def _is_ancestor(a: _Dict, b: _Dict) -> bool:
    p = b.parent
    while p is not None:
        if p is a:
            return True
        p = p.parent
    return False


def _clone(n, parent: _Dict):
    if isinstance(n, _Dict):
        c = _Dict(parent)
        c.state = _DONE
        c.entries = {k: _clone(v, c) for k, v in n.entries.items()}
        return c
    return _Value(n.expr, parent)


def _merge_copy(dst: _Dict, src: _Dict):
    new_entries = {}
    for k, sv in src.entries.items():
        dv = dst.entries.get(k)
        if dv is None:
            new_entries[k] = _clone(sv, dst)
        elif isinstance(dv, _Dict) and isinstance(sv, _Dict):
            _merge_copy(dv, sv)
            new_entries[k] = dv
        elif not isinstance(dv, _Dict) and not isinstance(sv, _Dict):
            new_entries[k] = dv
        else:
            raise ConfigError(f"type conflict with inherited key {k!r}")
    for k, dv in dst.entries.items():
        if k not in new_entries:
            new_entries[k] = dv
    dst.entries = new_entries


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _stringify(v) -> str:
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if v is None:
        return 'null'
    if isinstance(v, str):
        return v
    if isinstance(v, (int, float)):
        return str(v)
    raise ConfigError("cannot interpolate a list or block into a string")


def _add(a, b):
    if _is_num(a) and _is_num(b):
        return a + b
    if isinstance(a, str) and isinstance(b, str):
        return a + b
    if isinstance(a, list) and isinstance(b, list):
        return a + b
    raise ConfigError(f"unsupported operand types for +: {type(a).__name__} and {type(b).__name__}")


def _copy_val(v):
    if isinstance(v, list):
        return [_copy_val(x) for x in v]
    return v


class _Evaluator:
    def __init__(self, env: dict):
        self.env = env

    # --- inheritance ---

    def resolve(self, node: _Dict):
        if node.state == _DONE:
            return
        if node.state == _ACTIVE:
            raise ConfigError("circular inheritance detected")
        if node.parent is not None:
            self.resolve(node.parent)
            if node.state == _DONE:
                return
            if node.state == _ACTIVE:
                raise ConfigError("circular inheritance detected")
        node.state = _ACTIVE
        if node.inherit is not None:
            target = self._find_parent_block(node.inherit, node.parent)
            if target is node or _is_ancestor(target, node) or _is_ancestor(node, target):
                raise ConfigError(f"invalid inheritance from {'.'.join(node.inherit)!r}")
            self.resolve_subtree(target)
            _merge_copy(node, target)
        node.state = _DONE

    def resolve_subtree(self, node: _Dict):
        self.resolve(node)
        for child in list(node.entries.values()):
            if isinstance(child, _Dict):
                self.resolve_subtree(child)

    def _find_parent_block(self, path, scope: _Dict) -> _Dict:
        name = '.'.join(path)
        s = scope
        while s is not None:
            self.resolve(s)
            if path[0] in s.entries:
                break
            s = s.parent
        if s is None:
            raise ConfigError(f"undefined parent block {name!r}")
        cur = s.entries[path[0]]
        for k in path[1:]:
            if not isinstance(cur, _Dict):
                raise ConfigError(f"undefined parent block {name!r}")
            self.resolve(cur)
            if k not in cur.entries:
                raise ConfigError(f"undefined parent block {name!r}")
            cur = cur.entries[k]
        if not isinstance(cur, _Dict):
            raise ConfigError(f"parent {name!r} is not a block")
        return cur

    # --- values ---

    def eval_value(self, vn: _Value):
        if vn.state == _DONE:
            return vn.value
        if vn.state == _ACTIVE:
            raise ConfigError("circular reference detected")
        vn.state = _ACTIVE
        v = self.eval_expr(vn.expr, vn.scope)
        vn.value = v
        vn.state = _DONE
        return v

    def eval_expr(self, expr, scope: _Dict):
        kind = expr[0]
        if kind == 'lit':
            return expr[1]
        if kind == 'str':
            out = []
            for p in expr[1]:
                if isinstance(p, str):
                    out.append(p)
                else:
                    out.append(_stringify(self.eval_expr(p, scope)))
            return ''.join(out)
        if kind == 'list':
            return [self.eval_expr(e, scope) for e in expr[1]]
        if kind == 'ref':
            return self._lookup_value(expr[1], scope)
        if kind == 'env':
            _, name, default = expr
            if default is None:
                if name not in self.env:
                    raise ConfigError(f"undefined environment variable {name!r}")
                return self.env[name]
            val = self.env.get(name)
            if val is None or val == '':
                return default
            return val
        if kind == 'add':
            terms = expr[1]
            acc = self.eval_expr(terms[0], scope)
            for t in terms[1:]:
                acc = _add(acc, self.eval_expr(t, scope))
            return acc
        raise ConfigError(f"unknown expression kind {kind!r}")

    def _lookup_value(self, path, scope: _Dict):
        name = '.'.join(path)
        s = scope
        while s is not None and path[0] not in s.entries:
            s = s.parent
        if s is None:
            raise ConfigError(f"undefined reference {name!r}")
        cur = s.entries[path[0]]
        for k in path[1:]:
            if not isinstance(cur, _Dict) or k not in cur.entries:
                raise ConfigError(f"undefined reference {name!r}")
            cur = cur.entries[k]
        if isinstance(cur, _Dict):
            raise ConfigError(f"reference {name!r} points to a block")
        return self.eval_value(cur)

    def to_output(self, node: _Dict) -> dict:
        out = {}
        for k, v in node.entries.items():
            if isinstance(v, _Dict):
                out[k] = self.to_output(v)
            else:
                out[k] = _copy_val(self.eval_value(v))
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
    try:
        if old_limit < 10000:
            sys.setrecursionlimit(10000)
        toks = _tokenize(text)
        stmts = _Parser(text, toks).parse_file()
        root = _Dict(None)
        _build(stmts, root)
        ev = _Evaluator(env)
        ev.resolve_subtree(root)
        return ev.to_output(root)
    except RecursionError:
        raise ConfigError("configuration is too deeply nested or recursive") from None
    finally:
        if sys.getrecursionlimit() != old_limit:
            sys.setrecursionlimit(old_limit)
=== END ===
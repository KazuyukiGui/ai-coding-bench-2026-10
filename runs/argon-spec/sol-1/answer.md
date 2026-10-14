=== FILE: config_parser.py ===
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


@dataclass(frozen=True)
class _Token:
    kind: str
    value: Any
    start: int
    end: int


@dataclass(frozen=True)
class _Literal:
    value: Any


@dataclass(frozen=True)
class _Reference:
    content: str


@dataclass(frozen=True)
class _String:
    parts: tuple[str | _Reference, ...]


@dataclass(frozen=True)
class _ListExpr:
    items: tuple[Any, ...]


@dataclass(frozen=True)
class _Add:
    terms: tuple[Any, ...]


@dataclass
class _Object:
    entries: dict[str, Any] = field(default_factory=dict)
    inherit: tuple[str, ...] | None = None


_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_PATH_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*"
)
_ENV_NAME_RE = re.compile(r"[A-Za-z0-9_]+")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


def _lex(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    n = len(text)
    single = {
        ".": "DOT",
        "=": "EQUAL",
        "{": "LBRACE",
        "}": "RBRACE",
        "[": "LBRACKET",
        "]": "RBRACKET",
        ",": "COMMA",
        ";": "SEMI",
        ":": "COLON",
        "+": "PLUS",
        "-": "MINUS",
    }

    while i < n:
        ch = text[i]

        if ch in " \t":
            i += 1
            continue

        if ch == "\n":
            tokens.append(_Token("NEWLINE", None, i, i + 1))
            i += 1
            continue

        if ch == "\r":
            if i + 1 < n and text[i + 1] == "\n":
                tokens.append(_Token("NEWLINE", None, i, i + 2))
                i += 2
                continue
            raise ConfigError("不正な改行です")

        if ch == "#":
            i += 1
            while i < n and text[i] not in "\r\n":
                i += 1
            continue

        if text.startswith("//", i):
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            continue

        if text.startswith("/*", i):
            start = i
            i += 2
            closed = False
            while i < n:
                if text.startswith("*/", i):
                    i += 2
                    closed = True
                    break
                if text[i] == "\n":
                    tokens.append(_Token("NEWLINE", None, i, i + 1))
                    i += 1
                elif text[i] == "\r":
                    if i + 1 < n and text[i + 1] == "\n":
                        tokens.append(_Token("NEWLINE", None, i, i + 2))
                        i += 2
                    else:
                        raise ConfigError("不正な改行です")
                else:
                    i += 1
            if not closed:
                raise ConfigError(f"閉じられていないブロックコメントです: {start}")
            continue

        if ch == '"':
            start = i
            i += 1
            parts: list[str | _Reference] = []
            buf: list[str] = []

            def flush() -> None:
                if buf:
                    parts.append("".join(buf))
                    buf.clear()

            closed = False
            while i < n:
                c = text[i]
                if c == '"':
                    i += 1
                    closed = True
                    break
                if c in "\r\n":
                    raise ConfigError("文字列リテラルに生の改行を含めることはできません")
                if c == "\\":
                    if i + 1 >= n:
                        raise ConfigError("閉じられていない文字列リテラルです")
                    esc = text[i + 1]
                    escapes = {
                        '"': '"',
                        "\\": "\\",
                        "n": "\n",
                        "t": "\t",
                        "r": "\r",
                        "$": "$",
                    }
                    if esc not in escapes:
                        raise ConfigError(f"未対応のエスケープシーケンスです: \\{esc}")
                    buf.append(escapes[esc])
                    i += 2
                    continue
                if c == "$" and i + 1 < n and text[i + 1] == "{":
                    end = text.find("}", i + 2)
                    if end < 0:
                        raise ConfigError("閉じられていない文字列補間です")
                    flush()
                    parts.append(_Reference(text[i + 2:end]))
                    i = end + 1
                    continue
                buf.append(c)
                i += 1

            if not closed:
                raise ConfigError("閉じられていない文字列リテラルです")
            flush()
            tokens.append(_Token("STRING", _String(tuple(parts)), start, i))
            continue

        if text.startswith("${", i):
            start = i
            end = text.find("}", i + 2)
            if end < 0:
                raise ConfigError("閉じられていない参照です")
            tokens.append(_Token("REFERENCE", text[i + 2:end], start, end + 1))
            i = end + 1
            continue

        ident = _IDENT_RE.match(text, i)
        if ident is not None:
            tokens.append(_Token("IDENT", ident.group(0), i, ident.end()))
            i = ident.end()
            continue

        number = _NUMBER_RE.match(text, i)
        if number is not None:
            tokens.append(_Token("NUMBER", number.group(0), i, number.end()))
            i = number.end()
            continue

        kind = single.get(ch)
        if kind is not None:
            tokens.append(_Token(kind, ch, i, i + 1))
            i += 1
            continue

        raise ConfigError(f"不正な文字です: {ch!r}")

    tokens.append(_Token("EOF", None, n, n))
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.pos = 0

    @property
    def current(self) -> _Token:
        return self.tokens[self.pos]

    def advance(self) -> _Token:
        token = self.current
        self.pos += 1
        return token

    def accept(self, kind: str) -> _Token | None:
        if self.current.kind == kind:
            return self.advance()
        return None

    def expect(self, kind: str) -> _Token:
        if self.current.kind != kind:
            raise ConfigError(
                f"{kind} が必要ですが {self.current.kind} が見つかりました"
            )
        return self.advance()

    def parse(self) -> _Object:
        root = _Object()
        self.parse_statements(root, root_level=True)
        self.expect("EOF")
        return root

    def parse_statements(self, target: _Object, root_level: bool = False) -> None:
        while True:
            while self.current.kind in ("NEWLINE", "SEMI"):
                self.advance()

            if self.current.kind == "EOF":
                if not root_level:
                    raise ConfigError("閉じられていないブロックです")
                return
            if self.current.kind == "RBRACE":
                if root_level:
                    raise ConfigError("対応する開き波括弧がありません")
                return

            path = self.parse_path()

            if self.accept("EQUAL") is not None:
                expr = self.parse_expr()
                self.assign(target, path, expr)
            else:
                parent: tuple[str, ...] | None = None
                if self.accept("COLON") is not None:
                    parent = self.parse_path()
                while self.accept("NEWLINE") is not None:
                    pass
                self.expect("LBRACE")
                block = self.ensure_block(target, path)
                if parent is not None:
                    if block.inherit is not None:
                        raise ConfigError("同一ブロックに複数の継承指定があります")
                    block.inherit = parent
                self.parse_statements(block)
                self.expect("RBRACE")

            if self.current.kind not in ("NEWLINE", "SEMI", "RBRACE", "EOF"):
                raise ConfigError("文は改行またはセミコロンで区切る必要があります")

    def parse_path(self) -> tuple[str, ...]:
        parts = [self.expect("IDENT").value]
        while self.accept("DOT") is not None:
            parts.append(self.expect("IDENT").value)
        return tuple(parts)

    def parse_expr(self) -> Any:
        terms = [self.parse_term()]
        while self.accept("PLUS") is not None:
            while self.accept("NEWLINE") is not None:
                pass
            terms.append(self.parse_term())
        if len(terms) == 1:
            return terms[0]
        return _Add(tuple(terms))

    def parse_term(self) -> Any:
        token = self.current

        if token.kind == "STRING":
            self.advance()
            return token.value

        if token.kind == "REFERENCE":
            self.advance()
            return _Reference(token.value)

        if token.kind in ("PLUS", "MINUS"):
            sign = self.advance()
            number = self.current
            if number.kind != "NUMBER" or number.start != sign.end:
                raise ConfigError("符号は数値リテラルの直前に記述してください")
            self.advance()
            prefix = "-" if sign.kind == "MINUS" else "+"
            return _Literal(self.parse_number(prefix + number.value))

        if token.kind == "NUMBER":
            self.advance()
            return _Literal(self.parse_number(token.value))

        if token.kind == "IDENT":
            self.advance()
            if token.value == "true":
                return _Literal(True)
            if token.value == "false":
                return _Literal(False)
            if token.value == "null":
                return _Literal(None)
            raise ConfigError(f"値の位置に不正な識別子があります: {token.value}")

        if token.kind == "LBRACKET":
            return self.parse_list()

        raise ConfigError(f"式の項が必要ですが {token.kind} が見つかりました")

    def parse_list(self) -> _ListExpr:
        self.expect("LBRACKET")
        items: list[Any] = []
        self.skip_newlines()

        if self.accept("RBRACKET") is not None:
            return _ListExpr(tuple(items))
        if self.current.kind == "COMMA":
            raise ConfigError("リストの先頭にカンマは置けません")

        while True:
            items.append(self.parse_expr())
            self.skip_newlines()

            if self.accept("RBRACKET") is not None:
                break
            self.expect("COMMA")
            self.skip_newlines()

            if self.accept("RBRACKET") is not None:
                break
            if self.current.kind == "COMMA":
                raise ConfigError("リストに空の要素があります")

        return _ListExpr(tuple(items))

    def skip_newlines(self) -> None:
        while self.accept("NEWLINE") is not None:
            pass

    @staticmethod
    def parse_number(raw: str) -> int | float:
        unsigned = raw[1:] if raw[:1] in "+-" else raw
        integer_part = re.split(r"[.eE]", unsigned, maxsplit=1)[0]
        if len(integer_part) > 1 and integer_part.startswith("0"):
            raise ConfigError(f"数値の先頭ゼロは許可されていません: {raw}")
        try:
            if "." in unsigned or "e" in unsigned.lower():
                return float(raw)
            return int(raw)
        except ValueError as exc:
            raise ConfigError(f"不正な数値です: {raw}") from exc

    @staticmethod
    def assign(target: _Object, path: tuple[str, ...], expr: Any) -> None:
        obj = target
        for part in path[:-1]:
            existing = obj.entries.get(part)
            if existing is None:
                child = _Object()
                obj.entries[part] = child
                obj = child
            elif isinstance(existing, _Object):
                obj = existing
            else:
                raise ConfigError(f"非辞書をパスの途中として使用できません: {part}")

        key = path[-1]
        existing = obj.entries.get(key)
        if isinstance(existing, _Object):
            raise ConfigError(f"辞書を非辞書で上書きできません: {key}")
        obj.entries[key] = expr

    @staticmethod
    def ensure_block(target: _Object, path: tuple[str, ...]) -> _Object:
        obj = target
        for part in path:
            existing = obj.entries.get(part)
            if existing is None:
                child = _Object()
                obj.entries[part] = child
                obj = child
            elif isinstance(existing, _Object):
                obj = existing
            else:
                raise ConfigError(f"非辞書をブロックとして使用できません: {part}")
        return obj


_MISSING = object()


class _Instance:
    def __init__(
        self,
        local: _Object | None,
        outer: _Instance | None,
        path: tuple[str, ...],
        fallbacks: list[_Instance] | None = None,
    ) -> None:
        self.local = local
        self.outer = outer
        self.path = path
        self.fallbacks = list(fallbacks or ())
        self.explicit: _Instance | None = None
        self._explicit_state = 0
        self._key_cache: dict[str, Any] = {}
        self._key_state: set[str] = set()

    def ensure_explicit(self) -> None:
        if self._explicit_state == 2:
            return
        if self._explicit_state == 1:
            raise ConfigError("継承の循環参照を検出しました")

        self._explicit_state = 1
        try:
            if self.local is not None and self.local.inherit is not None:
                if self.outer is None:
                    raise ConfigError("ルートブロックは継承できません")
                node, _ = _lookup(self.outer, self.local.inherit)
                if not isinstance(node, _Instance):
                    raise ConfigError("継承元はブロックでなければなりません")

                source = node.path
                target = self.path
                if (
                    source == target
                    or source == target[:len(source)]
                    or target == source[:len(target)]
                ):
                    raise ConfigError("自分自身・祖先・子孫は継承できません")
                self.explicit = node
            self._explicit_state = 2
        except Exception:
            self._explicit_state = 0
            raise

    def providers(self) -> list[_Instance]:
        self.ensure_explicit()
        result = list(self.fallbacks)
        if self.explicit is not None:
            result.append(self.explicit)
        return result

    def keys(self) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()

        for provider in self.providers():
            for key in provider.keys():
                if key not in seen:
                    seen.add(key)
                    result.append(key)

        if self.local is not None:
            for key in self.local.entries:
                if key not in seen:
                    seen.add(key)
                    result.append(key)

        return result

    def get(self, key: str) -> Any:
        if key in self._key_cache:
            return self._key_cache[key]
        if key in self._key_state:
            raise ConfigError("継承またはマージの循環参照を検出しました")

        self._key_state.add(key)
        try:
            inherited: list[Any] = []
            for provider in self.providers():
                value = provider.get(key)
                if value is not _MISSING:
                    inherited.append(value)

            local_value = _MISSING
            if self.local is not None:
                local_value = self.local.entries.get(key, _MISSING)

            values = list(inherited)
            if local_value is not _MISSING:
                values.append(local_value)
            if not values:
                return _MISSING

            has_object = any(
                isinstance(value, (_Object, _Instance)) for value in values
            )
            has_value = any(
                not isinstance(value, (_Object, _Instance)) for value in values
            )
            if has_object and has_value:
                raise ConfigError(f"辞書と非辞書の型が衝突しています: {key}")

            if not has_object:
                result = values[-1]
                self._key_cache[key] = result
                return result

            child_fallbacks: list[_Instance] = []
            local_object: _Object | None = None

            for value in inherited:
                if isinstance(value, _Instance):
                    child_fallbacks.append(value)
                elif isinstance(value, _Object):
                    child_fallbacks.append(
                        _Instance(value, self, self.path + (key,))
                    )

            if isinstance(local_value, _Object):
                local_object = local_value
            elif isinstance(local_value, _Instance):
                child_fallbacks.append(local_value)

            result = _Instance(
                local_object,
                self,
                self.path + (key,),
                child_fallbacks,
            )
            self._key_cache[key] = result
            return result
        finally:
            self._key_state.discard(key)


def _lookup(
    scope: _Instance, path: tuple[str, ...]
) -> tuple[Any, _Instance]:
    head = path[0]
    current: _Instance | None = scope

    while current is not None:
        node = current.get(head)
        if node is not _MISSING:
            owner = current
            for part in path[1:]:
                if not isinstance(node, _Instance):
                    raise ConfigError(
                        f"非辞書に対してパスをたどることはできません: {'.'.join(path)}"
                    )
                owner = node
                node = node.get(part)
                if node is _MISSING:
                    raise ConfigError(f"未定義の参照です: {'.'.join(path)}")
            return node, owner
        current = current.outer

    raise ConfigError(f"未定義の参照です: {'.'.join(path)}")


def _parse_reference(content: str) -> tuple[str, Any]:
    if content.startswith("env:"):
        rest = content[4:]
        if ":-" in rest:
            name, default = rest.split(":-", 1)
            if "${" in default:
                raise ConfigError("環境変数のデフォルト値でネスト参照は使えません")
            if _ENV_NAME_RE.fullmatch(name) is None:
                raise ConfigError(f"不正な環境変数名です: {name}")
            return "env_default", (name, default)

        if _ENV_NAME_RE.fullmatch(rest) is None:
            raise ConfigError(f"不正な環境変数名です: {rest}")
        return "env", rest

    if _PATH_RE.fullmatch(content) is None:
        raise ConfigError(f"不正な参照パスです: {content}")
    return "path", tuple(content.split("."))


class _Evaluator:
    def __init__(self, env: dict[str, str]) -> None:
        self.env = env
        self.memo: dict[tuple[int, str], Any] = {}
        self.value_state: set[tuple[int, str]] = set()
        self.object_state: set[int] = set()

    def resolve_reference(
        self, reference: _Reference, scope: _Instance
    ) -> Any:
        kind, data = _parse_reference(reference.content)

        if kind == "env":
            if data not in self.env:
                raise ConfigError(f"未定義の環境変数です: {data}")
            return self.env[data]

        if kind == "env_default":
            name, default = data
            value = self.env.get(name)
            return value if value not in (None, "") else default

        node, owner = _lookup(scope, data)
        if isinstance(node, _Instance):
            raise ConfigError("ブロックを値として参照することはできません")
        return self.eval_property(owner, data[-1], node)

    def eval_property(
        self, owner: _Instance, key: str, node: Any | None = None
    ) -> Any:
        cache_key = (id(owner), key)
        if cache_key in self.memo:
            return self.memo[cache_key]
        if cache_key in self.value_state:
            raise ConfigError("変数参照の循環を検出しました")

        if node is None:
            node = owner.get(key)
        if node is _MISSING:
            raise ConfigError(f"未定義のキーです: {key}")
        if isinstance(node, _Instance):
            raise ConfigError("ブロックを値として評価できません")

        self.value_state.add(cache_key)
        try:
            value = self.eval_expr(node, owner)
            self.memo[cache_key] = value
            return value
        finally:
            self.value_state.discard(cache_key)

    def eval_expr(self, expr: Any, scope: _Instance) -> Any:
        if isinstance(expr, _Literal):
            return expr.value

        if isinstance(expr, _Reference):
            return self.resolve_reference(expr, scope)

        if isinstance(expr, _String):
            output: list[str] = []
            for part in expr.parts:
                if isinstance(part, str):
                    output.append(part)
                    continue
                value = self.resolve_reference(part, scope)
                if isinstance(value, (list, dict)):
                    raise ConfigError("リストまたは辞書は文字列に補間できません")
                if value is None:
                    output.append("null")
                elif type(value) is bool:
                    output.append("true" if value else "false")
                else:
                    output.append(str(value))
            return "".join(output)

        if isinstance(expr, _ListExpr):
            return [self.eval_expr(item, scope) for item in expr.items]

        if isinstance(expr, _Add):
            values = [self.eval_expr(term, scope) for term in expr.terms]
            result = values[0]
            for right in values[1:]:
                if type(result) in (int, float) and type(right) in (int, float):
                    result = result + right
                elif isinstance(result, str) and isinstance(right, str):
                    result = result + right
                elif isinstance(result, list) and isinstance(right, list):
                    result = result + right
                else:
                    raise ConfigError(
                        f"+ 演算子に使用できない型です: "
                        f"{type(result).__name__}, {type(right).__name__}"
                    )
            return result

        raise ConfigError("不明な式です")

    def eval_object(self, instance: _Instance) -> dict[str, Any]:
        identity = id(instance)
        if identity in self.object_state:
            raise ConfigError("ブロック構造の循環を検出しました")

        self.object_state.add(identity)
        try:
            result: dict[str, Any] = {}
            for key in instance.keys():
                node = instance.get(key)
                if isinstance(node, _Instance):
                    result[key] = self.eval_object(node)
                else:
                    result[key] = self.eval_property(instance, key, node)
            return result
        finally:
            self.object_state.discard(identity)


def _validate_inheritance(
    instance: _Instance,
    visiting: set[int],
    completed: set[int],
) -> None:
    identity = id(instance)
    if identity in completed:
        return
    if identity in visiting:
        raise ConfigError("継承の循環参照を検出しました")

    visiting.add(identity)
    instance.ensure_explicit()

    for provider in instance.fallbacks:
        _validate_inheritance(provider, visiting, completed)
    if instance.explicit is not None:
        _validate_inheritance(instance.explicit, visiting, completed)

    for key in instance.keys():
        node = instance.get(key)
        if isinstance(node, _Instance):
            _validate_inheritance(node, visiting, completed)

    visiting.remove(identity)
    completed.add(identity)


def parse_config(
    text: str, env: dict[str, str] | None = None
) -> dict[str, Any]:
    try:
        tokens = _lex(text)
        raw_root = _Parser(tokens).parse()
        root = _Instance(raw_root, None, ())
        _validate_inheritance(root, set(), set())
        return _Evaluator({} if env is None else dict(env)).eval_object(root)
    except ConfigError:
        raise
    except RecursionError as exc:
        raise ConfigError("循環参照または過度に深い設定を検出しました") from exc
=== END ===
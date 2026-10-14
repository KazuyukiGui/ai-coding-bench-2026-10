=== FILE: config_parser.py ===
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_PATH_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*"
)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")
_ENV_RE = re.compile(r"env:([A-Za-z0-9_]+)(?::-(.*))?\Z", re.DOTALL)


@dataclass(frozen=True)
class _Token:
    kind: str
    value: Any
    pos: int
    end: int


@dataclass(frozen=True)
class _Literal:
    value: Any


@dataclass(frozen=True)
class _Reference:
    kind: str
    path: tuple[str, ...] | None = None
    variable: str | None = None
    default: str | None = None
    has_default: bool = False


@dataclass(frozen=True)
class _String:
    parts: tuple[str | _Reference, ...]


@dataclass(frozen=True)
class _ListExpr:
    items: tuple[Any, ...]


@dataclass(frozen=True)
class _Add:
    terms: tuple[Any, ...]


class _RawObject:
    def __init__(self) -> None:
        self.fields: dict[str, _RawObject | Any] = {}
        self.inherit: tuple[str, ...] | None = None


def _parse_reference(content: str) -> _Reference:
    env_match = _ENV_RE.fullmatch(content)
    if env_match is not None:
        variable = env_match.group(1)
        default = env_match.group(2)
        return _Reference(
            kind="env",
            variable=variable,
            default=default,
            has_default=default is not None,
        )

    if _PATH_RE.fullmatch(content) is None:
        raise ConfigError("不正な参照です")

    return _Reference(kind="path", path=tuple(content.split(".")))


class _Lexer:
    _PUNCTUATION = {
        ".": "DOT",
        "=": "EQUAL",
        "{": "LBRACE",
        "}": "RBRACE",
        ":": "COLON",
        ";": "SEMI",
        "+": "PLUS",
        "-": "MINUS",
        "[": "LBRACKET",
        "]": "RBRACKET",
        ",": "COMMA",
    }

    def __init__(self, text: str) -> None:
        if not isinstance(text, str):
            raise ConfigError("設定テキストは文字列である必要があります")
        self.text = text
        self.length = len(text)
        self.index = 0
        self.tokens: list[_Token] = []

    def tokenize(self) -> list[_Token]:
        while self.index < self.length:
            ch = self.text[self.index]

            if ch in " \t":
                self.index += 1
                continue

            if ch == "\n":
                self.tokens.append(
                    _Token("NEWLINE", None, self.index, self.index + 1)
                )
                self.index += 1
                continue

            if ch == "\r":
                if (
                    self.index + 1 < self.length
                    and self.text[self.index + 1] == "\n"
                ):
                    self.tokens.append(
                        _Token("NEWLINE", None, self.index, self.index + 2)
                    )
                    self.index += 2
                    continue
                raise ConfigError("不正な改行です")

            if ch == "#":
                self._skip_line_comment(1)
                continue

            if ch == "/" and self.index + 1 < self.length:
                following = self.text[self.index + 1]
                if following == "/":
                    self._skip_line_comment(2)
                    continue
                if following == "*":
                    self._skip_block_comment()
                    continue
                raise ConfigError("不正な文字 '/' です")

            if ch == '"':
                self.tokens.append(self._read_string())
                continue

            if (
                ch == "$"
                and self.index + 1 < self.length
                and self.text[self.index + 1] == "{"
            ):
                self.tokens.append(self._read_reference())
                continue

            ident_match = _IDENT_RE.match(self.text, self.index)
            if ident_match is not None:
                start = self.index
                self.index = ident_match.end()
                self.tokens.append(
                    _Token("IDENT", ident_match.group(0), start, self.index)
                )
                continue

            number_match = _NUMBER_RE.match(self.text, self.index)
            if number_match is not None:
                start = self.index
                spelling = number_match.group(0)
                self.index = number_match.end()
                self._validate_number(spelling)
                self.tokens.append(
                    _Token("NUMBER", spelling, start, self.index)
                )
                continue

            kind = self._PUNCTUATION.get(ch)
            if kind is not None:
                self.tokens.append(
                    _Token(kind, ch, self.index, self.index + 1)
                )
                self.index += 1
                continue

            raise ConfigError(f"不正な文字です: {ch!r}")

        self.tokens.append(_Token("EOF", None, self.length, self.length))
        return self.tokens

    @staticmethod
    def _validate_number(spelling: str) -> None:
        integer_part = spelling
        for marker in (".", "e", "E"):
            if marker in integer_part:
                integer_part = integer_part.split(marker, 1)[0]
        if len(integer_part) > 1 and integer_part.startswith("0"):
            raise ConfigError("数値リテラルの先頭ゼロは許可されません")

    def _skip_line_comment(self, prefix_length: int) -> None:
        self.index += prefix_length
        while self.index < self.length and self.text[self.index] not in "\r\n":
            self.index += 1

    def _skip_block_comment(self) -> None:
        self.index += 2
        while self.index < self.length:
            if (
                self.text[self.index] == "*"
                and self.index + 1 < self.length
                and self.text[self.index + 1] == "/"
            ):
                self.index += 2
                return

            if self.text[self.index] == "\n":
                self.tokens.append(
                    _Token("NEWLINE", None, self.index, self.index + 1)
                )
                self.index += 1
                continue

            if self.text[self.index] == "\r":
                if (
                    self.index + 1 < self.length
                    and self.text[self.index + 1] == "\n"
                ):
                    self.tokens.append(
                        _Token("NEWLINE", None, self.index, self.index + 2)
                    )
                    self.index += 2
                    continue
                raise ConfigError("不正な改行です")

            self.index += 1

        raise ConfigError("ブロックコメントが閉じられていません")

    def _read_reference(self) -> _Token:
        start = self.index
        self.index += 2
        content_start = self.index

        while self.index < self.length and self.text[self.index] != "}":
            self.index += 1

        if self.index >= self.length:
            raise ConfigError("参照が閉じられていません")

        content = self.text[content_start:self.index]
        self.index += 1
        return _Token(
            "REFERENCE",
            _parse_reference(content),
            start,
            self.index,
        )

    def _read_string(self) -> _Token:
        start = self.index
        self.index += 1
        parts: list[str | _Reference] = []
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                parts.append("".join(buffer))
                buffer.clear()

        escapes = {
            '"': '"',
            "\\": "\\",
            "n": "\n",
            "t": "\t",
            "r": "\r",
            "$": "$",
        }

        while self.index < self.length:
            ch = self.text[self.index]

            if ch == '"':
                flush()
                self.index += 1
                return _Token(
                    "STRING",
                    _String(tuple(parts)),
                    start,
                    self.index,
                )

            if ch in "\r\n":
                raise ConfigError("文字列リテラル内に生の改行は記述できません")

            if ch == "\\":
                if self.index + 1 >= self.length:
                    raise ConfigError("文字列リテラルが閉じられていません")
                escaped = self.text[self.index + 1]
                if escaped not in escapes:
                    raise ConfigError(f"未対応のエスケープです: \\{escaped}")
                buffer.append(escapes[escaped])
                self.index += 2
                continue

            if (
                ch == "$"
                and self.index + 1 < self.length
                and self.text[self.index + 1] == "{"
            ):
                flush()
                self.index += 2
                content_start = self.index
                while self.index < self.length and self.text[self.index] != "}":
                    if self.text[self.index] in "\r\n":
                        raise ConfigError(
                            "文字列リテラル内に生の改行は記述できません"
                        )
                    self.index += 1
                if self.index >= self.length:
                    raise ConfigError("文字列内の参照が閉じられていません")
                content = self.text[content_start:self.index]
                parts.append(_parse_reference(content))
                self.index += 1
                continue

            buffer.append(ch)
            self.index += 1

        raise ConfigError("文字列リテラルが閉じられていません")


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.index = 0
        self.root = _RawObject()

    @property
    def current(self) -> _Token:
        return self.tokens[self.index]

    def _advance(self) -> _Token:
        token = self.current
        self.index += 1
        return token

    def _accept(self, kind: str) -> _Token | None:
        if self.current.kind == kind:
            return self._advance()
        return None

    def _expect(self, kind: str) -> _Token:
        if self.current.kind != kind:
            raise ConfigError(f"{kind} が必要です")
        return self._advance()

    def _skip_separators(self) -> None:
        while self.current.kind in {"NEWLINE", "SEMI"}:
            self._advance()

    def _skip_newlines(self) -> None:
        while self.current.kind == "NEWLINE":
            self._advance()

    def parse(self) -> _RawObject:
        self._parse_body(self.root, closing=False)
        return self.root

    def _parse_body(self, target: _RawObject, closing: bool) -> None:
        while True:
            self._skip_separators()

            if self.current.kind == "EOF":
                if closing:
                    raise ConfigError("ブロックが閉じられていません")
                return

            if self.current.kind == "RBRACE":
                if not closing:
                    raise ConfigError("対応する開き波括弧がありません")
                self._advance()
                return

            self._parse_statement(target)

            if self.current.kind not in {
                "NEWLINE",
                "SEMI",
                "RBRACE",
                "EOF",
            }:
                raise ConfigError("文は改行またはセミコロンで区切る必要があります")

    def _parse_path(self) -> tuple[str, ...]:
        components = [self._expect("IDENT").value]
        while self._accept("DOT") is not None:
            components.append(self._expect("IDENT").value)
        return tuple(components)

    def _container_for(
        self, target: _RawObject, path: tuple[str, ...]
    ) -> tuple[_RawObject, str]:
        current = target
        for component in path[:-1]:
            existing = current.fields.get(component)
            if existing is None:
                child = _RawObject()
                current.fields[component] = child
                current = child
            elif isinstance(existing, _RawObject):
                current = existing
            else:
                raise ConfigError("非辞書値をパスの途中として使用できません")
        return current, path[-1]

    def _parse_statement(self, target: _RawObject) -> None:
        path = self._parse_path()

        if self._accept("EQUAL") is not None:
            expression = self._parse_expression()
            container, key = self._container_for(target, path)
            existing = container.fields.get(key)
            if isinstance(existing, _RawObject):
                raise ConfigError("辞書を非辞書値で上書きできません")
            container.fields[key] = expression
            return

        parent_path: tuple[str, ...] | None = None

        if self._accept("COLON") is not None:
            parent_path = self._parse_path()
            self._skip_newlines()
        elif self.current.kind == "NEWLINE":
            self._skip_newlines()

        self._expect("LBRACE")
        container, key = self._container_for(target, path)
        existing = container.fields.get(key)

        if existing is None:
            block = _RawObject()
            container.fields[key] = block
        elif isinstance(existing, _RawObject):
            block = existing
        else:
            raise ConfigError("非辞書値をブロックとして使用できません")

        if parent_path is not None:
            if block.inherit is not None:
                raise ConfigError("同じブロックに複数の継承は指定できません")
            block.inherit = parent_path

        self._parse_body(block, closing=True)

    def _parse_expression(self) -> Any:
        terms = [self._parse_term()]

        while self.current.kind == "PLUS":
            self._advance()
            self._skip_newlines()
            terms.append(self._parse_term())

        if len(terms) == 1:
            return terms[0]
        return _Add(tuple(terms))

    def _parse_term(self) -> Any:
        token = self.current

        if token.kind == "STRING":
            self._advance()
            return token.value

        if token.kind == "REFERENCE":
            self._advance()
            return token.value

        if token.kind == "LBRACKET":
            return self._parse_list()

        if token.kind in {"PLUS", "MINUS"}:
            sign = self._advance()
            number = self._expect("NUMBER")
            if sign.end != number.pos:
                raise ConfigError("数値の符号と数字の間に空白は置けません")
            value = self._number_value(number.value)
            if sign.kind == "MINUS":
                value = -value
            return _Literal(value)

        if token.kind == "NUMBER":
            self._advance()
            return _Literal(self._number_value(token.value))

        if token.kind == "IDENT":
            self._advance()
            if token.value == "true":
                return _Literal(True)
            if token.value == "false":
                return _Literal(False)
            if token.value == "null":
                return _Literal(None)
            raise ConfigError("値の位置に識別子は記述できません")

        raise ConfigError("式の項が必要です")

    @staticmethod
    def _number_value(spelling: str) -> int | float:
        if "." in spelling or "e" in spelling or "E" in spelling:
            return float(spelling)
        return int(spelling)

    def _parse_list(self) -> _ListExpr:
        self._expect("LBRACKET")
        self._skip_newlines()
        items: list[Any] = []

        if self._accept("RBRACKET") is not None:
            return _ListExpr(tuple(items))

        while True:
            if self.current.kind == "COMMA":
                raise ConfigError("空のリスト要素は許可されません")

            items.append(self._parse_expression())
            self._skip_newlines()

            if self._accept("RBRACKET") is not None:
                return _ListExpr(tuple(items))

            self._expect("COMMA")
            self._skip_newlines()

            if self._accept("RBRACKET") is not None:
                return _ListExpr(tuple(items))


_MISSING = object()


class _View:
    def __init__(
        self,
        world: _World,
        container: _View | None,
        ambient: tuple[_View, ...],
        local: _RawObject | None,
    ) -> None:
        self.world = world
        self.container = container
        self.ambient = ambient
        self.local = local
        self._bases_cache: tuple[_View, ...] | None = None
        self._bases_state = 0
        self._keys_cache: tuple[str, ...] | None = None
        self._keys_state = 0
        self._field_cache: dict[str, Any] = {}
        self._evaluation_cache: dict[str, Any] = {}

    def bases(self) -> tuple[_View, ...]:
        if self._bases_cache is not None:
            return self._bases_cache
        if self._bases_state == 1:
            raise ConfigError("ブロック継承の循環参照です")

        self._bases_state = 1
        bases = list(self.ambient)

        if self.local is not None and self.local.inherit is not None:
            if self.container is None:
                raise ConfigError("ルートは継承できません")

            parent = self.world.lookup_object(
                self.container,
                self.local.inherit,
            )

            if self._related_to(parent):
                raise ConfigError(
                    "自分自身・祖先・子孫のブロックは継承できません"
                )

            bases.append(parent)

        self._bases_cache = tuple(bases)
        self._bases_state = 2
        return self._bases_cache

    def _related_to(self, other: _View) -> bool:
        current: _View | None = other
        while current is not None:
            if current is self:
                return True
            current = current.container

        current = self.container
        while current is not None:
            if current is other:
                return True
            current = current.container

        return False

    def keys(self) -> tuple[str, ...]:
        if self._keys_cache is not None:
            return self._keys_cache
        if self._keys_state == 1:
            raise ConfigError("ブロック継承の循環参照です")

        self._keys_state = 1
        ordered: dict[str, None] = {}

        for base in self.bases():
            for key in base.keys():
                ordered.setdefault(key, None)

        if self.local is not None:
            for key in self.local.fields:
                ordered.setdefault(key, None)

        self._keys_cache = tuple(ordered)
        self._keys_state = 2
        return self._keys_cache

    def has(self, key: str) -> bool:
        return key in self.keys()

    def get(self, key: str) -> Any:
        if key in self._field_cache:
            return self._field_cache[key]
        if not self.has(key):
            raise ConfigError(f"未定義のキーです: {key}")

        object_sources: list[_View] = []
        scalar: Any = _MISSING

        for base in self.bases():
            if not base.has(key):
                continue
            value = base.get(key)
            if isinstance(value, _View):
                if scalar is not _MISSING:
                    raise ConfigError("辞書と非辞書の型が衝突しています")
                object_sources.append(value)
            else:
                if object_sources:
                    raise ConfigError("辞書と非辞書の型が衝突しています")
                scalar = value

        local_value: Any = _MISSING
        if self.local is not None and key in self.local.fields:
            local_value = self.local.fields[key]

        if isinstance(local_value, _RawObject):
            if scalar is not _MISSING:
                raise ConfigError("辞書と非辞書の型が衝突しています")
            result: Any = _View(
                self.world,
                self,
                tuple(object_sources),
                local_value,
            )
        elif local_value is not _MISSING:
            if object_sources:
                raise ConfigError("辞書と非辞書の型が衝突しています")
            result = local_value
        elif object_sources:
            result = _View(
                self.world,
                self,
                tuple(object_sources),
                None,
            )
        elif scalar is not _MISSING:
            result = scalar
        else:
            raise ConfigError(f"未定義のキーです: {key}")

        self._field_cache[key] = result
        return result


class _World:
    def __init__(self, raw_root: _RawObject, env: dict[str, str]) -> None:
        self.env = env
        self.root = _View(self, None, (), raw_root)
        self._evaluating_fields: set[tuple[int, str]] = set()
        self._evaluating_objects: set[int] = set()

    def lookup(
        self,
        start: _View,
        path: tuple[str, ...],
    ) -> tuple[_View, str, Any]:
        head = path[0]
        scope: _View | None = start

        while scope is not None:
            if scope.has(head):
                owner = scope
                key = head
                value = owner.get(key)

                for component in path[1:]:
                    if not isinstance(value, _View):
                        raise ConfigError(
                            "非辞書値に対してパスをたどることはできません"
                        )
                    owner = value
                    key = component
                    if not owner.has(key):
                        raise ConfigError(
                            f"参照先のキーが存在しません: {component}"
                        )
                    value = owner.get(key)

                return owner, key, value

            scope = scope.container

        raise ConfigError(f"未定義参照です: {'.'.join(path)}")

    def lookup_object(
        self,
        start: _View,
        path: tuple[str, ...],
    ) -> _View:
        _, _, value = self.lookup(start, path)
        if not isinstance(value, _View):
            raise ConfigError("継承元は辞書である必要があります")
        return value

    def evaluate_reference(self, reference: _Reference, scope: _View) -> Any:
        if reference.kind == "env":
            assert reference.variable is not None
            variable = reference.variable
            if variable in self.env and self.env[variable] != "":
                return self.env[variable]
            if reference.has_default:
                return reference.default if reference.default is not None else ""
            raise ConfigError(f"環境変数が定義されていません: {variable}")

        assert reference.path is not None
        owner, key, value = self.lookup(scope, reference.path)
        if isinstance(value, _View):
            raise ConfigError("辞書を式の値として参照することはできません")
        return copy.deepcopy(self.evaluate_field(owner, key, value))

    def evaluate_field(self, owner: _View, key: str, expression: Any) -> Any:
        if key in owner._evaluation_cache:
            return owner._evaluation_cache[key]

        marker = (id(owner), key)
        if marker in self._evaluating_fields:
            raise ConfigError("変数参照の循環を検出しました")

        self._evaluating_fields.add(marker)
        try:
            value = self.evaluate_expression(expression, owner)
            owner._evaluation_cache[key] = value
            return value
        finally:
            self._evaluating_fields.discard(marker)

    def evaluate_expression(self, expression: Any, scope: _View) -> Any:
        if isinstance(expression, _Literal):
            return expression.value

        if isinstance(expression, _Reference):
            return self.evaluate_reference(expression, scope)

        if isinstance(expression, _String):
            pieces: list[str] = []
            for part in expression.parts:
                if isinstance(part, str):
                    pieces.append(part)
                    continue
                value = self.evaluate_reference(part, scope)
                if isinstance(value, (list, dict)):
                    raise ConfigError(
                        "リストまたは辞書を文字列に埋め込むことはできません"
                    )
                if value is None:
                    pieces.append("null")
                elif type(value) is bool:
                    pieces.append("true" if value else "false")
                elif type(value) in (str, int, float):
                    pieces.append(str(value))
                else:
                    raise ConfigError("文字列に埋め込めない値です")
            return "".join(pieces)

        if isinstance(expression, _ListExpr):
            return [
                self.evaluate_expression(item, scope)
                for item in expression.items
            ]

        if isinstance(expression, _Add):
            iterator = iter(expression.terms)
            result = self.evaluate_expression(next(iterator), scope)
            for term in iterator:
                right = self.evaluate_expression(term, scope)
                result = self._add(result, right)
            return result

        raise ConfigError("不正な式です")

    @staticmethod
    def _add(left: Any, right: Any) -> Any:
        if type(left) in (int, float) and type(right) in (int, float):
            return left + right
        if type(left) is str and type(right) is str:
            return left + right
        if type(left) is list and type(right) is list:
            return left + right
        raise ConfigError("'+' に使用できない型の組み合わせです")

    def evaluate_object(self, view: _View) -> dict[str, Any]:
        marker = id(view)
        if marker in self._evaluating_objects:
            raise ConfigError("ブロック構造の循環を検出しました")

        self._evaluating_objects.add(marker)
        try:
            result: dict[str, Any] = {}
            for key in view.keys():
                value = view.get(key)
                if isinstance(value, _View):
                    result[key] = self.evaluate_object(value)
                else:
                    result[key] = self.evaluate_field(view, key, value)
            return result
        finally:
            self._evaluating_objects.discard(marker)


def parse_config(
    text: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    environment = {} if env is None else dict(env)
    tokens = _Lexer(text).tokenize()
    raw_root = _Parser(tokens).parse()
    return _World(raw_root, environment).evaluate_object(
        _World(raw_root, environment).root
    )
=== END ===
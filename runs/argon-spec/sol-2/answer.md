=== FILE: config_parser.py ===
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*")
_PATH_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*"
)
_NUMBER_RE = re.compile(
    r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"
)
_ENV_NAME_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class _Ref:
    path: tuple[str, ...] | None = None
    env_name: str | None = None
    env_default: str | None = None
    has_default: bool = False


@dataclass(frozen=True)
class _Literal:
    value: Any


@dataclass(frozen=True)
class _String:
    parts: tuple[str | _Ref, ...]


@dataclass(frozen=True)
class _List:
    items: tuple[_Expr, ...]


_Term = _Literal | _String | _List | _Ref


@dataclass(frozen=True)
class _Expr:
    terms: tuple[_Term, ...]


@dataclass(frozen=True)
class _Token:
    kind: str
    value: Any
    line: int
    column: int


def _parse_reference(content: str, line: int, column: int) -> _Ref:
    if content.startswith("env:"):
        rest = content[4:]
        if ":-" in rest:
            name, default = rest.split(":-", 1)
            if _ENV_NAME_RE.fullmatch(name) is None:
                raise ConfigError(
                    f"invalid environment variable reference at "
                    f"line {line}, column {column}"
                )
            return _Ref(
                env_name=name,
                env_default=default,
                has_default=True,
            )

        if _ENV_NAME_RE.fullmatch(rest) is None:
            raise ConfigError(
                f"invalid environment variable reference at "
                f"line {line}, column {column}"
            )
        return _Ref(env_name=rest)

    if _PATH_RE.fullmatch(content) is None:
        raise ConfigError(
            f"invalid reference at line {line}, column {column}"
        )
    return _Ref(path=tuple(content.split(".")))


class _Lexer:
    _PUNCTUATION = {
        "=": "EQUAL",
        "{": "LBRACE",
        "}": "RBRACE",
        "[": "LBRACKET",
        "]": "RBRACKET",
        ",": "COMMA",
        ".": "DOT",
        ":": "COLON",
        ";": "SEMICOLON",
        "+": "PLUS",
        "-": "MINUS",
    }

    _ESCAPES = {
        '"': '"',
        "\\": "\\",
        "n": "\n",
        "t": "\t",
        "r": "\r",
        "$": "$",
    }

    def __init__(self, text: str) -> None:
        self.text = text
        self.length = len(text)
        self.index = 0
        self.line = 1
        self.column = 1
        self.tokens: list[_Token] = []

    def tokenize(self) -> list[_Token]:
        while self.index < self.length:
            ch = self.text[self.index]

            if ch in " \t":
                self._advance_char()
                continue

            if ch == "\n":
                self.tokens.append(
                    _Token("NEWLINE", None, self.line, self.column)
                )
                self._advance_newline()
                continue

            if ch == "\r":
                if self._peek_char(1) != "\n":
                    self._error("bare carriage return is not allowed")
                self.tokens.append(
                    _Token("NEWLINE", None, self.line, self.column)
                )
                self._advance_crlf()
                continue

            if ch == "#":
                self._skip_line_comment()
                continue

            if ch == "/" and self._peek_char(1) == "/":
                self._advance_char()
                self._advance_char()
                self._skip_line_comment()
                continue

            if ch == "/" and self._peek_char(1) == "*":
                self._skip_block_comment()
                continue

            if ch == '"':
                self.tokens.append(self._read_string())
                continue

            if ch == "$" and self._peek_char(1) == "{":
                self.tokens.append(self._read_reference())
                continue

            if "0" <= ch <= "9":
                self.tokens.append(self._read_number())
                continue

            if (
                "A" <= ch <= "Z"
                or "a" <= ch <= "z"
                or ch == "_"
            ):
                self.tokens.append(self._read_identifier())
                continue

            kind = self._PUNCTUATION.get(ch)
            if kind is not None:
                self.tokens.append(
                    _Token(kind, ch, self.line, self.column)
                )
                self._advance_char()
                continue

            self._error(f"unexpected character {ch!r}")

        self.tokens.append(_Token("EOF", None, self.line, self.column))
        return self.tokens

    def _peek_char(self, offset: int) -> str | None:
        index = self.index + offset
        if index >= self.length:
            return None
        return self.text[index]

    def _advance_char(self) -> None:
        self.index += 1
        self.column += 1

    def _advance_newline(self) -> None:
        self.index += 1
        self.line += 1
        self.column = 1

    def _advance_crlf(self) -> None:
        self.index += 2
        self.line += 1
        self.column = 1

    def _skip_line_comment(self) -> None:
        while self.index < self.length:
            if self.text[self.index] in "\r\n":
                return
            self._advance_char()

    def _skip_block_comment(self) -> None:
        start_line = self.line
        start_column = self.column
        self._advance_char()
        self._advance_char()

        while self.index < self.length:
            if (
                self.text[self.index] == "*"
                and self._peek_char(1) == "/"
            ):
                self._advance_char()
                self._advance_char()
                return

            if self.text[self.index] == "\n":
                self.tokens.append(
                    _Token("NEWLINE", None, self.line, self.column)
                )
                self._advance_newline()
            elif self.text[self.index] == "\r":
                if self._peek_char(1) != "\n":
                    self._error("bare carriage return is not allowed")
                self.tokens.append(
                    _Token("NEWLINE", None, self.line, self.column)
                )
                self._advance_crlf()
            else:
                self._advance_char()

        raise ConfigError(
            f"unterminated block comment at "
            f"line {start_line}, column {start_column}"
        )

    def _read_identifier(self) -> _Token:
        line = self.line
        column = self.column
        match = _IDENT_RE.match(self.text, self.index)
        if match is None:
            self._error("invalid identifier")

        value = match.group(0)
        for _ in value:
            self._advance_char()
        return _Token("IDENT", value, line, column)

    def _read_number(self) -> _Token:
        line = self.line
        column = self.column
        match = _NUMBER_RE.match(self.text, self.index)
        if match is None:
            self._error("invalid number")

        raw = match.group(0)
        next_index = match.end()
        if next_index < self.length:
            following = self.text[next_index]
            if (
                "A" <= following <= "Z"
                or "a" <= following <= "z"
                or "0" <= following <= "9"
                or following in "_.-"
            ):
                self._error("invalid number")

        for _ in raw:
            self._advance_char()

        try:
            value: int | float
            if "." in raw or "e" in raw or "E" in raw:
                value = float(raw)
            else:
                value = int(raw)
        except ValueError as exc:
            raise ConfigError(
                f"invalid number at line {line}, column {column}"
            ) from exc

        return _Token("NUMBER", value, line, column)

    def _read_reference(self) -> _Token:
        line = self.line
        column = self.column
        self._advance_char()
        self._advance_char()
        chars: list[str] = []

        while self.index < self.length:
            ch = self.text[self.index]
            if ch == "}":
                self._advance_char()
                ref = _parse_reference(
                    "".join(chars), line, column
                )
                return _Token("REF", ref, line, column)

            if ch == "\n":
                chars.append(ch)
                self._advance_newline()
            elif ch == "\r":
                if self._peek_char(1) != "\n":
                    self._error("bare carriage return is not allowed")
                chars.append("\n")
                self._advance_crlf()
            else:
                chars.append(ch)
                self._advance_char()

        raise ConfigError(
            f"unterminated reference at line {line}, column {column}"
        )

    def _read_string(self) -> _Token:
        line = self.line
        column = self.column
        self._advance_char()

        parts: list[str | _Ref] = []
        literal: list[str] = []

        def flush_literal() -> None:
            if literal:
                parts.append("".join(literal))
                literal.clear()

        while self.index < self.length:
            ch = self.text[self.index]

            if ch == '"':
                self._advance_char()
                flush_literal()
                return _Token(
                    "STRING",
                    _String(tuple(parts)),
                    line,
                    column,
                )

            if ch in "\r\n":
                raise ConfigError(
                    f"raw newline in string at "
                    f"line {self.line}, column {self.column}"
                )

            if ch == "\\":
                escape_line = self.line
                escape_column = self.column
                self._advance_char()
                if self.index >= self.length:
                    raise ConfigError(
                        f"unterminated string at "
                        f"line {line}, column {column}"
                    )
                escaped = self.text[self.index]
                replacement = self._ESCAPES.get(escaped)
                if replacement is None:
                    raise ConfigError(
                        f"invalid escape sequence at "
                        f"line {escape_line}, column {escape_column}"
                    )
                literal.append(replacement)
                self._advance_char()
                continue

            if ch == "$" and self._peek_char(1) == "{":
                flush_literal()
                ref_line = self.line
                ref_column = self.column
                self._advance_char()
                self._advance_char()
                content: list[str] = []

                while self.index < self.length:
                    inner = self.text[self.index]
                    if inner == "}":
                        self._advance_char()
                        parts.append(
                            _parse_reference(
                                "".join(content),
                                ref_line,
                                ref_column,
                            )
                        )
                        break

                    if inner in "\r\n":
                        raise ConfigError(
                            f"raw newline in string at "
                            f"line {self.line}, column {self.column}"
                        )

                    if inner == "\\":
                        escape_line = self.line
                        escape_column = self.column
                        self._advance_char()
                        if self.index >= self.length:
                            raise ConfigError(
                                f"unterminated interpolation at "
                                f"line {ref_line}, column {ref_column}"
                            )
                        escaped = self.text[self.index]
                        replacement = self._ESCAPES.get(escaped)
                        if replacement is None:
                            raise ConfigError(
                                f"invalid escape sequence at "
                                f"line {escape_line}, "
                                f"column {escape_column}"
                            )
                        content.append(replacement)
                        self._advance_char()
                    else:
                        content.append(inner)
                        self._advance_char()
                else:
                    raise ConfigError(
                        f"unterminated interpolation at "
                        f"line {ref_line}, column {ref_column}"
                    )
                continue

            literal.append(ch)
            self._advance_char()

        raise ConfigError(
            f"unterminated string at line {line}, column {column}"
        )

    def _error(self, message: str) -> None:
        raise ConfigError(
            f"{message} at line {self.line}, column {self.column}"
        )


@dataclass(eq=False)
class _SourceObject:
    parent: _SourceObject | None
    entries: dict[str, _SourceObject | _Expr] = field(
        default_factory=dict
    )
    inherited_from: tuple[str, ...] | None = None


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self.tokens = tokens
        self.index = 0
        self.root = _SourceObject(None)

    def parse(self) -> _SourceObject:
        self._parse_statements(self.root, stop_at_brace=False)
        self._expect("EOF")
        return self.root

    def _current(self) -> _Token:
        return self.tokens[self.index]

    def _accept(self, kind: str) -> _Token | None:
        token = self._current()
        if token.kind != kind:
            return None
        self.index += 1
        return token

    def _expect(self, kind: str) -> _Token:
        token = self._current()
        if token.kind != kind:
            raise ConfigError(
                f"expected {kind}, got {token.kind} at "
                f"line {token.line}, column {token.column}"
            )
        self.index += 1
        return token

    def _skip_separators(self) -> None:
        while self._current().kind in ("NEWLINE", "SEMICOLON"):
            self.index += 1

    def _skip_newlines(self) -> None:
        while self._current().kind == "NEWLINE":
            self.index += 1

    def _parse_statements(
        self,
        scope: _SourceObject,
        *,
        stop_at_brace: bool,
    ) -> None:
        self._skip_separators()

        while True:
            token = self._current()

            if token.kind == "EOF":
                if stop_at_brace:
                    raise ConfigError(
                        f"unterminated block before line "
                        f"{token.line}, column {token.column}"
                    )
                return

            if token.kind == "RBRACE":
                if not stop_at_brace:
                    raise ConfigError(
                        f"unexpected closing brace at "
                        f"line {token.line}, column {token.column}"
                    )
                self.index += 1
                return

            self._parse_statement(scope)

            token = self._current()
            if token.kind in ("NEWLINE", "SEMICOLON"):
                self._skip_separators()
            elif token.kind in ("EOF", "RBRACE"):
                continue
            else:
                raise ConfigError(
                    f"statements must be separated at "
                    f"line {token.line}, column {token.column}"
                )

    def _parse_path(self) -> tuple[str, ...]:
        parts = [self._expect("IDENT").value]
        while self._accept("DOT") is not None:
            parts.append(self._expect("IDENT").value)
        return tuple(parts)

    def _parse_statement(self, scope: _SourceObject) -> None:
        path = self._parse_path()

        if self._accept("EQUAL") is not None:
            expression = self._parse_expression()
            self._assign(scope, path, expression)
            return

        inherited_from: tuple[str, ...] | None = None
        if self._accept("COLON") is not None:
            inherited_from = self._parse_path()

        self._skip_newlines()
        self._expect("LBRACE")

        target = self._ensure_object(scope, path)
        if inherited_from is not None:
            if target.inherited_from is not None:
                token = self._current()
                raise ConfigError(
                    f"multiple inheritance declarations for "
                    f"{'.'.join(path)!r} near line "
                    f"{token.line}, column {token.column}"
                )
            target.inherited_from = inherited_from

        self._parse_statements(target, stop_at_brace=True)

    def _ensure_object(
        self,
        scope: _SourceObject,
        path: tuple[str, ...],
    ) -> _SourceObject:
        current = scope
        for part in path:
            existing = current.entries.get(part)
            if existing is None:
                child = _SourceObject(current)
                current.entries[part] = child
                current = child
            elif isinstance(existing, _SourceObject):
                current = existing
            else:
                raise ConfigError(
                    f"type conflict at {'.'.join(path)!r}"
                )
        return current

    def _assign(
        self,
        scope: _SourceObject,
        path: tuple[str, ...],
        expression: _Expr,
    ) -> None:
        current = scope
        for part in path[:-1]:
            existing = current.entries.get(part)
            if existing is None:
                child = _SourceObject(current)
                current.entries[part] = child
                current = child
            elif isinstance(existing, _SourceObject):
                current = existing
            else:
                raise ConfigError(
                    f"non-object used as path component in "
                    f"{'.'.join(path)!r}"
                )

        leaf = path[-1]
        if isinstance(current.entries.get(leaf), _SourceObject):
            raise ConfigError(
                f"cannot overwrite object {'.'.join(path)!r} "
                f"with a non-object value"
            )
        current.entries[leaf] = expression

    def _parse_expression(self) -> _Expr:
        terms = [self._parse_term()]

        while self._accept("PLUS") is not None:
            self._skip_newlines()
            terms.append(self._parse_term())

        return _Expr(tuple(terms))

    def _parse_term(self) -> _Term:
        token = self._current()

        if token.kind in ("PLUS", "MINUS"):
            sign = -1 if token.kind == "MINUS" else 1
            self.index += 1
            number = self._expect("NUMBER")
            return _Literal(sign * number.value)

        if token.kind == "NUMBER":
            self.index += 1
            return _Literal(token.value)

        if token.kind == "STRING":
            self.index += 1
            return token.value

        if token.kind == "REF":
            self.index += 1
            return token.value

        if token.kind == "IDENT":
            self.index += 1
            if token.value == "true":
                return _Literal(True)
            if token.value == "false":
                return _Literal(False)
            if token.value == "null":
                return _Literal(None)
            raise ConfigError(
                f"unexpected identifier {token.value!r} at "
                f"line {token.line}, column {token.column}"
            )

        if token.kind == "LBRACKET":
            return self._parse_list()

        raise ConfigError(
            f"expected expression term at "
            f"line {token.line}, column {token.column}"
        )

    def _parse_list(self) -> _List:
        self._expect("LBRACKET")
        self._skip_newlines()

        if self._accept("RBRACKET") is not None:
            return _List(())

        items: list[_Expr] = []
        while True:
            items.append(self._parse_expression())
            self._skip_newlines()

            if self._accept("COMMA") is not None:
                self._skip_newlines()
                if self._accept("RBRACKET") is not None:
                    return _List(tuple(items))
                continue

            self._expect("RBRACKET")
            return _List(tuple(items))


@dataclass(eq=False)
class _EffectiveObject:
    entries: dict[str, _EffectiveObject | _Expr] = field(
        default_factory=dict
    )
    origins: set[_SourceObject] = field(default_factory=set)
    parent: _EffectiveObject | None = None


@dataclass(frozen=True)
class _ObjectView:
    base: _EffectiveObject
    own: _SourceObject


_ObjectLike = _SourceObject | _EffectiveObject | _ObjectView


class _Resolver:
    def __init__(self, root: _SourceObject) -> None:
        self.root = root
        self._object_cache: dict[_SourceObject, _EffectiveObject] = {}
        self._object_state: set[_SourceObject] = set()
        self._base_cache: dict[
            _SourceObject, _EffectiveObject | None
        ] = {}
        self._base_state: set[_SourceObject] = set()

    def resolve(self) -> _EffectiveObject:
        return self._resolve_object(self.root)

    def _resolve_object(
        self,
        source: _SourceObject,
    ) -> _EffectiveObject:
        cached = self._object_cache.get(source)
        if cached is not None:
            return cached

        if source in self._object_state:
            raise ConfigError("cyclic block inheritance detected")

        self._object_state.add(source)
        try:
            base = self._resolve_base(source)
            if base is None:
                result = _EffectiveObject(origins={source})
            else:
                result = self._clone_object(base)
                result.origins.add(source)

            for key, own_value in source.entries.items():
                inherited_value = result.entries.get(key)

                if isinstance(own_value, _Expr):
                    if isinstance(inherited_value, _EffectiveObject):
                        raise ConfigError(
                            f"type conflict for inherited key {key!r}"
                        )
                    result.entries[key] = own_value
                    continue

                own_object = self._resolve_object(own_value)
                if inherited_value is None:
                    result.entries[key] = self._clone_object(own_object)
                elif isinstance(inherited_value, _Expr):
                    raise ConfigError(
                        f"type conflict for inherited key {key!r}"
                    )
                else:
                    result.entries[key] = self._merge_objects(
                        inherited_value,
                        own_object,
                    )

            self._set_parents(result, None)
            self._object_cache[source] = result
            return result
        finally:
            self._object_state.remove(source)

    def _resolve_base(
        self,
        source: _SourceObject,
    ) -> _EffectiveObject | None:
        if source in self._base_cache:
            return self._base_cache[source]

        if source.inherited_from is None:
            self._base_cache[source] = None
            return None

        if source in self._base_state:
            raise ConfigError("cyclic block inheritance detected")

        self._base_state.add(source)
        try:
            target = self._find_inheritance_target(source)
            if self._contains_related_origin(source, target):
                raise ConfigError(
                    "a block cannot inherit from itself, an ancestor, "
                    "or a descendant"
                )
            result = self._materialize(target)
            self._base_cache[source] = result
            return result
        finally:
            self._base_state.remove(source)

    def _find_inheritance_target(
        self,
        source: _SourceObject,
    ) -> _ObjectLike:
        assert source.inherited_from is not None
        path = source.inherited_from
        scope = source.parent

        while scope is not None:
            current = self._scope_value(scope, path[0])
            if current is None:
                scope = scope.parent
                continue

            for part in path[1:]:
                if isinstance(current, _Expr):
                    raise ConfigError(
                        f"non-object in inherited path "
                        f"{'.'.join(path)!r}"
                    )
                obj = self._materialize(current)
                next_value = obj.entries.get(part)
                if next_value is None:
                    raise ConfigError(
                        f"undefined inherited path "
                        f"{'.'.join(path)!r}"
                    )
                current = next_value

            if isinstance(current, _Expr):
                raise ConfigError(
                    f"inherited value {'.'.join(path)!r} "
                    f"is not an object"
                )
            return current

        raise ConfigError(
            f"undefined inherited block {'.'.join(path)!r}"
        )

    def _scope_value(
        self,
        scope: _SourceObject,
        key: str,
    ) -> _ObjectLike | _Expr | None:
        base = self._resolve_base(scope)
        inherited = None if base is None else base.entries.get(key)
        own = scope.entries.get(key)

        if own is None:
            return inherited
        if inherited is None:
            return own

        inherited_is_object = isinstance(
            inherited, _EffectiveObject
        )
        own_is_object = isinstance(own, _SourceObject)

        if inherited_is_object != own_is_object:
            raise ConfigError(
                f"type conflict for inherited key {key!r}"
            )

        if own_is_object:
            assert isinstance(inherited, _EffectiveObject)
            assert isinstance(own, _SourceObject)
            return _ObjectView(inherited, own)

        return own

    def _materialize(
        self,
        value: _ObjectLike,
    ) -> _EffectiveObject:
        if isinstance(value, _EffectiveObject):
            return value
        if isinstance(value, _SourceObject):
            return self._resolve_object(value)

        own = self._resolve_object(value.own)
        return self._merge_objects(value.base, own)

    def _contains_related_origin(
        self,
        source: _SourceObject,
        target: _ObjectLike,
    ) -> bool:
        if isinstance(target, _SourceObject):
            return self._related(source, target)

        if isinstance(target, _ObjectView):
            if self._related(source, target.own):
                return True
            return any(
                self._related(source, origin)
                for origin in target.base.origins
            )

        return any(
            self._related(source, origin)
            for origin in target.origins
        )

    @staticmethod
    def _related(
        left: _SourceObject,
        right: _SourceObject,
    ) -> bool:
        current: _SourceObject | None = left
        while current is not None:
            if current is right:
                return True
            current = current.parent

        current = right
        while current is not None:
            if current is left:
                return True
            current = current.parent

        return False

    def _clone_object(
        self,
        source: _EffectiveObject,
    ) -> _EffectiveObject:
        result = _EffectiveObject(origins=set(source.origins))
        for key, value in source.entries.items():
            if isinstance(value, _EffectiveObject):
                result.entries[key] = self._clone_object(value)
            else:
                result.entries[key] = value
        self._set_parents(result, None)
        return result

    def _merge_objects(
        self,
        base: _EffectiveObject,
        overlay: _EffectiveObject,
    ) -> _EffectiveObject:
        result = self._clone_object(base)
        result.origins.update(overlay.origins)

        for key, value in overlay.entries.items():
            existing = result.entries.get(key)

            if isinstance(value, _EffectiveObject):
                if existing is None:
                    result.entries[key] = self._clone_object(value)
                elif isinstance(existing, _Expr):
                    raise ConfigError(
                        f"type conflict for inherited key {key!r}"
                    )
                else:
                    result.entries[key] = self._merge_objects(
                        existing,
                        value,
                    )
            else:
                if isinstance(existing, _EffectiveObject):
                    raise ConfigError(
                        f"type conflict for inherited key {key!r}"
                    )
                result.entries[key] = value

        self._set_parents(result, None)
        return result

    def _set_parents(
        self,
        obj: _EffectiveObject,
        parent: _EffectiveObject | None,
    ) -> None:
        obj.parent = parent
        for value in obj.entries.values():
            if isinstance(value, _EffectiveObject):
                self._set_parents(value, obj)


class _Evaluator:
    def __init__(
        self,
        root: _EffectiveObject,
        env: dict[str, str],
    ) -> None:
        self.root = root
        self.env = env
        self.memo: dict[tuple[int, str], Any] = {}
        self.active: set[tuple[int, str]] = set()

    def evaluate(self) -> dict[str, Any]:
        return self._evaluate_object(self.root)

    def _evaluate_object(
        self,
        obj: _EffectiveObject,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in obj.entries.items():
            if isinstance(value, _EffectiveObject):
                result[key] = self._evaluate_object(value)
            else:
                result[key] = self._evaluate_entry(obj, key)
        return result

    def _evaluate_entry(
        self,
        owner: _EffectiveObject,
        key: str,
    ) -> Any:
        cache_key = (id(owner), key)
        if cache_key in self.memo:
            return self.memo[cache_key]
        if cache_key in self.active:
            raise ConfigError("cyclic variable reference detected")

        value = owner.entries.get(key)
        if value is None and key not in owner.entries:
            raise ConfigError(f"undefined key {key!r}")
        if isinstance(value, _EffectiveObject):
            raise ConfigError(
                f"object {key!r} cannot be used as a value"
            )

        self.active.add(cache_key)
        try:
            assert isinstance(value, _Expr)
            result = self._evaluate_expression(value, owner)
            self.memo[cache_key] = result
            return result
        finally:
            self.active.remove(cache_key)

    def _evaluate_expression(
        self,
        expression: _Expr,
        scope: _EffectiveObject,
    ) -> Any:
        result = self._evaluate_term(expression.terms[0], scope)

        for term in expression.terms[1:]:
            right = self._evaluate_term(term, scope)
            result = self._add(result, right)

        return result

    def _evaluate_term(
        self,
        term: _Term,
        scope: _EffectiveObject,
    ) -> Any:
        if isinstance(term, _Literal):
            return term.value

        if isinstance(term, _Ref):
            return self._evaluate_reference(term, scope)

        if isinstance(term, _String):
            pieces: list[str] = []
            for part in term.parts:
                if isinstance(part, str):
                    pieces.append(part)
                else:
                    value = self._evaluate_reference(part, scope)
                    pieces.append(self._interpolate(value))
            return "".join(pieces)

        if isinstance(term, _List):
            return [
                self._evaluate_expression(item, scope)
                for item in term.items
            ]

        raise ConfigError("invalid expression term")

    def _evaluate_reference(
        self,
        reference: _Ref,
        scope: _EffectiveObject,
    ) -> Any:
        if reference.env_name is not None:
            name = reference.env_name
            if name in self.env:
                value = self.env[name]
                if not isinstance(value, str):
                    raise ConfigError(
                        f"environment variable {name!r} is not a string"
                    )
                if value != "" or not reference.has_default:
                    return value

            if reference.has_default:
                assert reference.env_default is not None
                return reference.env_default

            raise ConfigError(
                f"undefined environment variable {name!r}"
            )

        assert reference.path is not None
        path = reference.path
        current_scope: _EffectiveObject | None = scope

        while current_scope is not None:
            if path[0] not in current_scope.entries:
                current_scope = current_scope.parent
                continue

            owner = current_scope
            current: _EffectiveObject | _Expr = (
                current_scope.entries[path[0]]
            )
            current_key = path[0]

            for part in path[1:]:
                if not isinstance(current, _EffectiveObject):
                    if isinstance(current, _Expr):
                        self._evaluate_entry(owner, current_key)
                    raise ConfigError(
                        f"non-object in reference "
                        f"{'.'.join(path)!r}"
                    )

                owner = current
                if part not in current.entries:
                    raise ConfigError(
                        f"undefined reference {'.'.join(path)!r}"
                    )
                current = current.entries[part]
                current_key = part

            if isinstance(current, _EffectiveObject):
                raise ConfigError(
                    f"object reference {'.'.join(path)!r} "
                    f"cannot be used as a value"
                )
            return self._evaluate_entry(owner, current_key)

        raise ConfigError(
            f"undefined reference {'.'.join(path)!r}"
        )

    @staticmethod
    def _interpolate(value: Any) -> str:
        if isinstance(value, str):
            return value
        if value is True:
            return "true"
        if value is False:
            return "false"
        if value is None:
            return "null"
        if type(value) in (int, float):
            return str(value)
        raise ConfigError(
            "lists and objects cannot be interpolated into strings"
        )

    @staticmethod
    def _add(left: Any, right: Any) -> Any:
        if type(left) in (int, float) and type(right) in (int, float):
            return left + right
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        if isinstance(left, list) and isinstance(right, list):
            return left + right
        raise ConfigError(
            f"invalid operands for +: "
            f"{type(left).__name__} and {type(right).__name__}"
        )


def parse_config(
    text: str,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not isinstance(text, str):
        raise ConfigError("configuration text must be a string")

    environment = {} if env is None else env
    if not isinstance(environment, dict):
        raise ConfigError("env must be a dictionary")

    tokens = _Lexer(text).tokenize()
    source_root = _Parser(tokens).parse()
    effective_root = _Resolver(source_root).resolve()
    return _Evaluator(effective_root, environment).evaluate()
=== END ===
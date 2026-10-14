=== FILE: config_parser.py ===
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


_IDENTIFIER = r"[A-Za-z_][A-Za-z0-9_-]*"
_IDENT_RE = re.compile(_IDENTIFIER)
_NUMBER_RE = re.compile(
    r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"
)
_PATH_RE = re.compile(
    rf"[ \t]*{_IDENTIFIER}(?:[ \t]*\.[ \t]*{_IDENTIFIER})*[ \t]*"
)
_ENV_RE = re.compile(
    r"[ \t]*env[ \t]*:[ \t]*([A-Za-z0-9_]+)"
    r"(?:[ \t]*:-([\s\S]*)|[ \t]*)"
)
_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "$": "$",
}
_MISSING = object()
_BUSY = object()


@dataclass(frozen=True, slots=True)
class _Expr:
    kind: str
    value: Any


@dataclass(frozen=True, slots=True)
class _Token:
    kind: str
    value: Any
    start: int
    end: int


@dataclass(slots=True)
class _Block:
    items: dict[str, Any] = field(default_factory=dict)
    inheritance: tuple[str, ...] | None = None


def _reference_expression(body: str) -> _Expr:
    if "${" in body:
        raise ConfigError("参照の入れ子は使用できません")

    match = _ENV_RE.fullmatch(body)
    if match is not None:
        return _Expr("env", (match.group(1), match.group(2)))

    if _PATH_RE.fullmatch(body) is None:
        raise ConfigError(f"不正な参照: ${{{body}}}")

    return _Expr("ref", tuple(part.strip(" \t") for part in body.split(".")))


class _Lexer:
    def __init__(self, text: str):
        self.text = text
        self.pos = 0

    def _error(self, message: str) -> None:
        raise ConfigError(f"{message} (位置 {self.pos})")

    def _escape(self) -> str:
        self.pos += 1
        if self.pos >= len(self.text):
            self._error("エスケープシーケンスが閉じられていません")
        char = self.text[self.pos]
        if char not in _ESCAPES:
            self._error(f"不正なエスケープシーケンス: \\{char}")
        self.pos += 1
        return _ESCAPES[char]

    def _reference(self, in_string: bool) -> _Expr:
        self.pos += 2
        chars: list[str] = []

        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == "}":
                self.pos += 1
                return _reference_expression("".join(chars))

            if in_string:
                if char in "\r\n":
                    self._error("文字列内に生の改行は使用できません")
                if char == '"':
                    self._error("文字列補間が閉じられていません")
                if char == "\\":
                    chars.append(self._escape())
                    continue

            chars.append(char)
            self.pos += 1

        self._error("参照が閉じられていません")

    def _string(self) -> _Expr:
        self.pos += 1
        parts: list[Any] = []
        chars: list[str] = []

        while self.pos < len(self.text):
            char = self.text[self.pos]
            if char == '"':
                self.pos += 1
                if chars:
                    parts.append("".join(chars))
                return _Expr("string", tuple(parts))

            if char in "\r\n":
                self._error("文字列内に生の改行は使用できません")

            if char == "\\":
                chars.append(self._escape())
                continue

            if self.text.startswith("${", self.pos):
                if chars:
                    parts.append("".join(chars))
                    chars.clear()
                parts.append(self._reference(in_string=True))
                continue

            chars.append(char)
            self.pos += 1

        self._error("文字列が閉じられていません")

    def tokenize(self) -> list[_Token]:
        result: list[_Token] = []
        text = self.text

        while self.pos < len(text):
            start = self.pos
            char = text[start]

            if char in " \t":
                self.pos += 1
                continue

            if char == "\n" or text.startswith("\r\n", start):
                self.pos += 2 if char == "\r" else 1
                result.append(_Token("NL", None, start, self.pos))
                continue

            if char == "#" or text.startswith("//", start):
                while self.pos < len(text) and text[self.pos] not in "\r\n":
                    self.pos += 1
                continue

            if text.startswith("/*", start):
                end = text.find("*/", start + 2)
                if end < 0:
                    self._error("ブロックコメントが閉じられていません")
                cursor = start + 2
                while True:
                    newline = text.find("\n", cursor, end)
                    if newline < 0:
                        break
                    result.append(_Token("NL", None, newline, newline + 1))
                    cursor = newline + 1
                self.pos = end + 2
                continue

            if char == '"':
                value = self._string()
                result.append(_Token("STRING", value, start, self.pos))
                continue

            if text.startswith("${", start):
                value = self._reference(in_string=False)
                result.append(_Token("REF", value, start, self.pos))
                continue

            match = _IDENT_RE.match(text, start)
            if match is not None:
                self.pos = match.end()
                result.append(
                    _Token("IDENT", match.group(), start, self.pos)
                )
                continue

            match = _NUMBER_RE.match(text, start)
            if match is not None:
                spelling = match.group()
                integer_part = re.split(r"[.eE]", spelling, maxsplit=1)[0]
                if len(integer_part) > 1 and integer_part.startswith("0"):
                    self._error("数値の整数部に先頭ゼロは使用できません")
                self.pos = match.end()
                result.append(
                    _Token("NUMBER", spelling, start, self.pos)
                )
                continue

            if char in "{}[]=.:;,+-":
                self.pos += 1
                result.append(_Token(char, char, start, self.pos))
                continue

            self._error(f"不正な文字: {char!r}")

        result.append(_Token("EOF", None, len(text), len(text)))
        return result


class _Parser:
    def __init__(self, tokens: list[_Token]):
        self.tokens = tokens
        self.pos = 0

    @property
    def current(self) -> _Token:
        return self.tokens[self.pos]

    def _error(self, message: str) -> None:
        raise ConfigError(f"{message} (位置 {self.current.start})")

    def _take(self, kind: str) -> _Token:
        token = self.current
        if token.kind != kind:
            self._error(f"{kind!r} が必要です")
        self.pos += 1
        return token

    def _newlines(self) -> None:
        while self.current.kind == "NL":
            self.pos += 1

    def _path(self) -> tuple[str, ...]:
        parts = [self._take("IDENT").value]
        while self.current.kind == ".":
            self.pos += 1
            parts.append(self._take("IDENT").value)
        return tuple(parts)

    @staticmethod
    def _block_at(block: _Block, path: tuple[str, ...]) -> _Block:
        for name in path:
            item = block.items.get(name, _MISSING)
            if item is _MISSING:
                item = _Block()
                block.items[name] = item
            elif not isinstance(item, _Block):
                raise ConfigError(f"辞書と非辞書の型が衝突しています: {name}")
            block = item
        return block

    def _assign(
        self, block: _Block, path: tuple[str, ...], expression: _Expr
    ) -> None:
        owner = self._block_at(block, path[:-1])
        name = path[-1]
        if isinstance(owner.items.get(name), _Block):
            raise ConfigError(f"辞書を非辞書で上書きできません: {name}")
        owner.items[name] = expression

    def _term(self) -> _Expr:
        token = self.current

        if token.kind in ("STRING", "REF"):
            self.pos += 1
            return token.value

        if token.kind in ("NUMBER", "+", "-"):
            sign = ""
            if token.kind in ("+", "-"):
                sign = token.kind
                self.pos += 1
                if (
                    self.current.kind != "NUMBER"
                    or self.current.start != token.end
                ):
                    self._error("数値の符号の直後には数字が必要です")
            spelling = sign + self._take("NUMBER").value
            try:
                if any(char in spelling for char in ".eE"):
                    value = float(spelling)
                else:
                    value = int(spelling)
            except (ValueError, OverflowError) as exc:
                raise ConfigError(f"不正な数値: {spelling}") from exc
            return _Expr("literal", value)

        if token.kind == "IDENT":
            literals = {"true": True, "false": False, "null": None}
            if token.value not in literals:
                self._error("値の識別子は ${...} で参照してください")
            self.pos += 1
            return _Expr("literal", literals[token.value])

        if token.kind == "[":
            self.pos += 1
            self._newlines()
            elements: list[_Expr] = []

            if self.current.kind == "]":
                self.pos += 1
                return _Expr("list", tuple(elements))

            while True:
                elements.append(self._expression())
                self._newlines()

                if self.current.kind == "]":
                    self.pos += 1
                    break

                self._take(",")
                self._newlines()
                if self.current.kind == "]":
                    self.pos += 1
                    break

            return _Expr("list", tuple(elements))

        self._error("式の項が必要です")

    def _expression(self) -> _Expr:
        terms = [self._term()]
        while self.current.kind == "+":
            self.pos += 1
            self._newlines()
            terms.append(self._term())
        if len(terms) == 1:
            return terms[0]
        return _Expr("add", tuple(terms))

    def _body(self, block: _Block, nested: bool) -> None:
        while True:
            while self.current.kind in ("NL", ";"):
                self.pos += 1

            if self.current.kind == "EOF":
                if nested:
                    self._error("ブロックが閉じられていません")
                return

            if self.current.kind == "}":
                if not nested:
                    self._error("対応する開き波括弧がありません")
                self.pos += 1
                return

            path = self._path()

            if self.current.kind == "=":
                self.pos += 1
                self._assign(block, path, self._expression())
            else:
                inheritance = None
                if self.current.kind == ":":
                    self.pos += 1
                    inheritance = self._path()

                self._newlines()
                self._take("{")
                target = self._block_at(block, path)

                if inheritance is not None:
                    if target.inheritance is not None:
                        self._error("同じブロックに複数の継承指定があります")
                    target.inheritance = inheritance

                self._body(target, nested=True)

            if self.current.kind not in ("NL", ";", "EOF", "}"):
                self._error("文の間には改行またはセミコロンが必要です")

    def parse(self) -> _Block:
        root = _Block()
        self._body(root, nested=False)
        return root


class _Object:
    """未評価の式を保持する、スコープ付きの辞書ビュー。"""

    def __init__(
        self,
        parent: _Object | None,
        name: str,
        local: _Block | None,
        sources: tuple[_Object, ...] = (),
    ):
        self.parent = parent
        self.name = name
        self.local = local
        self.sources = sources
        self.bases: tuple[_Object, ...] | None = None
        self.bases_busy = False
        self.members: dict[str, Any] = {}
        self.keys: tuple[str, ...] | None = None
        self.keys_busy = False
        self.structure_state = 0
        self.values: dict[str, Any] = {}


class _Evaluator:
    def __init__(self, block: _Block, env: dict[str, str]):
        self.root = _Object(None, "", block)
        self.env = env

    @staticmethod
    def _is_ancestor(ancestor: _Object, node: _Object) -> bool:
        current: _Object | None = node
        while current is not None:
            if current is ancestor:
                return True
            current = current.parent
        return False

    def _bases(self, node: _Object) -> tuple[_Object, ...]:
        if node.bases is not None:
            return node.bases
        if node.bases_busy:
            raise ConfigError("継承の循環参照があります")

        node.bases_busy = True
        try:
            bases: list[_Object] = []
            if node.local is not None and node.local.inheritance is not None:
                _, _, target = self._lookup(
                    node.parent, node.local.inheritance
                )
                if not isinstance(target, _Object):
                    raise ConfigError("継承元は辞書でなければなりません")
                if (
                    self._is_ancestor(target, node)
                    or self._is_ancestor(node, target)
                ):
                    raise ConfigError(
                        "自分自身・祖先・子孫ブロックは継承できません"
                    )
                bases.append(target)

            bases.extend(node.sources)
            node.bases = tuple(bases)
            return node.bases
        finally:
            node.bases_busy = False

    def _member(self, node: _Object, name: str) -> Any:
        if name in node.members:
            value = node.members[name]
            if value is _BUSY:
                raise ConfigError(f"継承の循環参照があります: {name}")
            return value

        node.members[name] = _BUSY
        try:
            candidates: list[Any] = []

            for base in self._bases(node):
                candidate = self._member(base, name)
                if candidate is not _MISSING:
                    candidates.append(candidate)

            if node.local is not None and name in node.local.items:
                candidates.append(node.local.items[name])

            if not candidates:
                value = _MISSING
            else:
                dictionary_flags = [
                    isinstance(candidate, (_Object, _Block))
                    for candidate in candidates
                ]
                if any(dictionary_flags) and not all(dictionary_flags):
                    raise ConfigError(
                        f"辞書と非辞書の型が衝突しています: {name}"
                    )

                if dictionary_flags[0]:
                    local = None
                    sources: list[_Object] = []
                    for candidate in candidates:
                        if isinstance(candidate, _Block):
                            local = candidate
                        else:
                            sources.append(candidate)
                    value = _Object(node, name, local, tuple(sources))
                else:
                    value = candidates[-1]

            node.members[name] = value
            return value
        except Exception:
            node.members.pop(name, None)
            raise

    def _keys(self, node: _Object) -> tuple[str, ...]:
        if node.keys is not None:
            return node.keys
        if node.keys_busy:
            raise ConfigError("継承の循環参照があります")

        node.keys_busy = True
        try:
            names: dict[str, None] = {}
            for base in self._bases(node):
                for name in self._keys(base):
                    names[name] = None
            if node.local is not None:
                for name in node.local.items:
                    names[name] = None

            node.keys = tuple(names)
            return node.keys
        finally:
            node.keys_busy = False

    def _lookup(
        self, scope: _Object | None, path: tuple[str, ...]
    ) -> tuple[_Object, str, Any]:
        current = scope
        head = path[0]

        while current is not None:
            value = self._member(current, head)
            if value is not _MISSING:
                owner = current
                name = head
                break
            current = current.parent
        else:
            raise ConfigError(f"未定義参照: {'.'.join(path)}")

        for name in path[1:]:
            if not isinstance(value, _Object):
                raise ConfigError(
                    f"辞書以外の値の内部は参照できません: {'.'.join(path)}"
                )
            owner = value
            value = self._member(owner, name)
            if value is _MISSING:
                raise ConfigError(f"未定義参照: {'.'.join(path)}")

        return owner, name, value

    def _resolve_structure(self, node: _Object) -> None:
        if node.structure_state == 2:
            return
        if node.structure_state == 1:
            raise ConfigError("ブロック継承の循環参照があります")

        node.structure_state = 1

        # コピー元の構造を先に検証する。式はコピー先で後から評価する。
        for base in self._bases(node):
            self._resolve_structure(base)

        for name in self._keys(node):
            value = self._member(node, name)
            if isinstance(value, _Object):
                self._resolve_structure(value)

        node.structure_state = 2

    @staticmethod
    def _stringify(value: Any) -> str:
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
        raise ConfigError("リストや辞書を文字列に補間することはできません")

    @staticmethod
    def _add(left: Any, right: Any) -> Any:
        numeric = (int, float)
        if type(left) in numeric and type(right) in numeric:
            try:
                return left + right
            except (OverflowError, ValueError) as exc:
                raise ConfigError("数値の加算に失敗しました") from exc

        if isinstance(left, str) and isinstance(right, str):
            return left + right

        if isinstance(left, list) and isinstance(right, list):
            return left + right

        raise ConfigError(
            f"+ で結合できない型です: "
            f"{type(left).__name__}, {type(right).__name__}"
        )

    def _expression(self, expression: _Expr, scope: _Object) -> Any:
        kind = expression.kind
        value = expression.value

        if kind == "literal":
            return value

        if kind == "env":
            name, default = value
            if name not in self.env:
                if default is not None:
                    return default
                raise ConfigError(f"未定義の環境変数: {name}")

            result = self.env[name]
            if not isinstance(result, str):
                raise ConfigError(f"環境変数の値は文字列が必要です: {name}")

            if default is not None and result == "":
                return default
            return result

        if kind == "ref":
            owner, name, target = self._lookup(scope, value)
            if isinstance(target, _Object):
                raise ConfigError(
                    f"辞書を値として参照することはできません: {'.'.join(value)}"
                )
            return self._value(owner, name)

        if kind == "string":
            parts: list[str] = []
            for part in value:
                if isinstance(part, str):
                    parts.append(part)
                else:
                    parts.append(
                        self._stringify(self._expression(part, scope))
                    )
            return "".join(parts)

        if kind == "list":
            return [self._expression(element, scope) for element in value]

        if kind == "add":
            result = self._expression(value[0], scope)
            for term in value[1:]:
                result = self._add(result, self._expression(term, scope))
            return result

        raise ConfigError(f"不明な式: {kind}")

    def _value(self, scope: _Object, name: str) -> Any:
        if name in scope.values:
            value = scope.values[name]
            if value is _BUSY:
                raise ConfigError(f"変数の循環参照があります: {name}")
            return value

        expression = self._member(scope, name)
        if not isinstance(expression, _Expr):
            raise ConfigError(f"値として評価できません: {name}")

        scope.values[name] = _BUSY
        try:
            value = self._expression(expression, scope)
            scope.values[name] = value
            return value
        except Exception:
            scope.values.pop(name, None)
            raise

    def _render(self, node: _Object) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name in self._keys(node):
            member = self._member(node, name)
            if isinstance(member, _Object):
                result[name] = self._render(member)
            else:
                result[name] = self._value(node, name)
        return result

    def evaluate(self) -> dict[str, Any]:
        self._resolve_structure(self.root)
        return self._render(self.root)


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    """
    HCL Lite の文字列を解析・評価し、辞書を返す。
    env が省略された場合は空辞書を使用し、os.environ は参照しない。
    """
    if not isinstance(text, str):
        raise ConfigError("text は文字列でなければなりません")

    try:
        tokens = _Lexer(text).tokenize()
        block = _Parser(tokens).parse()
        return _Evaluator(block, {} if env is None else env).evaluate()
    except RecursionError as exc:
        raise ConfigError(
            "設定のネストが深すぎるか、循環参照があります"
        ) from exc
=== END ===
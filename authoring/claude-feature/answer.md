=== FILE: meta.json ===
{"title": "INI設定ライブラリに値の展開（インターポレーション）を追加", "category": "feature", "answer": ["iniconf.py"]}
=== FILE: prompt.md ===
# 設定ファイルライブラリに「値の展開」を追加する

添付の `iniconf.py` は INI 形式の設定ファイルを読み書きする小さなライブラリで、現在の機能は正しく動いています。これに、値の中から他の設定値を参照して埋め込む「展開（インターポレーション）」の機能を追加してください。

既存の機能（書式の解釈、`ConfigError` と行番号、DEFAULT セクションによる既定値、`sections` / `has_section` / `keys` / `get` / `getint` / `getbool` / `items` / `set` / `dump` の挙動、見つからないときの `KeyError` など）は、この文書で変更すると書いた点以外はそのまま保ってください。

## 追加・変更する公開要素

- 例外 `InterpolationError`：`iniconf` モジュールに定義する `ConfigError` のサブクラス。この例外の `lineno` は `None`。
- `Config(interpolation=True)`：展開を行うかどうかを指定する。`False` のときは展開を一切行わず、すべての取り出しが現在と同じく生の値を返す。
- `parse(text, *, interpolation=True)`：作る `Config` に同じ指定を渡す。
- `get(section, key, default=（省略可）, *, raw=False)`：`raw=True` なら展開せず生の値を返す。
- `items(section, *, raw=False)`：各値を `get(section, key, raw=raw)` と同じ規則で返す。

## 展開の規則

値を先頭から順に読み、次のように変換した文字列を結果とします。

- `$$` は `$` 1文字になる。
- `${参照}` は参照先の値（それ自体も展開したもの）に置き換わる。参照は `${` の直後から、その後で最初に現れる `}` の手前まで。`}` が見つからなければ `InterpolationError`。
- 上の2つに当たらない `$`（直後が `$` でも `{` でもない、または値の末尾にある `$`）はそのまま `$` として残る。
- `$` 以外の文字はそのまま残る。
- 参照先から得た文字列は結果にそのまま入り、改めて展開されることはない。

### 参照の解決

- 参照に `:` が含まれていれば最初の `:` で分け、前をセクション名、後ろをキーとする。含まれていなければ参照全体がキーで、セクションは後述の「文脈セクション」とする。
- セクション名とキーの前後の空白は取り除かない。セクション名は大文字小文字を区別し、キーは区別しない（`get` と同じ）。セクション名またはキーが空文字列なら `InterpolationError`。
- 値の探し方は `get` と同じ（そのセクションに無ければ DEFAULT の値を使う）。セクションが存在しない場合やキーが見つからない場合は `InterpolationError`。セクション名に `DEFAULT` と書けば DEFAULT セクションを直接参照できる。

### 文脈セクション

- `get(S, k)` などで取り出した値を展開するときの文脈は `S`。その値が DEFAULT から借りたものであっても文脈は `S`。
- `${T:k}` で得た値を展開するときの文脈は `T`（その値が DEFAULT から借りたものであっても `T`）。
- `${k}` で得た値を展開するときの文脈は、今の文脈のまま。

例：
```
[DEFAULT]
url = http://${host}/

[web]
host = w.local

[app]
host = a.local
target = ${web:url}
```
`get("web", "url")` は `http://w.local/`、`get("app", "url")` は `http://a.local/`、`get("app", "target")` は `http://w.local/`。`get("DEFAULT", "url")` は DEFAULT に `host` が無いので `InterpolationError`。

### 循環

展開中の値は「(文脈セクション, 小文字にそろえたキー)」の組で区別します。`get(S, k)` は組 `(S, k)` の展開から始まり、`${...}` の参照を解決するたびに、参照先の組（`${T:k}` なら `(T, k)`、`${k}` なら `(今の文脈, k)`）の展開に入ります。ある組を展開している途中で（入れ子の中で）同じ組の展開がもう一度必要になったら `InterpolationError` です。

- `a = ${b}${b}` のように、入れ子でなく同じ参照を何度使うのは循環ではない。
- `(S, k)` と `(DEFAULT, k)` は別の組。たとえばセクション `S` の `path = ${DEFAULT:path}/local` は、DEFAULT の `path` が `/usr` なら `/usr/local` になる。一方 `S` の `path = ${path}/bin` は循環。

## 展開が行われる場面

- `get`（`raw=False` のとき）、`items`（`raw=False` のとき）、`getint`、`getbool` は展開後の値を使う。`getint` / `getbool` は展開後の値を変換する。
- キーが見つからず `default` を返すとき、`default` は展開せずそのまま返す。キーが見つかって展開に失敗した場合は、`default` が与えられていても `InterpolationError` を送出する。セクションやキーが見つからないときの `KeyError` は従来どおり。
- 展開は値を取り出すたびにその時点の内容で行う。`parse` と `set` は値を生のまま保存し、参照先が無い・循環しているといった問題があっても `parse` や `set` はエラーにしない。`dump` は生の値を書き出す。
- `sections` / `has_section` / `keys` の挙動は変わらない。
=== FILE: given/iniconf.py ===
"""INI 形式の設定ファイルを読み書きする小さなライブラリ。

書式:
  - 空行と、前後の空白を除いて '#' または ';' で始まる行はコメントとして無視する。
  - 空白またはタブで始まる行（コメント・空行を除く）は続き行。前後の空白を除いた内容を
    "\\n" でつないで直前の設定項目の値に追加する。直前の行が設定項目または続き行で
    なければエラー（空行・コメント行・セクション見出しを挟むと続けられない）。
  - "[名前]" の行はセクション見出し。名前は前後の空白を除いたもので、大文字小文字を
    区別する。同じ見出しが再び現れた場合は既存のセクションに追記する。
  - "キー = 値" の行は設定項目。最初の '=' で分割し、キーと値はそれぞれ前後の空白を除く。
    キーは小文字にそろえて保持する。同じセクション内でキーが重複するとエラー。
  - セクション "DEFAULT" は特別扱いで、他のセクションに無いキーの既定値になる。
    sections() には含めない。
  - 行末の "\\r" は無視する。
"""

DEFAULT_SECTION = "DEFAULT"

_TRUE = {"1", "yes", "true", "on"}
_FALSE = {"0", "no", "false", "off"}

_MISSING = object()


class ConfigError(Exception):
    """書式の誤り。lineno は 1 始まりの行番号（行に結び付かない場合は None）。"""

    def __init__(self, message, lineno=None):
        if lineno is not None:
            message = f"line {lineno}: {message}"
        super().__init__(message)
        self.lineno = lineno


class Config:
    def __init__(self):
        self._sections = {DEFAULT_SECTION: {}}
        self._order = []

    # --- セクション ---

    def sections(self):
        """DEFAULT 以外のセクション名を、最初に現れた順で返す。"""
        return list(self._order)

    def has_section(self, section):
        return section != DEFAULT_SECTION and section in self._sections

    def _add_section(self, section):
        if section not in self._sections:
            self._sections[section] = {}
            self._order.append(section)
        return self._sections[section]

    def _section(self, section):
        try:
            return self._sections[section]
        except KeyError:
            raise KeyError(section) from None

    # --- 参照 ---

    def keys(self, section):
        """セクション自身のキー（定義順）に続けて、DEFAULT にだけあるキー（定義順）を返す。"""
        own = self._section(section)
        result = list(own)
        if section != DEFAULT_SECTION:
            defaults = self._sections[DEFAULT_SECTION]
            result.extend(k for k in defaults if k not in own)
        return result

    def _lookup(self, section, key):
        """生の値を返す。セクションまたはキーが無ければ KeyError。"""
        own = self._section(section)
        key = key.lower()
        if key in own:
            return own[key]
        defaults = self._sections[DEFAULT_SECTION]
        if key in defaults:
            return defaults[key]
        raise KeyError(key)

    def get(self, section, key, default=_MISSING):
        try:
            return self._lookup(section, key)
        except KeyError:
            if default is _MISSING:
                raise
            return default

    def getint(self, section, key, default=_MISSING):
        try:
            value = self._lookup(section, key)
        except KeyError:
            if default is _MISSING:
                raise
            return default
        return int(value)

    def getbool(self, section, key, default=_MISSING):
        try:
            value = self._lookup(section, key)
        except KeyError:
            if default is _MISSING:
                raise
            return default
        lowered = value.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ValueError(f"not a boolean: {value!r}")

    def items(self, section):
        return [(key, self.get(section, key)) for key in self.keys(section)]

    # --- 更新・出力 ---

    def set(self, section, key, value):
        if not isinstance(value, str):
            raise TypeError("value must be a str")
        if section == DEFAULT_SECTION:
            target = self._sections[DEFAULT_SECTION]
        else:
            target = self._add_section(section)
        target[key.lower()] = value

    def dump(self):
        """parse() で読み戻せるテキストを返す。DEFAULT は中身があるときだけ先頭に書く。"""
        names = list(self._order)
        if self._sections[DEFAULT_SECTION]:
            names.insert(0, DEFAULT_SECTION)
        blocks = []
        for name in names:
            lines = [f"[{name}]"]
            for key, value in self._sections[name].items():
                first, *rest = value.split("\n")
                lines.append(f"{key} = {first}".rstrip())
                lines.extend(f"    {part}" for part in rest)
            blocks.append("\n".join(lines))
        if not blocks:
            return ""
        return "\n\n".join(blocks) + "\n"


def parse(text):
    config = Config()
    current = None
    last_key = None
    for lineno, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\r")
        stripped = line.strip()
        if not stripped or stripped[0] in "#;":
            last_key = None
            continue
        if line[0] in " \t":
            if last_key is None:
                raise ConfigError("continuation line without a key", lineno)
            section = config._sections[current]
            section[last_key] += "\n" + stripped
            continue
        last_key = None
        if stripped.startswith("["):
            if not stripped.endswith("]"):
                raise ConfigError("unterminated section header", lineno)
            name = stripped[1:-1].strip()
            if not name:
                raise ConfigError("empty section name", lineno)
            if name != DEFAULT_SECTION:
                config._add_section(name)
            current = name
            continue
        if "=" not in stripped:
            raise ConfigError("expected 'key = value'", lineno)
        if current is None:
            raise ConfigError("key outside of any section", lineno)
        key, _, value = stripped.partition("=")
        key = key.strip().lower()
        if not key:
            raise ConfigError("empty key", lineno)
        section = config._sections[current]
        if key in section:
            raise ConfigError(f"duplicate key {key!r}", lineno)
        section[key] = value.strip()
        last_key = key
    return config
=== FILE: ref/iniconf.py ===
"""INI 形式の設定ファイルを読み書きする小さなライブラリ。

書式:
  - 空行と、前後の空白を除いて '#' または ';' で始まる行はコメントとして無視する。
  - 空白またはタブで始まる行（コメント・空行を除く）は続き行。前後の空白を除いた内容を
    "\\n" でつないで直前の設定項目の値に追加する。直前の行が設定項目または続き行で
    なければエラー（空行・コメント行・セクション見出しを挟むと続けられない）。
  - "[名前]" の行はセクション見出し。名前は前後の空白を除いたもので、大文字小文字を
    区別する。同じ見出しが再び現れた場合は既存のセクションに追記する。
  - "キー = 値" の行は設定項目。最初の '=' で分割し、キーと値はそれぞれ前後の空白を除く。
    キーは小文字にそろえて保持する。同じセクション内でキーが重複するとエラー。
  - セクション "DEFAULT" は特別扱いで、他のセクションに無いキーの既定値になる。
    sections() には含めない。
  - 行末の "\\r" は無視する。

値の展開（interpolation=True のとき、値を取り出すたびに行う）:
  - "$$" は "$"、"${キー}" は文脈セクションの値、"${セクション:キー}" は指定セクションの値。
  - それ以外の "$" はそのまま。展開して得た文字列は再び展開しない。
  - 文脈セクションは get() で指定したセクション。"${T:k}" で得た値の文脈は T。
  - (文脈セクション, キー) の展開が入れ子で再び必要になったら循環としてエラー。
"""

DEFAULT_SECTION = "DEFAULT"

_TRUE = {"1", "yes", "true", "on"}
_FALSE = {"0", "no", "false", "off"}

_MISSING = object()


class ConfigError(Exception):
    """書式の誤り。lineno は 1 始まりの行番号（行に結び付かない場合は None）。"""

    def __init__(self, message, lineno=None):
        if lineno is not None:
            message = f"line {lineno}: {message}"
        super().__init__(message)
        self.lineno = lineno


class InterpolationError(ConfigError):
    """値の展開の失敗（参照先が無い、循環している、書式が誤っている）。"""


class Config:
    def __init__(self, interpolation=True):
        self._sections = {DEFAULT_SECTION: {}}
        self._order = []
        self._interpolation = interpolation

    # --- セクション ---

    def sections(self):
        """DEFAULT 以外のセクション名を、最初に現れた順で返す。"""
        return list(self._order)

    def has_section(self, section):
        return section != DEFAULT_SECTION and section in self._sections

    def _add_section(self, section):
        if section not in self._sections:
            self._sections[section] = {}
            self._order.append(section)
        return self._sections[section]

    def _section(self, section):
        try:
            return self._sections[section]
        except KeyError:
            raise KeyError(section) from None

    # --- 参照 ---

    def keys(self, section):
        """セクション自身のキー（定義順）に続けて、DEFAULT にだけあるキー（定義順）を返す。"""
        own = self._section(section)
        result = list(own)
        if section != DEFAULT_SECTION:
            defaults = self._sections[DEFAULT_SECTION]
            result.extend(k for k in defaults if k not in own)
        return result

    def _lookup(self, section, key):
        """生の値を返す。セクションまたはキーが無ければ KeyError。"""
        own = self._section(section)
        key = key.lower()
        if key in own:
            return own[key]
        defaults = self._sections[DEFAULT_SECTION]
        if key in defaults:
            return defaults[key]
        raise KeyError(key)

    def _value(self, section, key, raw=False):
        """値を返す（必要なら展開する）。セクションまたはキーが無ければ KeyError。"""
        value = self._lookup(section, key)
        if raw or not self._interpolation:
            return value
        return self._expand(section, value, ((section, key.lower()),))

    def _expand(self, context, value, chain):
        out = []
        i = 0
        while i < len(value):
            ch = value[i]
            nxt = value[i + 1:i + 2]
            if ch != "$":
                out.append(ch)
                i += 1
            elif nxt == "$":
                out.append("$")
                i += 2
            elif nxt == "{":
                end = value.find("}", i + 2)
                if end < 0:
                    raise InterpolationError(f"unterminated reference in {value!r}")
                out.append(self._resolve(context, value[i + 2:end], chain))
                i = end + 1
            else:
                out.append("$")
                i += 1
        return "".join(out)

    def _resolve(self, context, ref, chain):
        if ":" in ref:
            section, _, key = ref.partition(":")
        else:
            section, key = context, ref
        if not section or not key:
            raise InterpolationError(f"invalid reference {ref!r}")
        node = (section, key.lower())
        if node in chain:
            raise InterpolationError(f"circular reference {ref!r}")
        try:
            value = self._lookup(section, key)
        except KeyError:
            raise InterpolationError(f"unknown reference {ref!r}") from None
        return self._expand(section, value, chain + (node,))

    def get(self, section, key, default=_MISSING, *, raw=False):
        try:
            return self._value(section, key, raw)
        except KeyError:
            if default is _MISSING:
                raise
            return default

    def getint(self, section, key, default=_MISSING):
        try:
            value = self._value(section, key)
        except KeyError:
            if default is _MISSING:
                raise
            return default
        return int(value)

    def getbool(self, section, key, default=_MISSING):
        try:
            value = self._value(section, key)
        except KeyError:
            if default is _MISSING:
                raise
            return default
        lowered = value.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ValueError(f"not a boolean: {value!r}")

    def items(self, section, *, raw=False):
        return [(key, self.get(section, key, raw=raw)) for key in self.keys(section)]

    # --- 更新・出力 ---

    def set(self, section, key, value):
        if not isinstance(value, str):
            raise TypeError("value must be a str")
        if section == DEFAULT_SECTION:
            target = self._sections[DEFAULT_SECTION]
        else:
            target = self._add_section(section)
        target[key.lower()] = value

    def dump(self):
        """parse() で読み戻せるテキストを返す。DEFAULT は中身があるときだけ先頭に書く。"""
        names = list(self._order)
        if self._sections[DEFAULT_SECTION]:
            names.insert(0, DEFAULT_SECTION)
        blocks = []
        for name in names:
            lines = [f"[{name}]"]
            for key, value in self._sections[name].items():
                first, *rest = value.split("\n")
                lines.append(f"{key} = {first}".rstrip())
                lines.extend(f"    {part}" for part in rest)
            blocks.append("\n".join(lines))
        if not blocks:
            return ""
        return "\n\n".join(blocks) + "\n"


def parse(text, *, interpolation=True):
    config = Config(interpolation)
    current = None
    last_key = None
    for lineno, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\r")
        stripped = line.strip()
        if not stripped or stripped[0] in "#;":
            last_key = None
            continue
        if line[0] in " \t":
            if last_key is None:
                raise ConfigError("continuation line without a key", lineno)
            section = config._sections[current]
            section[last_key] += "\n" + stripped
            continue
        last_key = None
        if stripped.startswith("["):
            if not stripped.endswith("]"):
                raise ConfigError("unterminated section header", lineno)
            name = stripped[1:-1].strip()
            if not name:
                raise ConfigError("empty section name", lineno)
            if name != DEFAULT_SECTION:
                config._add_section(name)
            current = name
            continue
        if "=" not in stripped:
            raise ConfigError("expected 'key = value'", lineno)
        if current is None:
            raise ConfigError("key outside of any section", lineno)
        key, _, value = stripped.partition("=")
        key = key.strip().lower()
        if not key:
            raise ConfigError("empty key", lineno)
        section = config._sections[current]
        if key in section:
            raise ConfigError(f"duplicate key {key!r}", lineno)
        section[key] = value.strip()
        last_key = key
    return config
=== FILE: tests/test_hidden.py ===
import unittest

import iniconf
from iniconf import Config, ConfigError, parse


BASIC = """\
# 全体の設定
[DEFAULT]
timeout = 30
debug = no

[server]
Host = example.local
port = 8080
; コメント
debug = Yes

[paths]
search = /usr/lib
    /opt/lib
\t/srv/lib
"""


class ExistingBehaviorTest(unittest.TestCase):
    def test_basic_get_and_case_insensitive_keys(self):
        c = parse(BASIC)
        self.assertEqual(c.get("server", "host"), "example.local")
        self.assertEqual(c.get("server", "HOST"), "example.local")
        self.assertEqual(c.getint("server", "port"), 8080)
        self.assertIs(c.getbool("server", "debug"), True)
        self.assertIs(c.getbool("paths", "debug"), False)
        self.assertEqual(c.get("paths", "timeout"), "30")
        self.assertEqual(c.get("paths", "search"), "/usr/lib\n/opt/lib\n/srv/lib")

    def test_sections_and_keys_order(self):
        c = parse(BASIC)
        self.assertEqual(c.sections(), ["server", "paths"])
        self.assertTrue(c.has_section("server"))
        self.assertFalse(c.has_section("DEFAULT"))
        self.assertFalse(c.has_section("Server"))
        self.assertEqual(c.keys("server"), ["host", "port", "debug", "timeout"])
        self.assertEqual(c.keys("DEFAULT"), ["timeout", "debug"])
        self.assertEqual(
            c.items("paths"),
            [("search", "/usr/lib\n/opt/lib\n/srv/lib"), ("timeout", "30"), ("debug", "no")],
        )

    def test_missing_and_default(self):
        c = parse(BASIC)
        with self.assertRaises(KeyError):
            c.get("server", "nothing")
        with self.assertRaises(KeyError):
            c.get("nosuch", "host")
        self.assertEqual(c.get("server", "nothing", "x"), "x")
        self.assertIsNone(c.get("nosuch", "host", None))
        self.assertEqual(c.getint("server", "nothing", 7), 7)
        self.assertEqual(c.getbool("server", "nothing", "keep"), "keep")
        with self.assertRaises(ValueError):
            c.getbool("server", "host")

    def test_parse_errors_with_line_numbers(self):
        cases = [
            ("a = 1\n", 1),
            ("[s]\na = 1\n\n  b\n", 4),
            ("[s]\na = 1\n# c\n  b\n", 4),
            ("[s]\na = 1\n[t]\nb = 2\n[s]\nA = 3\n", 6),
            ("[s]\njust text\n", 2),
            ("[s]\n[ ]\n", 2),
            ("[s\n", 1),
            ("[s]\n = 1\n", 2),
        ]
        for text, lineno in cases:
            with self.subTest(text=text):
                with self.assertRaises(ConfigError) as cm:
                    parse(text)
                self.assertEqual(cm.exception.lineno, lineno)

    def test_repeated_section_merges_and_crlf(self):
        c = parse("[a]\r\nx = 1\r\n[b]\r\ny = 2\r\n[a]\r\nz = 3\r\n")
        self.assertEqual(c.sections(), ["a", "b"])
        self.assertEqual(c.keys("a"), ["x", "z"])
        self.assertEqual(c.get("a", "z"), "3")

    def test_set_and_dump(self):
        c = parse(BASIC)
        c.set("new", "Key", "v")
        c.set("DEFAULT", "extra", "e")
        self.assertEqual(c.sections(), ["server", "paths", "new"])
        self.assertEqual(c.get("new", "key"), "v")
        expected = (
            "[DEFAULT]\ntimeout = 30\ndebug = no\nextra = e\n\n"
            "[server]\nhost = example.local\nport = 8080\ndebug = Yes\n\n"
            "[paths]\nsearch = /usr/lib\n    /opt/lib\n    /srv/lib\n\n"
            "[new]\nkey = v\n"
        )
        self.assertEqual(c.dump(), expected)
        again = parse(c.dump())
        self.assertEqual(again.dump(), expected)
        self.assertEqual(Config().dump(), "")
        with self.assertRaises(TypeError):
            c.set("new", "n", 5)


class InterpolationTest(unittest.TestCase):
    def test_same_section_and_other_section(self):
        c = parse(
            "[base]\nroot = /srv\n\n"
            "[app]\nname = shop\nDir = ${base:root}/${name}\nlog = ${dir}/log\n"
        )
        self.assertEqual(c.get("app", "dir"), "/srv/shop")
        self.assertEqual(c.get("app", "log"), "/srv/shop/log")

    def test_dollar_rules(self):
        c = parse(
            "[s]\n"
            "a = 1\n"
            "price = 5$\n"
            "plain = $x and $ y\n"
            "triple = a$$$b\n"
            "esc = $${a}\n"
            "mix = $$$${a}\n"
            "brace = ${a}}\n"
            "first = {${a}$\n"
        )
        self.assertEqual(c.get("s", "price"), "5$")
        self.assertEqual(c.get("s", "plain"), "$x and $ y")
        self.assertEqual(c.get("s", "triple"), "a$$b")
        self.assertEqual(c.get("s", "esc"), "${a}")
        self.assertEqual(c.get("s", "mix"), "$${a}")
        self.assertEqual(c.get("s", "brace"), "1}")
        self.assertEqual(c.get("s", "first"), "{1$")

    def test_result_is_not_rescanned(self):
        c = parse("[s]\na = $${b}\nb = oops\nc = <${a}>\nd = $$$$\ne = ${d}${d}\n")
        self.assertEqual(c.get("s", "c"), "<${b}>")
        self.assertEqual(c.get("s", "e"), "$$$$")

    def test_default_value_uses_requesting_section(self):
        c = parse(
            "[DEFAULT]\nurl = http://${host}:${port}/\nport = 80\n\n"
            "[web]\nhost = w.local\n\n"
            "[api]\nhost = a.local\nport = 9000\n\n"
            "[client]\nhost = c.local\ntarget = ${web:url}\nall = ${api:url}|${url}\n"
        )
        self.assertEqual(c.get("web", "url"), "http://w.local:80/")
        self.assertEqual(c.get("api", "url"), "http://a.local:9000/")
        # ${web:url} は DEFAULT から借りた値だが、展開の文脈は web
        self.assertEqual(c.get("client", "target"), "http://w.local:80/")
        self.assertEqual(c.get("client", "all"), "http://a.local:9000/|http://c.local:80/")
        with self.assertRaises(iniconf.InterpolationError):
            c.get("DEFAULT", "url")

    def test_default_section_reference(self):
        c = parse(
            "[DEFAULT]\npath = /usr\nhost = d.local\nurl = //${host}\n\n"
            "[s]\npath = ${DEFAULT:path}/local\nhost = s.local\nown = ${url}\nbase = ${DEFAULT:url}\n"
        )
        self.assertEqual(c.get("s", "path"), "/usr/local")
        self.assertEqual(c.get("s", "own"), "//s.local")
        self.assertEqual(c.get("s", "base"), "//d.local")
        self.assertEqual(c.get("DEFAULT", "url"), "//d.local")

    def test_cycles(self):
        c = parse(
            "[s]\nself = x${self}\na = ${b}\nb = ${c}\nc = ${t:x}\n"
            "path = ${path}/bin\n\n[t]\nx = ${s:a}\n"
        )
        for key in ("self", "a", "b", "c", "path"):
            with self.subTest(key=key):
                with self.assertRaises(iniconf.InterpolationError) as cm:
                    c.get("s", key)
                self.assertIsInstance(cm.exception, ConfigError)
                self.assertIsNone(cm.exception.lineno)
        with self.assertRaises(iniconf.InterpolationError):
            c.get("t", "x")

    def test_case_insensitive_key_in_cycle_detection(self):
        c = parse("[s]\na = ${B}\nb = ${A}\n")
        with self.assertRaises(iniconf.InterpolationError):
            c.get("s", "A")

    def test_repeated_reference_is_not_a_cycle(self):
        c = parse(
            "[s]\nd = 1\nb = ${d}${d}\nc = ${D}\na = ${b}-${c}-${b}\n"
            "deep = ${s:a}${a}\n"
        )
        self.assertEqual(c.get("s", "a"), "11-1-11")
        self.assertEqual(c.get("s", "deep"), "11-1-1111-1-11")

    def test_missing_references(self):
        c = parse(
            "[web]\nhost = h\n\n[s]\nhost = local\n"
            "k = ${nothing}\n"
            "sec = ${nosuch:host}\n"
            "case = ${Web:host}\n"
            "ok = ${WEB_NOT:x}\n"
            "spaced = ${ host }\n"
        )
        for key in ("k", "sec", "case", "ok", "spaced"):
            with self.subTest(key=key):
                with self.assertRaises(iniconf.InterpolationError):
                    c.get("s", key)
                with self.assertRaises(iniconf.InterpolationError):
                    c.get("s", key, "fallback")

    def test_malformed_references(self):
        c = parse(
            "[s]\na = 1\n"
            "open = x${a\n"
            "empty = ${}\n"
            "nosec = ${:a}\n"
            "nokey = ${s:}\n"
            "nested = ${a${a}}\n"
        )
        for key in ("open", "empty", "nosec", "nokey", "nested"):
            with self.subTest(key=key):
                with self.assertRaises(iniconf.InterpolationError):
                    c.get("s", key)

    def test_colon_splits_at_first(self):
        c = parse("[s]\nA:B = 1\n\n[t]\nv = ${s:a:b}\nw = ${s:A:B}\n")
        self.assertEqual(c.get("t", "v"), "1")
        self.assertEqual(c.get("t", "w"), "1")

    def test_ref_key_case_insensitive_section_case_sensitive(self):
        c = parse("[Web]\nhost = h\n\n[s]\nx = ${Web:HOST}\ny = ${HoSt}\nhost = local\n")
        self.assertEqual(c.get("s", "x"), "h")
        self.assertEqual(c.get("s", "y"), "local")

    def test_multiline_values(self):
        c = parse("[s]\nlist = a\n    ${x}\nx = 1\ny = [${list}]\n")
        self.assertEqual(c.get("s", "list"), "a\n1")
        self.assertEqual(c.get("s", "y"), "[a\n1]")

    def test_raw_and_items(self):
        c = parse("[DEFAULT]\nd = ${n}!\n\n[s]\nn = 3\nm = $$${n}\n")
        self.assertEqual(c.get("s", "m"), "$3")
        self.assertEqual(c.get("s", "m", raw=True), "$$${n}")
        self.assertEqual(c.get("s", "zz", "${n}", raw=True), "${n}")
        self.assertEqual(c.items("s"), [("n", "3"), ("m", "$3"), ("d", "3!")])
        self.assertEqual(
            c.items("s", raw=True), [("n", "3"), ("m", "$$${n}"), ("d", "${n}!")]
        )

    def test_items_raises_on_bad_reference(self):
        c = parse("[s]\na = ok\nb = ${missing}\n")
        with self.assertRaises(iniconf.InterpolationError):
            c.items("s")
        self.assertEqual(c.items("s", raw=True), [("a", "ok"), ("b", "${missing}")])

    def test_default_argument_not_interpolated(self):
        c = parse("[s]\nn = 1\n")
        self.assertEqual(c.get("s", "missing", "${n}"), "${n}")
        self.assertEqual(c.get("s", "missing", default="$$"), "$$")
        self.assertEqual(c.getint("s", "missing", "${n}"), "${n}")
        with self.assertRaises(KeyError):
            c.get("s", "missing")

    def test_getint_getbool_use_expanded_value(self):
        c = parse(
            "[DEFAULT]\nbase = 8000\nflag = ON\n\n"
            "[s]\nport = ${base}\nenabled = ${flag}\nbad = ${base}x\n"
        )
        self.assertEqual(c.getint("s", "port"), 8000)
        self.assertIs(c.getbool("s", "enabled"), True)
        with self.assertRaises(ValueError):
            c.getint("s", "bad")
        c.set("s", "broken", "${nope}")
        with self.assertRaises(iniconf.InterpolationError):
            c.getint("s", "broken", 1)
        with self.assertRaises(iniconf.InterpolationError):
            c.getbool("s", "broken", False)

    def test_lazy_expansion_and_dump_keeps_raw(self):
        text = "[s]\na = ${b}\nb = ${a}\nc = $$5\n"
        c = parse(text)
        self.assertEqual(c.dump(), text)
        self.assertEqual(c.get("s", "c"), "$5")
        c.set("s", "b", "fixed")
        self.assertEqual(c.get("s", "a"), "fixed")
        c.set("s", "b", "${c}${c}")
        self.assertEqual(c.get("s", "a"), "$5$5")
        self.assertEqual(c.get("s", "b", raw=True), "${c}${c}")

    def test_interpolation_disabled(self):
        c = parse("[s]\na = 1\nb = ${a}$$\nc = ${missing\n", interpolation=False)
        self.assertEqual(c.get("s", "b"), "${a}$$")
        self.assertEqual(c.get("s", "c"), "${missing")
        self.assertEqual(c.get("s", "b", raw=True), "${a}$$")
        self.assertEqual(c.items("s"), [("a", "1"), ("b", "${a}$$"), ("c", "${missing")])
        plain = Config(interpolation=False)
        plain.set("s", "x", "${y}")
        self.assertEqual(plain.get("s", "x"), "${y}")
        enabled = Config()
        enabled.set("s", "y", "2")
        enabled.set("s", "x", "${y}")
        self.assertEqual(enabled.get("s", "x"), "2")

    def test_interpolation_error_is_config_error(self):
        self.assertTrue(issubclass(iniconf.InterpolationError, ConfigError))
        c = parse("[s]\na = ${b}\n")
        with self.assertRaises(ConfigError) as cm:
            c.get("s", "a")
        self.assertIsNone(cm.exception.lineno)


if __name__ == "__main__":
    unittest.main()
=== END ===
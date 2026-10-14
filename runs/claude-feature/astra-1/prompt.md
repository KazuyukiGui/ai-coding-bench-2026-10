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

添付ファイル:
=== FILE: iniconf.py ===
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
=== END ===

答え方: 次のファイルの全体（変更しないファイルは不要）を、説明なしで、次の形式だけで返してください。各ファイルは「=== FILE: パス ===」の行で始め、最後に「=== END ===」の行を置きます。ツールは使えません。Python 3.11・標準ライブラリのみ。
返すファイル: iniconf.py

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

展開:
  - 値の取り出し時に "$$" は "$" に、"${キー}" や "${セクション:キー}" は参照先の
    （展開済みの）値に置き換わる。それ以外の "$" はそのまま残る。
  - "${キー}" は展開中の値の文脈セクションから探す。参照先が無い、"}" が無い、
    循環しているといった場合は InterpolationError。
  - 値は生のまま保存し、取り出すたびに展開する。
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
    """値の展開に失敗した。lineno は常に None。"""

    def __init__(self, message):
        super().__init__(message)


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

    # --- 展開 ---

    def _expand(self, section, key, value, raw=False):
        """取り出した生の値を、設定と raw の指定に従って展開して返す。"""
        if raw or not self._interpolation:
            return value
        return self._interpolate(section, value, [(section, key.lower())])

    def _resolve(self, ref, context, stack):
        """参照 ref を文脈 context で解決し、展開済みの値を返す。"""
        if ":" in ref:
            section, _, key = ref.partition(":")
            if not section:
                raise InterpolationError(f"empty section name in reference {ref!r}")
        else:
            section, key = context, ref
        if not key:
            raise InterpolationError(f"empty key in reference {ref!r}")
        entry = (section, key.lower())
        if entry in stack:
            raise InterpolationError(
                f"circular reference to {section}:{key.lower()}"
            )
        try:
            value = self._lookup(section, key)
        except KeyError:
            raise InterpolationError(
                f"unresolved reference {ref!r} in section {context!r}"
            ) from None
        stack.append(entry)
        try:
            return self._interpolate(section, value, stack)
        finally:
            stack.pop()

    def _interpolate(self, context, value, stack):
        parts = []
        i = 0
        n = len(value)
        while i < n:
            ch = value[i]
            if ch != "$":
                j = value.find("$", i)
                if j == -1:
                    j = n
                parts.append(value[i:j])
                i = j
                continue
            nxt = value[i + 1] if i + 1 < n else ""
            if nxt == "$":
                parts.append("$")
                i += 2
            elif nxt == "{":
                end = value.find("}", i + 2)
                if end == -1:
                    raise InterpolationError(f"unterminated reference in {value!r}")
                parts.append(self._resolve(value[i + 2:end], context, stack))
                i = end + 1
            else:
                parts.append("$")
                i += 1
        return "".join(parts)

    # --- 取り出し ---

    def get(self, section, key, default=_MISSING, *, raw=False):
        try:
            value = self._lookup(section, key)
        except KeyError:
            if default is _MISSING:
                raise
            return default
        return self._expand(section, key, value, raw)

    def getint(self, section, key, default=_MISSING):
        try:
            value = self._lookup(section, key)
        except KeyError:
            if default is _MISSING:
                raise
            return default
        value = self._expand(section, key, value)
        return int(value)

    def getbool(self, section, key, default=_MISSING):
        try:
            value = self._lookup(section, key)
        except KeyError:
            if default is _MISSING:
                raise
            return default
        value = self._expand(section, key, value)
        lowered = value.lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ValueError(f"not a boolean: {value!r}")

    def items(self, section, *, raw=False):
        return [
            (key, self.get(section, key, raw=raw)) for key in self.keys(section)
        ]

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
    config = Config(interpolation=interpolation)
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
あなたは、AI のコーディング性能を比べる試験の「審査員」です。別の AI が作った課題を、試験に使う前に点検します。解く側は課題文と添付ファイル（given）だけを読んでファイル全体を書きます。隠し試験（tests）と模範解答（ref）は解く側には見えません。

次の観点で点検し、問題だけを挙げてください。問題が無ければ空の配列を返します。
1. 課題文に書いていない挙動を、隠し試験が問うていないか（エラー文の文言・例外の型・並び順・空白・丸め方など）
2. 課題文の読み方が2通り以上あり、模範解答と違う読み方でも妥当なのに、試験で落ちる所はないか
3. 試験そのものの誤り（模範解答は通るが、課題文に照らすと期待値が違う）
4. 解く側に渡していない情報（given に無い関数名・ファイル名・定数）に試験が頼っていないか
5. 試験が環境に依存していないか（時刻・乱数・ファイルの並び順・ロケール）

答えは JSON だけで返してください（説明・前置き不要）。
{"issues": [{"severity": "high|medium|low", "where": "tests の関数名か課題文の箇所", "problem": "何が問題か", "fix": "課題文をどう直すか、または試験をどう直すか"}]}
severity の目安: high＝正しく解いても落ちる、medium＝妥当な別解が落ちる恐れ、low＝読みにくいが結果は変わらない。

---
=== FILE: given/config_parser.py ===
import re
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""
    pass


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
INT_RE = re.compile(r"^[+-]?(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|[0-9][0-9_]*)$")
FLOAT_RE = re.compile(r"^[+-]?(?:[0-9][0-9_]*\.[0-9_]*|\.[0-9_]+)(?:[eE][+-]?[0-9_]+)?$|^[+-]?[0-9][0-9_]*[eE][+-]?[0-9_]+$")


class _RawValue:
    def __init__(self, raw: str, is_raw_assign: bool, section: tuple[str, ...]):
        self.raw = raw
        self.is_raw_assign = is_raw_assign
        self.section = section


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and in_double:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i]
        i += 1
    return line


def _join_continuation_lines(text: str) -> list[str]:
    raw_lines = text.splitlines()
    logical_lines: list[str] = []
    buffer = ""
    continuing = False

    for line in raw_lines:
        clean = _strip_comment(line).strip()
        if not clean and not continuing:
            continue

        if clean.endswith("\\"):
            clean = clean[:-1].rstrip()
            buffer += clean
            continuing = True
        else:
            buffer += clean
            logical_lines.append(buffer)
            buffer = ""
            continuing = False

    if continuing:
        logical_lines.append(buffer)

    return logical_lines


def _unescape_double_quoted(s: str, is_raw_assign: bool) -> str:
    out = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\":
            if i + 1 >= len(s):
                raise ConfigError("Trailing backslash in string")
            nxt = s[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "r":
                out.append("\r")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            elif nxt == "$":
                if is_raw_assign:
                    out.append("$")
                else:
                    out.append("\\$")
            else:
                raise ConfigError(f"Invalid escape sequence: \\{nxt}")
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _split_array_elements(content: str) -> list[str]:
    content = content.strip()
    if not content:
        return []
    elements = []
    current = []
    depth = 0
    in_single = False
    in_double = False
    i = 0
    while i < len(content):
        ch = content[i]
        if ch == "\\" and in_double:
            current.append(content[i:i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth < 0:
                    raise ConfigError("Unbalanced brackets in array")
            elif ch == "," and depth == 0:
                elem = "".join(current).strip()
                if not elem:
                    raise ConfigError("Empty element in array")
                elements.append(elem)
                current = []
                i += 1
                continue
        current.append(ch)
        i += 1

    if in_single or in_double or depth != 0:
        raise ConfigError("Unterminated string or bracket in array")

    last = "".join(current).strip()
    if last:
        elements.append(last)
    return elements


def _coerce_unquoted(val: str) -> Any:
    if not val:
        raise ConfigError("Empty value is not allowed")

    low = val.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none"):
        return None

    if INT_RE.match(val):
        try:
            return int(val, 0)
        except ValueError:
            pass

    if FLOAT_RE.match(val):
        try:
            return float(val)
        except ValueError:
            pass

    if any(c.isspace() or c in ('"', "'") for c in val):
        raise ConfigError(f"Invalid unquoted string: {val}")

    return val


def _lookup_path(root: dict[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    curr: Any = root
    for part in path:
        if not isinstance(curr, dict) or part not in curr:
            return False, None
        curr = curr[part]
    return True, curr


def _format_scalar(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float, str)):
        return str(val)
    raise ConfigError(f"Cannot interpolate non-scalar value: {type(val)}")


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    if env is None:
        env = {}

    lines = _join_continuation_lines(text)
    root: dict[str, Any] = {}
    current_section: tuple[str, ...] = ()

    for line in lines:
        if line.startswith("[") and line.endswith("]"):
            sec_str = line[1:-1].strip()
            if not sec_str:
                raise ConfigError("Empty section name")
            parts = tuple(sec_str.split("."))
            for p in parts:
                if not IDENT_RE.match(p):
                    raise ConfigError(f"Invalid section part: {p}")
            current_section = parts

            curr = root
            for p in parts:
                if p not in curr:
                    curr[p] = {}
                elif not isinstance(curr[p], dict):
                    raise ConfigError(f"Section conflicts with existing key: {sec_str}")
                curr = curr[p]
            continue

        is_raw = False
        if ":=" in line:
            key_part, val_part = line.split(":=", 1)
            is_raw = True
        elif "=" in line:
            key_part, val_part = line.split("=", 1)
        else:
            raise ConfigError(f"Invalid syntax in line: {line}")

        key = key_part.strip()
        val_str = val_part.strip()

        if not IDENT_RE.match(key):
            raise ConfigError(f"Invalid key name: {key}")
        if not val_str:
            raise ConfigError(f"Empty value for key: {key}")

        target = root
        for p in current_section:
            target = target[p]

        if key in target and isinstance(target[key], dict):
            raise ConfigError(f"Key conflicts with existing section: {key}")

        target[key] = _RawValue(val_str, is_raw, current_section)

    resolving: set[tuple[str, ...]] = set()

    def resolve_node(path: tuple[str, ...], node: Any) -> Any:
        if not isinstance(node, _RawValue):
            return node
        if path in resolving:
            raise ConfigError(f"Circular reference detected at {'.'.join(path)}")

        resolving.add(path)
        try:
            res = evaluate_expr(node.raw, node.is_raw_assign, node.section)
        finally:
            resolving.remove(path)

        target = root
        for p in path[:-1]:
            target = target[p]
        target[path[-1]] = res
        return res

    def interpolate_string(s: str, section: tuple[str, ...]) -> tuple[bool, Any]:
        # Returns (is_direct_single_ref, value)
        pattern = re.compile(r"(?<!\\)\$\{([^}]*)\}")
        matches = list(pattern.finditer(s))
        if not matches:
            return False, s.replace("\\$", "$")

        if len(matches) == 1 and matches[0].span() == (0, len(s)):
            expr = matches[0].group(1)
            if not expr.startswith("ENV:"):
                val = resolve_ref(expr, section)
                return True, val

        out = []
        last_idx = 0
        for m in matches:
            out.append(s[last_idx:m.start()].replace("\\$", "$"))
            expr = m.group(1)
            if not expr:
                raise ConfigError("Empty interpolation")
            if expr.startswith("ENV:"):
                env_spec = expr[4:]
                if ":-" in env_spec:
                    var_name, default = env_spec.split(":-", 1)
                    val = env.get(var_name, default)
                else:
                    var_name = env_spec
                    if var_name not in env:
                        raise ConfigError(f"Missing environment variable: {var_name}")
                    val = env[var_name]
                out.append(val)
            else:
                val = resolve_ref(expr, section)
                out.append(_format_scalar(val))
            last_idx = m.end()

        out.append(s[last_idx:].replace("\\$", "$"))
        return False, "".join(out)

    def resolve_ref(ref_str: str, section: tuple[str, ...]) -> Any:
        if not ref_str:
            raise ConfigError("Empty reference")
        parts = tuple(ref_str.split("."))
        if len(parts) == 1 and section:
            local_path = section + parts
            found, val = _lookup_path(root, local_path)
            if found:
                return resolve_node(local_path, val)

        found, val = _lookup_path(root, parts)
        if not found:
            raise ConfigError(f"Undefined reference: {ref_str}")
        return resolve_node(parts, val)

    def evaluate_expr(expr: str, is_raw_assign: bool, section: tuple[str, ...]) -> Any:
        expr = expr.strip()
        if not expr:
            raise ConfigError("Empty expression")

        if expr.startswith('"'):
            if not expr.endswith('"') or len(expr) < 2:
                raise ConfigError("Unterminated double-quoted string")
            inner = _unescape_double_quoted(expr[1:-1], is_raw_assign)
            if is_raw_assign:
                return inner
            _, interpolated = interpolate_string(inner, section)
            if not isinstance(interpolated, str):
                return _format_scalar(interpolated)
            return interpolated

        if expr.startswith("'"):
            if not expr.endswith("'") or len(expr) < 2:
                raise ConfigError("Unterminated single-quoted string")
            inner = expr[1:-1]
            if "'" in inner:
                raise ConfigError("Single quote inside single-quoted string")
            return inner

        if expr.startswith("["):
            if not expr.endswith("]"):
                raise ConfigError("Unterminated array")
            elems = _split_array_elements(expr[1:-1])
            return [evaluate_expr(e, is_raw_assign, section) for e in elems]

        if is_raw_assign:
            return _coerce_unquoted(expr)

        is_direct, val = interpolate_string(expr, section)
        if is_direct:
            return val
        return _coerce_unquoted(val)

    def walk_and_resolve(curr: dict[str, Any], prefix: tuple[str, ...]) -> None:
        for k, v in list(curr.items()):
            path = prefix + (k,)
            if isinstance(v, _RawValue):
                resolve_node(path, v)
            elif isinstance(v, dict):
                walk_and_resolve(v, path)

    walk_and_resolve(root, ())
    return root

=== FILE: prompt.md ===
社内ツールで利用されている独自フォーマットの階層型設定ファイルパーサー `config_parser.py` に、仕様と異なる挙動をするバグが複数報告されています。以下の仕様を満たすようにコードを修正してください。

## 仕様

関数 `parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]` は、設定テキストを解析してネストされた辞書を返します。文法違反や解決できない参照がある場合は `ConfigError` 例外を送出します。

### 1. 行の構造とコメント
- 改行コードは `\n` または `\r\n` です。
- 空行（空白文字のみの行を含む）は無視します。
- `#` から行末まではコメントとして無視します。ただし、**クォート（`"` または `'`）で囲まれた文字列リテラル内の `#` はコメント開始と見なしません**。
- 行頭・行末の空白文字（スペースおよびタブ）は、トークン解析前に除去されます。

### 2. 行継続（バックスラッシュ）
- コメントを除去した後の行末（末尾の空白文字を除く）がバックスラッシュ `\` で終わる場合、その `\` を取り除き、次の行（先頭の空白文字を除去したもの）を直結して1つの論理行として扱います。
- ただし、行末がエスケープされたバックスラッシュ（`\\`、すなわち直前に連続する `\` を含め末尾の連続する `\` の個数が偶数個）である場合は行継続とは見なしません。
- コメントの末尾が `\` で終わっていても行継続にはなりません（コメント除去後の本体部分で判定します）。
- 継続先の行が空行やコメントのみの行であっても、その行のコメント除去後（空文字列）を結合し、その行自体は `\` で終わらないためそこで継続は終了します。
- ファイルの最終行が行継続で終わっている場合は `ConfigError` とします。

### 3. セクション
- `[section.subsection]` の形式でセクションを指定します。ドット `.` で区切ることで階層（ネストした辞書）を表現します。
- セクションが一度も宣言される前のキーは、ルート辞書直下に配置されます。
- 各階層名（ドットで区切られた各パート）は、英字またはアンダースコアで始まり、英数字・アンダースコア・ハイフンのみで構成される必要があります（正規表現 `^[A-Za-z_][A-Za-z0-9_-]*$`）。空のパート（例: `[a..b]` や `[.a]`）や不正な文字が含まれる場合は `ConfigError` とします。
- 同じセクションが複数回宣言された場合は、既存の辞書にマージされます（上書きリセットではありません）。
- すでにスカラー値やリスト等の辞書以外の値が設定されているパスをセクション名（またはその親パス）として指定した場合、あるいは既存のセクション名と同じ名前のキーに値を代入しようとした場合は `ConfigError` とします。

### 4. キーと値の代入
- 代入行は `key = value` または `key := value` の形式をとります。
  - `=` は通常の代入で、値の中の変数展開（後述）を**行います**。
  - `:=` は生（raw）代入で、値の中の変数展開を**行いません**（クォートのエスケープ処理や型推論は通常通り行います）。
- 行内の最初の `=` または `:=` がキーと値の区切りになります（キー名に `=` や `:` は含まれません）。区切り文字の前後の空白は無視されます。
- キー名の命名規則はセクションの各パートと同じ（`^[A-Za-z_][A-Za-z0-9_-]*$`）です。キー名にドットは含められません。違反する場合は `ConfigError` とします。
- 同一セクション内で同じキーが複数回定義された場合は、後から定義された値で上書きされます。

### 5. 値の型とリテラル
値の文字列（前後の空白除去後）は以下のルールで解釈されます。

1. **ダブルクォート文字列 (`"..."`)**:
   - 先頭と末尾が `"` で囲まれた文字列。型は `str`。
   - 内部では以下のエスケープシーケンスを解釈します: `\\` -> `\`, `\"` -> `"`, `\n` -> 改行, `\t` -> タブ, `\r` -> CR。
   - `\$` は `=` と `:=` のどちらでも `$` になります。`=` の場合、`\$` から生じた `$` は `${...}` 展開の開始とは見なしません。
   - まとめると、エスケープシーケンスは `\\`, `\"`, `\n`, `\t`, `\r`, `\$`（`$`になる）の6種類のみ有効とし、それ以外の `\x` 等が含まれる場合は `ConfigError` とします。
   - 閉じクォートがない場合や、閉じクォートの後に（コメント以外の）余分な文字がある場合は `ConfigError` とします。

2. **シングルクォート文字列 (`'...'`)**:
   - 先頭と末尾が `'` で囲まれた文字列。型は `str`。
   - エスケープ処理は一切行いません（`\` もそのままの文字として扱います）。したがって内部に `'` を含めることはできません。
   - シングルクォート文字列内では、`=` による代入であっても**変数展開を行いません**。
   - 閉じクォートがない場合や、閉じクォートの後に余分な文字がある場合は `ConfigError` とします。

3. **配列リテラル (`[...]`)**:
   - 先頭が `[`、末尾が `]` の場合、カンマ `,` 区切りのリスト（`list`）として解析します。
   - 要素の前後の空白は無視されます。空リスト `[]` や、末尾のカンマ（例: `[1, 2, ]`）も許容されます（末尾カンマの後ろに空要素は作られません）。ただし `[,]` や `[1, , 2]` のように空の要素がある場合は `ConfigError` とします。
   - 各要素は再帰的にこの「5. 値の型とリテラル」のルールで解釈されます（ネストした配列 `[[1, 2], [3]]` やクォート文字列を含む配列も可）。
   - クォート文字列内の `,` や `[` `]` は区切りとして扱いません。括弧の対応が取れていない場合は `ConfigError` とします。

4. **クォートなしの値**:
   - 空文字列（`key = ` のように値が空）は `ConfigError` とします（空文字列を設定したい場合は `""` または `''` を使います）。
   - 変数展開（`=` の場合）を行った**後**の文字列に対して、以下の優先順位で型変換を試みます（ただし、変数展開を含む場合でも、クォートなしの値として評価されます）。
     - **真偽値**: 大文字小文字を区別せず `true`, `yes`, `on` は `True`、`false`, `no`, `off` は `False`。
     - **Null**: 大文字小文字を区別せず `null`, `none` は `None`。
     - **整数 (`int`)**: オプションの符号（`+`/`-`）に続く10進数字列、または `0x`/`0X`（16進）、`0o`/`0O`（8進）、`0b`/`0B`（2進）プレフィックス付きの整数。数字の間のアンダースコア `_`（Pythonの数値リテラルと同様、先頭・末尾・連続は不可）も許容します。
     - **浮動小数点数 (`float`)**: 小数点を含む数値、または指数表記（`1e5`, `-2.5e-3` など）。整数と同様に数字間の単一アンダースコア `_` を許容します（`inf`, `nan` は数値ではなく文字列として扱います）。
     - **不正な数値**: 整数・浮動小数点数の形（数字と `_` の並び。整数なら `0x` 等の接頭辞、浮動小数点数なら小数点や指数部を含む）をしているのに、Python の数値リテラルとして不正な値は、文字列にせず `ConfigError` とします。例: `1__000`・`1000_`・`0x10_`・`1._5`・`1_.5`・`1e_5`・`1e5_`（アンダースコアが先頭・末尾・連続・小数点や指数記号の隣にある）。
     - **文字列 (`str`)**: 上記のいずれにも該当しない場合は、そのまま文字列（`str`）となります。ただし、クォートなしの文字列の途中にクォート文字（`"` や `'`）や空白文字が含まれている場合は `ConfigError` とします（空白やクォートを含めたい場合はクォートで囲む必要があります）。

### 6. 変数展開（インターポレーション）
- 通常の代入（`=`）における**ダブルクォート文字列内**および**クォートなしの値**（配列の各要素を含む）では、`${...}` 形式のプレースホルダを展開します。
- **他の設定値の参照 (`${path.to.key}`)**:
  - ドット区切りのフルパスで他のキーの値を参照します。
  - 相対パスではなく、常にルートからのパスとして解決します。ただし、指定されたパスにドットが含まれず（例: `${foo}`）、現在のセクション内にそのキーが存在する場合は現在のセクションの値を優先し、存在しない場合はルートのキーを参照します。
  - 参照は定義順序に依存しません（後方参照可能）。全行の構文解析が終わった後に解決します。
  - 参照先の値が文字列以外（整数、真偽値、リスト、辞書など）である場合:
    - 値全体が単一の参照のみ（例: `key = ${other.key}`、クォートなし）で構成されている場合は、参照先の**型と値をそのまま引き継ぎます**（リストや辞書の場合は、参照元と同じオブジェクトを共有しない深いコピーとします）。
    - ダブルクォート文字列内（例: `key = "${other.key}"`）や、他の文字と結合されている場合（例: `key = prefix_${other.key}`）は、参照先がスカラー値（`str`, `int`, `float`, `bool`）であれば文字列化して埋め込みます。ただし `bool` は小文字の `"true"` / `"false"` として文字列化します。参照先が `None`、リスト、辞書である場合は文字列への埋め込みはできず `ConfigError` とします。
    - クォートなしの値が複数の参照や文字の組み合わせ（例: `${host}:${port}`）になった場合、展開後の文字列全体に対して「クォートなしの値」の型変換および構文チェック（空白を含まないこと等）を行います。例えば展開結果に空白が含まれた場合、クォートなしであれば `ConfigError` になりますが、ダブルクォート内であれば許容されます。
- **環境変数の参照 (`${ENV:VAR_NAME}` または `${ENV:VAR_NAME:-default}`)**:
  - 引数 `env`（辞書、`None` の場合は空辞書として扱う。`os.environ` は見ない）から `VAR_NAME` を探します。
  - 存在すればその文字列値に展開されます。
  - 存在しない場合、`:-default` が指定されていれば `default` 文字列（空文字列も可）に展開され、指定されていなければ `ConfigError` とします。
  - 環境変数参照の結果は常に文字列ですが、クォートなしの値で展開された場合は、展開後の文字列に対して通常の型変換（整数や真偽値への変換など）が適用されます。ダブルクォート内であれば文字列のままです。
- 存在しないキーへの参照、セクション（辞書）を文字列内に埋め込もうとした場合、構文が不正な `${...}`（閉じ括弧がない、空の `${}` など）、および**循環参照**（`a = ${b}`, `b = ${a}` など）がある場合はすべて `ConfigError` とします。

=== FILE: ref/config_parser.py ===
import copy
import re
from typing import Any


class ConfigError(Exception):
    """設定ファイルの解析エラーを表す例外"""
    pass


IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
INT_RE = re.compile(r"^[+-]?(?:0[xX][0-9a-fA-F_]+|0[oO][0-7_]+|0[bB][01_]+|[0-9][0-9_]*)$")
FLOAT_RE = re.compile(
    r"^[+-]?(?:[0-9][0-9_]*\.[0-9_]*|\.[0-9_]+)(?:[eE][+-]?[0-9_]+)?$"
    r"|^[+-]?[0-9][0-9_]*[eE][+-]?[0-9_]+$"
)


class _RawValue:
    def __init__(self, raw: str, is_raw_assign: bool, section: tuple[str, ...]):
        self.raw = raw
        self.is_raw_assign = is_raw_assign
        self.section = section


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and in_double:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return line[:i]
        i += 1
    return line


def _has_line_continuation(s: str) -> bool:
    count = 0
    i = len(s) - 1
    while i >= 0 and s[i] == "\\":
        count += 1
        i -= 1
    return count % 2 == 1


def _join_continuation_lines(text: str) -> list[str]:
    raw_lines = text.splitlines()
    logical_lines: list[str] = []
    buffer = ""
    continuing = False

    for line in raw_lines:
        clean = _strip_comment(line).strip()
        if not clean and not continuing:
            continue

        if _has_line_continuation(clean):
            clean = clean[:-1]
            buffer += clean
            continuing = True
        else:
            buffer += clean
            if buffer:
                logical_lines.append(buffer)
            buffer = ""
            continuing = False

    if continuing:
        raise ConfigError("Unexpected end of file after line continuation")

    return logical_lines


def _check_double_quoted(expr: str, is_raw_assign: bool) -> str:
    """ダブルクォート文字列の構文とエスケープを検証し、内部表現に変換する。
    通常代入時の \\$ は後続の変数展開と区別するため \\x00 に一時置換する。
    """
    if len(expr) < 2 or not expr.startswith('"'):
        raise ConfigError("Invalid double-quoted string")

    out = []
    i = 1
    closed = False
    while i < len(expr):
        ch = expr[i]
        if ch == '"':
            if i != len(expr) - 1:
                raise ConfigError("Unexpected characters after closing double quote")
            closed = True
            break
        if ch == "\\":
            if i + 1 >= len(expr) - 1 and expr[-1] == '"' and i + 1 == len(expr) - 1:
                # 最後の " がエスケープされている場合は閉じクォートがない
                raise ConfigError("Unterminated double-quoted string")
            if i + 1 >= len(expr):
                raise ConfigError("Unterminated escape in double-quoted string")
            nxt = expr[i + 1]
            if nxt == "n":
                out.append("\n")
            elif nxt == "t":
                out.append("\t")
            elif nxt == "r":
                out.append("\r")
            elif nxt == '"':
                out.append('"')
            elif nxt == "\\":
                out.append("\\")
            elif nxt == "$":
                if is_raw_assign:
                    out.append("$")
                else:
                    out.append("\x00")
            else:
                raise ConfigError(f"Invalid escape sequence: \\{nxt}")
            i += 2
        else:
            out.append(ch)
            i += 1

    if not closed:
        raise ConfigError("Unterminated double-quoted string")
    return "".join(out)


def _split_array_elements(content: str) -> list[str]:
    content = content.strip()
    if not content:
        return []
    elements = []
    current = []
    depth = 0
    in_single = False
    in_double = False
    i = 0
    saw_comma = False

    while i < len(content):
        ch = content[i]
        if ch == "\\" and in_double:
            if i + 1 >= len(content):
                raise ConfigError("Unterminated escape in array")
            current.append(content[i:i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif not in_single and not in_double:
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth < 0:
                    raise ConfigError("Unbalanced brackets in array")
            elif ch == "," and depth == 0:
                elem = "".join(current).strip()
                if not elem:
                    raise ConfigError("Empty element in array")
                elements.append(elem)
                current = []
                saw_comma = True
                i += 1
                continue
        current.append(ch)
        i += 1

    if in_single or in_double or depth != 0:
        raise ConfigError("Unterminated string or bracket in array")

    last = "".join(current).strip()
    if last:
        elements.append(last)
    elif saw_comma and not elements:
        raise ConfigError("Empty element in array")

    return elements


def _coerce_unquoted(val: str) -> Any:
    if not val:
        raise ConfigError("Empty value is not allowed")

    low = val.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none"):
        return None

    if INT_RE.match(val):
        try:
            return int(val, 0)
        except ValueError:
            raise ConfigError(f"Invalid integer literal: {val}")

    if FLOAT_RE.match(val):
        try:
            return float(val)
        except ValueError:
            raise ConfigError(f"Invalid float literal: {val}")

    if any(c.isspace() or c in ('"', "'") for c in val):
        raise ConfigError(f"Invalid unquoted string: {val}")

    return val


def _lookup_path(root: dict[str, Any], path: tuple[str, ...]) -> tuple[bool, Any]:
    curr: Any = root
    for part in path:
        if not isinstance(curr, dict) or part not in curr:
            return False, None
        curr = curr[part]
    return True, curr


def _format_scalar(val: Any) -> str:
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float, str)):
        return str(val)
    raise ConfigError(f"Cannot interpolate non-scalar value: {type(val)}")


def _find_assignment_operator(line: str) -> tuple[str, str, bool]:
    idx_raw = line.find(":=")
    idx_eq = line.find("=")
    if idx_eq == -1:
        raise ConfigError(f"Invalid syntax in line: {line}")

    if idx_raw != -1 and idx_raw <= idx_eq:
        return line[:idx_raw], line[idx_raw + 2:], True
    return line[:idx_eq], line[idx_eq + 1:], False


def _validate_ref_syntax(ref_str: str) -> tuple[str, ...]:
    if not ref_str:
        raise ConfigError("Empty reference")
    parts = tuple(ref_str.split("."))
    for p in parts:
        if not IDENT_RE.match(p):
            raise ConfigError(f"Invalid reference path: {ref_str}")
    return parts


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    if env is None:
        env = {}

    lines = _join_continuation_lines(text)
    root: dict[str, Any] = {}
    current_section: tuple[str, ...] = ()

    for line in lines:
        if line.startswith("["):
            if not line.endswith("]"):
                raise ConfigError(f"Invalid section header: {line}")
            sec_str = line[1:-1].strip()
            if not sec_str:
                raise ConfigError("Empty section name")
            parts = tuple(sec_str.split("."))
            for p in parts:
                if not IDENT_RE.match(p):
                    raise ConfigError(f"Invalid section part: {p}")
            current_section = parts

            curr = root
            for p in parts:
                if p not in curr:
                    curr[p] = {}
                elif not isinstance(curr[p], dict):
                    raise ConfigError(f"Section conflicts with existing key: {sec_str}")
                curr = curr[p]
            continue

        key_part, val_part, is_raw = _find_assignment_operator(line)
        key = key_part.strip()
        val_str = val_part.strip()

        if not IDENT_RE.match(key):
            raise ConfigError(f"Invalid key name: {key}")
        if not val_str:
            raise ConfigError(f"Empty value for key: {key}")

        target = root
        for p in current_section:
            target = target[p]

        if key in target and isinstance(target[key], dict):
            raise ConfigError(f"Key conflicts with existing section: {key}")

        target[key] = _RawValue(val_str, is_raw, current_section)

    resolving: set[tuple[str, ...]] = set()

    def resolve_node(path: tuple[str, ...], node: Any) -> Any:
        if path in resolving:
            raise ConfigError(f"Circular reference detected at {'.'.join(path)}")

        if isinstance(node, _RawValue):
            resolving.add(path)
            try:
                res = evaluate_expr(node.raw, node.is_raw_assign, node.section)
            finally:
                resolving.remove(path)

            target = root
            for p in path[:-1]:
                target = target[p]
            target[path[-1]] = res
            return res
        elif isinstance(node, dict):
            resolving.add(path)
            try:
                walk_and_resolve(node, path)
            finally:
                resolving.remove(path)
            return node
        return node

    def resolve_ref(ref_str: str, section: tuple[str, ...]) -> Any:
        parts = _validate_ref_syntax(ref_str)
        if len(parts) == 1 and section:
            local_path = section + parts
            found, val = _lookup_path(root, local_path)
            if found:
                return resolve_node(local_path, val)

        found, val = _lookup_path(root, parts)
        if not found:
            raise ConfigError(f"Undefined reference: {ref_str}")
        return resolve_node(parts, val)

    def resolve_env(env_spec: str) -> str:
        if ":-" in env_spec:
            var_name, default = env_spec.split(":-", 1)
            if not var_name:
                raise ConfigError("Empty environment variable name")
            return env.get(var_name, default)
        else:
            var_name = env_spec
            if not var_name:
                raise ConfigError("Empty environment variable name")
            if var_name not in env:
                raise ConfigError(f"Missing environment variable: {var_name}")
            return env[var_name]

    def interpolate(s: str, section: tuple[str, ...], is_quoted: bool) -> tuple[bool, Any]:
        """文字列 s 内の ${...} を展開する。
        戻り値: (単一変数参照により型をそのまま引き継ぐか, 展開結果の値)
        """
        out: list[str] = []
        i = 0
        tokens: list[tuple[str, str]] = []  # ("lit", str) or ("ref", expr)

        while i < len(s):
            idx = s.find("$", i)
            if idx == -1:
                tokens.append(("lit", s[i:]))
                break
            if idx > i:
                tokens.append(("lit", s[i:idx]))

            if idx + 1 < len(s) and s[idx + 1] == "{":
                end_idx = s.find("}", idx + 2)
                if end_idx == -1:
                    raise ConfigError("Unclosed interpolation '${'")
                expr = s[idx + 2:end_idx]
                if not expr or "{" in expr:
                    raise ConfigError(f"Invalid interpolation expression: {expr}")
                tokens.append(("ref", expr))
                i = end_idx + 1
            else:
                tokens.append(("lit", "$"))
                i = idx + 1

        if (
            not is_quoted
            and len(tokens) == 1
            and tokens[0][0] == "ref"
            and not tokens[0][1].startswith("ENV:")
        ):
            val = resolve_ref(tokens[0][1], section)
            return True, copy.deepcopy(val)

        for kind, content in tokens:
            if kind == "lit":
                out.append(content.replace("\x00", "$"))
            else:
                if content.startswith("ENV:"):
                    out.append(resolve_env(content[4:]))
                else:
                    val = resolve_ref(content, section)
                    out.append(_format_scalar(val))

        return False, "".join(out)

    def evaluate_expr(expr: str, is_raw_assign: bool, section: tuple[str, ...]) -> Any:
        expr = expr.strip()
        if not expr:
            raise ConfigError("Empty expression")

        if expr.startswith('"'):
            inner = _check_double_quoted(expr, is_raw_assign)
            if is_raw_assign:
                return inner
            _, res = interpolate(inner, section, is_quoted=True)
            return res

        if expr.startswith("'"):
            if not expr.endswith("'") or len(expr) < 2:
                raise ConfigError("Unterminated single-quoted string")
            inner = expr[1:-1]
            if "'" in inner:
                raise ConfigError("Single quote inside single-quoted string")
            return inner

        if expr.startswith("["):
            if not expr.endswith("]"):
                raise ConfigError("Unterminated array")
            elems = _split_array_elements(expr[1:-1])
            return [evaluate_expr(e, is_raw_assign, section) for e in elems]

        if is_raw_assign:
            return _coerce_unquoted(expr)

        if "\\" in expr:
            # クォートなしの値では \$ のようなエスケープは仕様上定義されていない
            pass

        is_direct, val = interpolate(expr, section, is_quoted=False)
        if is_direct:
            return val
        return _coerce_unquoted(val)

    def walk_and_resolve(curr: dict[str, Any], prefix: tuple[str, ...]) -> None:
        for k, v in list(curr.items()):
            path = prefix + (k,)
            if isinstance(v, _RawValue):
                resolve_node(path, v)
            elif isinstance(v, dict):
                walk_and_resolve(v, path)

    walk_and_resolve(root, ())
    return root

=== FILE: tests/test_hidden.py ===
import unittest
from config_parser import ConfigError, parse_config


class TestConfigParserHidden(unittest.TestCase):

    def test_01_basic_types_and_sections(self):
        cfg = """
        # Root keys
        app_name = "my_service"
        max_retries = 3
        timeout = 1.5e2
        debug = on
         nothing = None

        [database.primary]
        host = 'localhost'
        port = 5432
        pool_size = 0x10
        flags = [true, false, "read_write", ]

        [database]
        enabled = yes
        """
        res = parse_config(cfg)
        self.assertEqual(res["app_name"], "my_service")
        self.assertEqual(res["max_retries"], 3)
        self.assertEqual(res["timeout"], 150.0)
        self.assertIs(res["debug"], True)
        self.assertIsNone(res["nothing"])
        self.assertIs(res["database"]["enabled"], True)
        self.assertEqual(res["database"]["primary"]["host"], "localhost")
        self.assertEqual(res["database"]["primary"]["port"], 5432)
        self.assertEqual(res["database"]["primary"]["pool_size"], 16)
        self.assertEqual(res["database"]["primary"]["flags"], [True, False, "read_write"])

    def test_02_comments_and_quotes(self):
        cfg = r"""
        a = "hello # not a comment" # this is a comment
        b = 'single # not a comment' # comment
        c = "escaped \" quote # still string" # end
        d = 'backslashes \\ in single quote'
        """
        res = parse_config(cfg)
        self.assertEqual(res["a"], "hello # not a comment")
        self.assertEqual(res["b"], "single # not a comment")
        self.assertEqual(res["c"], 'escaped " quote # still string')
        self.assertEqual(res["d"], r"backslashes \\ in single quote")

    def test_03_line_continuation_and_even_backslashes(self):
        cfg = (
            'path = "C:\\\\path\\\\"\n'
            'next_key = "ok"\n'
            'joined = [1, \\\n'
            '  2, \\\n'
            '  3]\n'
            'str_cont = "hello \\\n'
            '   world"\n'
            'escaped_cont = "ends with backslash \\\\\\\n'
            '   and continues"\n'
        )
        res = parse_config(cfg)
        self.assertEqual(res["path"], "C:\\path\\")
        self.assertEqual(res["next_key"], "ok")
        self.assertEqual(res["joined"], [1, 2, 3])
        self.assertEqual(res["str_cont"], "hello world")
        self.assertEqual(res["escaped_cont"], "ends with backslash \\and continues")

    def test_04_trailing_continuation_at_eof_raises(self):
        cfg = "a = 1 \\\n"
        with self.assertRaises(ConfigError):
            parse_config(cfg)

        cfg2 = "a = 1 \\\n# comment only"
        # Continuing into a comment-only line finishes the continuation on that line
        res = parse_config(cfg2)
        self.assertEqual(res["a"], 1)

    def test_05_assignment_operator_precedence(self):
        # "=" appears before ":=" inside the value
        cfg = """
        [vars]
        x = "expanded"
        normal_with_colon_eq = "a:=b:${x}"
        raw_with_eq = "a=b:${x}"
        raw_assign := "a=b:${x}"
        """
        res = parse_config(cfg)
        self.assertEqual(res["vars"]["normal_with_colon_eq"], "a:=b:expanded")
        self.assertEqual(res["vars"]["raw_with_eq"], "a=b:expanded")
        self.assertEqual(res["vars"]["raw_assign"], "a=b:${x}")

    def test_06_escape_sequences_and_dollar_escape(self):
        cfg = r"""
        v = "VAL"
        s1 = "line1\nline2\t\r\"\\"
        s2 = "literal \$${v} and \${v} and \\${v}"
        s3 := "raw \${v} and \\${v}"
        """
        res = parse_config(cfg)
        self.assertEqual(res["s1"], "line1\nline2\t\r\"\\")
        # \$ -> literal $, ${v} -> VAL
        # \${v} -> literal ${v}
        # \\${v} -> literal \ followed by VAL
        self.assertEqual(res["s2"], "literal $VAL and ${v} and \\VAL")
        self.assertEqual(res["s3"], "raw ${v} and \\${v}")

    def test_07_invalid_escapes_and_quote_boundaries(self):
        bad_cases = [
            r'a = "invalid \a escape"',
            'a = "unterminated',
            'a = "escaped end quote\\"',
            'a = "first" "second"',
            'a = "first" trailing',
            "a = 'first' 'second'",
            "a = 'unterminated",
            'a = unquoted"quote',
            "a = unquoted'quote",
            "a = unquoted with spaces",
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)

    def test_08_numeric_literals_and_underscores(self):
        cfg = """
        i_dec = -1_000_000
        i_hex = 0xFF_00
        i_oct = 0o755
        i_bin = 0b1010_0101
        f_std = 3.14_15
        f_exp = -2.5e-3
        f_lead_dot = .5
        f_trail_dot = 5.
        inf_str = inf
        nan_str = NaN
        """
        res = parse_config(cfg)
        self.assertEqual(res["i_dec"], -1000000)
        self.assertEqual(res["i_hex"], 0xFF00)
        self.assertEqual(res["i_oct"], 0o755)
        self.assertEqual(res["i_bin"], 0b10100101)
        self.assertAlmostEqual(res["f_std"], 3.1415)
        self.assertAlmostEqual(res["f_exp"], -0.0025)
        self.assertAlmostEqual(res["f_lead_dot"], 0.5)
        self.assertAlmostEqual(res["f_trail_dot"], 5.0)
        self.assertEqual(res["inf_str"], "inf")
        self.assertEqual(res["nan_str"], "NaN")

        bad_nums = [
            "a = 1__000",
            "a = 1000_",
            "a = 0x10_",
            "a = 1._5",
            "a = 1_.5",
            "a = 1e_5",
            "a = 1e5_",
        ]
        for case in bad_nums:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)

    def test_09_arrays_nested_and_edge_cases(self):
        cfg = """
        empty = []
        single_trailing = [ "a,b", '[1,2]', ]
        nested = [[1, 2], [3, [4, 5]], []]
        with_refs = [${base}, "${base}_str"]
        base = 42
        """
        res = parse_config(cfg)
        self.assertEqual(res["empty"], [])
        self.assertEqual(res["single_trailing"], ["a,b", "[1,2]"])
        self.assertEqual(res["nested"], [[1, 2], [3, [4, 5]], []])
        self.assertEqual(res["with_refs"], [42, "42_str"])

        bad_arrays = [
            "a = [,]",
            "a = [1, , 2]",
            "a = [, 1]",
            "a = [[1, 2]",
            "a = [1, 2]]",
        ]
        for case in bad_arrays:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)

    def test_10_interpolation_scoping_and_forward_refs(self):
        cfg = """
        global_val = "root_global"
        shared = "root_shared"
        forward_root = ${sec.sub.deep}

        [sec]
        shared = "sec_shared"
        use_local = ${shared}
        use_global = ${global_val}
        use_root_explicit = ${shared}

        [sec.sub]
        deep = ${sec.use_local}
        """
        res = parse_config(cfg)
        self.assertEqual(res["sec"]["use_local"], "sec_shared")
        self.assertEqual(res["sec"]["use_global"], "root_global")
        self.assertEqual(res["forward_root"], "sec_shared")

    def test_11_type_preservation_vs_string_coercion(self):
        cfg = """
        flag = true
        num = 100
        arr = [1, 2]

        [sub]
        k = "v"

        [copy]
        c_flag = ${flag}
        c_flag_str = "${flag}"
        c_num_str = "${num}"
        c_combined = ${num}_000
        c_arr = ${arr}
        c_sec = ${sub}
        """
        res = parse_config(cfg)
        self.assertIs(res["copy"]["c_flag"], True)
        self.assertEqual(res["copy"]["c_flag_str"], "true")
        self.assertEqual(res["copy"]["c_num_str"], "100")
        self.assertEqual(res["copy"]["c_combined"], 100000)
        self.assertEqual(res["copy"]["c_arr"], [1, 2])
        self.assertIsNot(res["copy"]["c_arr"], res["arr"])
        self.assertEqual(res["copy"]["c_sec"], {"k": "v"})
        self.assertIsNot(res["copy"]["c_sec"], res["sub"])

    def test_12_non_scalar_in_string_interpolation_raises(self):
        bad_cases = [
            "n = null\ns = \"val is ${n}\"",
            "n = null\ns = prefix_${n}",
            "arr = [1, 2]\ns = \"${arr}\"",
            "[sec]\na = 1\n[other]\ns = \"${sec}\"",
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)

    def test_13_env_interpolation(self):
        cfg = """
        port = ${ENV:PORT}
        port_str = "${ENV:PORT}"
        host = ${ENV:HOST:-localhost}
        empty_def = "${ENV:MISSING:-}"
        fallback_with_colon = "${ENV:MISSING:-http://localhost:8080}"
        raw_env := ${ENV:PORT}
        single_env = '${ENV:PORT}'
        """
        env = {"PORT": "8080"}
        res = parse_config(cfg, env=env)
        self.assertEqual(res["port"], 8080)
        self.assertEqual(res["port_str"], "8080")
        self.assertEqual(res["host"], "localhost")
        self.assertEqual(res["empty_def"], "")
        self.assertEqual(res["fallback_with_colon"], "http://localhost:8080")
        self.assertEqual(res["raw_env"], "${ENV:PORT}")
        self.assertEqual(res["single_env"], "${ENV:PORT}")

        with self.assertRaises(ConfigError):
            parse_config("x = ${ENV:UNDEFINED_VAR}", env={})

    def test_14_unquoted_interpolation_producing_spaces_raises(self):
        cfg = """
        greeting = "hello world"
        bad = ${greeting}_suffix
        """
        with self.assertRaises(ConfigError):
            parse_config(cfg)

        cfg_ok = """
        greeting = "hello world"
        direct = ${greeting}
        quoted = "${greeting}_suffix"
        """
        res = parse_config(cfg_ok)
        self.assertEqual(res["direct"], "hello world")
        self.assertEqual(res["quoted"], "hello world_suffix")

    def test_15_circular_reference_detection(self):
        cases = [
            "a = ${a}",
            "a = ${b}\nb = ${a}",
            "a = ${b}\nb = [${c}]\nc = \"${a}\"",
            "[sec]\na = ${sec}\n",
        ]
        for case in cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)

    def test_16_section_and_key_conflicts_and_naming(self):
        bad_cases = [
            "a = 1\n[a]\nb = 2",
            "[a.b]\nc = 1\n[a]\nb = 2",
            "[]\na = 1",
            "[a..b]\nc = 1",
            "[.a]\nc = 1",
            "[a.]\nc = 1",
            "[123sec]\na = 1",
            "123key = 1",
            "a.b = 1",
            "key = ",
            "a = ${}",
            "a = ${unclosed",
            "a = ${nonexistent}",
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises(ConfigError):
                    parse_config(case)


if __name__ == "__main__":
    unittest.main()

=== END ===

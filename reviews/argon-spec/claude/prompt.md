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
from typing import Any


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    raise NotImplementedError

=== FILE: prompt.md ===
# 課題: 階層型設定ファイル (HCL Lite) パーサーと評価器の実装

インフラ管理やアプリケーション設定で用いられる、独自の軽量設定言語「HCL Lite」を解析し、Python の辞書 (`dict`) に変換するモジュール `config_parser.py` を実装してください。

この言語は、ネストされたブロック構造、ドット区切りによる深い階層の定義、変数展開、環境変数参照、式の連結、およびブロック間の継承機能をサポートします。

---

## 1. インターフェース

`config_parser.py` に以下の例外クラスと関数を実装してください。

```python
from typing import Any

class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass

def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    """
    HCL Lite 形式の文字列 text を解析・評価し、結果の辞書を返す。
    env は環境変数の辞書であり、省略時または None の場合は空辞書として扱う。
    （os.environ は参照してはならない）
    """
```

---

## 2. 言語仕様

### 2.1 文字・空白・コメント
- 空白文字（スペース `' '`、タブ `'\t'`）はトークンの区切りとして扱われ、それ自体は意味を持ちません（文字列リテラル内を除く）。
- 改行は `\n` または `\r\n` です。
- `#` または `//` から行末までは**行コメント**として無視されます（文字列リテラル内を除く）。
- `/*` から `*/` までは**ブロックコメント**として無視されます（文字列リテラル内を除く）。複数行にまたがることがあります。ブロックコメントのネストはサポートしません。閉じられていない `/*` がある場合は `ConfigError` を送出します。

### 2.2 識別子とパス
- **識別子 (Identifier)** は、英字 (`a-z`, `A-Z`) またはアンダースコア (`_`) で始まり、その後に英数字 (`a-z`, `A-Z`, `0-9`)、アンダースコア (`_`)、ハイフン (`-`) が0文字以上続く文字列です。
  - ただし、`true`, `false`, `null` は予約語（リテラル）ですが、**キー名・ブロック名・変数参照のパス要素としては通常の識別子と同様に使用可能**とします（値の位置に単独で現れた場合のみリテラルとして解釈します）。
- **パス (Path)** は、1つ以上の識別子をドット `.` で連結したものです（例: `server`, `server.http.port`）。先頭や末尾のドット、連続するドット（`..`）は構文エラー (`ConfigError`) です。

### 2.3 文と構造
設定ファイルは、0個以上の**代入文**または**ブロック定義**の並びです。

#### (1) 代入文
```
<path> = <expr>
```
- `<path>` で指定された階層に `<expr>` の評価結果を格納します。
- 例: `a.b.c = 10` は `{"a": {"b": {"c": 10}}}` を生成します。
- 複数の代入文は改行またはセミコロン `;` で区切られます（行末の `;` は任意、空文 `;` も許容されます）。
- 同じ行にセミコロンなしで複数の代入文を並べることはできません（例: `a = 1 b = 2` は `ConfigError`）。

#### (2) ブロック定義
```
<path> {
    <文の並び>
}
```
または継承付きブロック定義:
```
<path> : <parent_path> {
    <文の並び>
}
```
- `<path>` で指定された階層に辞書（オブジェクト）を生成し、ブロック内部の文をその辞書のスコープ内で処理します。
- 開き波括弧 `{` の前には改行があってもなくても構いません。
- 閉じ波括弧 `}` の後には改行または `;`（あるいはファイル末尾や外側の `}`）が続きます。
- 空のブロック `box {}` は空の辞書 `{"box": {}}` を生成します。
- 継承 `: <parent_path>` が指定された場合、このブロックの初期状態として `<parent_path>` が指す辞書をディープコピーして引き継ぎます（詳細は「3. 評価とセマンティクス」を参照）。`<parent_path>` の構文は `<path>` と同じです。

#### (3) マージと上書き規則
- 同一の辞書パスに対して複数回ブロック定義やドットパスによる辞書生成が行われた場合、それらは**深いマージ（ディープマージ）**されます。
  ```
  server { host = "localhost" }
  server.port = 8080
  # 結果: {"server": {"host": "localhost", "port": 8080}}
  ```
- 同一のプリミティブ値やリストのキーに対して再度代入が行われた場合は、後から記述された値で**上書き**されます。
- **型の衝突エラー**:
  - すでに辞書（ブロック）として定義されている箇所を、非辞書（数値、文字列、真偽値、null、リスト）で上書きしようとした場合、またはその逆（非辞書として定義されている箇所を辞書やブロック、あるいはドットパスの途中経路として使おうとした場合）は `ConfigError` を送出します。
  - ただし、継承によって親から引き継いだプロパティについては、親で非辞書だったキーを子で非辞書で上書きすることは可能です（親で辞書だったキーを子で非辞書にする、またはその逆は同様に `ConfigError` とします）。

---

### 2.4 値と式 (`<expr>`)

`<expr>` は、1つ以上の**項 (`<term>`)** を `+` 演算子で連結したものです。
```
<expr> ::= <term> ( "+" <term> )*
```
注意: `+` の前後に改行を含める場合は、`+` の直後でのみ改行を許容します（例: `"a" +\n "b"` は有効、`"a"\n + "b"` は別の文とみなされ構文エラーとなります）。

#### 項 (`<term>`) の種類

1. **文字列リテラル**: ダブルクォート `"` で囲まれた文字列。
   - 文字列リテラル内に生の改行文字を含めることはできません（`ConfigError`）。
   - **エスケープシーケンス**: `\"` (`"`), `\\` (`\`), `\n` (改行), `\t` (タブ), `\r` (キャリッジリターン), `\$` (文字としての `$`) をサポートします。これら以外の `\x` が現れた場合は `ConfigError` です。
   - **文字列補間 (Interpolation)**: 文字列中に `${...}` が含まれる場合、内部の式を評価した結果を文字列化して埋め込みます（詳細は後述）。`\$` でエスケープされた `\${...}` は補間されず、文字通りの `${...}` になります。

2. **数値リテラル**:
   - **整数 (`int`)**: オプションの符号 (`+` または `-`) に続く1桁以上の数字 `0-9`。
     - ただし、`0` 以外の数値が `0` から始まる場合（例: `01`, `-007`）は構文エラー (`ConfigError`) とします。`0`, `-0`, `+0` は有効な整数 `0` です。
   - **浮動小数点数 (`float`)**: オプションの符号に続く小数表記（例: `3.14`, `-0.5`, `10.0`）および指数表記（例: `1e5`, `2.5E-3`, `-1E+2`）。
     - 小数点の前後には必ず1桁以上の数字が必要です（`.5` や `5.` は不可）。整数部の先頭ゼロ規則は整数と同じです（`0.5` は有効、`01.5` は不可）。

3. **真偽値リテラル (`bool`)**: `true` (`True`), `false` (`False`)。

4. **Null リテラル (`None`)**: `null` (`None`)。

5. **リストリテラル (`list`)**: `[` と `]` で囲まれ、カンマ `,` で区切られた0個以上の `<expr>`。
   - リストの要素には任意の `<expr>`（別のリストや演算式、参照を含む）を指定できます。
   - `[` の直後、`,` の前後、`]` の直前には自由に改行やコメントを入れることができます。
   - 末尾のカンマ（Trailing comma、例: `[1, 2, ]`）を許容します。ただし `[,]` や `[1,,2]` は構文エラー (`ConfigError`) です。

6. **参照 (`${...}`)**:
   - 単独の項として `${<path>}` または環境変数参照 `${env:<VAR_NAME>}`、`${env:<VAR_NAME>:-<default_text>}` を記述できます。
   - 単独の項として記述された `${<path>}` は、参照先の**型を保持**します（参照先が `int` なら `int`、`list` なら `list`、辞書なら辞書のディープコピー。ただし辞書を値として直接代入することはできず、式の中で辞書が評価された場合は `ConfigError` とします）。

---

## 3. 評価とセマンティクス

すべての構文解析が完了した後、以下の規則に従って継承・変数参照・演算を解決します。

### 3.1 スコープと変数参照 (`${<path>}`)
`${<path>}`（例: `${port}` や `${db.host}`）は、その式が記述されているブロックから外側に向かって探索（レキシカルスコープ）を行います。

1. `<path>` の先頭の識別子を `head`、残りを `tail` とします（例: `db.host` なら `head = "db"`, `tail = ["host"]`）。
2. 現在のブロック（その式が直接属している辞書）にキー `head` が存在するか調べます。
   - 存在しない場合、1つ外側の親ブロック（包含ブロック）へ移動し、ルート階層に到達するまで繰り返します。
   - ルート階層でも `head` が見つからない場合は、未定義参照として `ConfigError` を送出します。
3. **重要**: あるブロックで `head` が見つかった場合、そこから `tail` をたどります。もし途中でキーが存在しない、あるいは辞書以外の値に対してさらにキーをたどろうとした場合は、**さらに外側のブロックを再探索することはせず**、直ちに `ConfigError` を送出します（シャドーイング）。
4. 参照の解決は定義順（ファイルの上から下か）に依存しません（後方参照が可能）。ただし、同じキーが複数回代入されている場合は、最終的に上書きされた後の値が参照されます。

### 3.2 環境変数参照 (`${env:...}`)
- `${env:VAR}`: 引数 `env` 辞書からキー `"VAR"` の値（`str`）を取得します。`"VAR"` が `env` に存在しない場合は `ConfigError` を送出します。
- `${env:VAR:-default}`: `"VAR"` が `env` に存在し、かつその値が**空文字列 `""` でない**場合は `env["VAR"]` を返し、存在しないか空文字列 `""` の場合は `default` 部分の文字列をそのまま（`str` として）返します。
  - `VAR` は1文字以上の英数字またはアンダースコア (`A-Za-z0-9_`) です。
  - `default` 部分には `}` 以外の任意の文字を含めることができます（空でも構いません。例: `${env:VAR:-}` は空文字列 `""` になります）。`default` 内でネストした `${...}` はサポートしません。
- 環境変数参照の結果は常に文字列 (`str`) です（単独の項として書かれていても数値等への自動変換はしません）。

### 3.3 文字列補間 (String Interpolation)
ダブルクォート文字列内の `${...}` には、通常の変数参照 `${<path>}` または環境変数参照 `${env:...}` を記述できます（文字列内の `${...}` の中には `+` 演算子などは書けません）。
- 参照先の評価結果は以下の規則で文字列に変換されて埋め込まれます:
  - `str`: そのまま
  - `int`, `float`: Python の `str(val)` と同じ文字列（例: `80` -> `"80"`, `3.5` -> `"3.5"`）
  - `bool`: `True` は `"true"`、`False` は `"false"`（小文字）
  - `None` (`null`): `"null"`
  - `list` または `dict`: 文字列内に埋め込むことはできず、`ConfigError` を送出します。

### 3.4 `+` 演算子の評価
`<term1> + <term2>` は左結合で順に評価されます。許容される型の組み合わせは以下の通りです:
1. **`int` / `float` 同士の加算**: 両方が数値（`int` または `float`、ただし `bool` は除く）の場合、算術加算を行います（`int + int -> int`、どちらかが `float` なら `float`）。
2. **`str` 同士の連結**: 両方が `str` の場合、文字列を連結します。（※ `str` と数値を `+` で直接足すことはできません。`"port: " + 80` は `ConfigError` です。文字列補間 `"port: ${port}"` を使う必要があります）
3. **`list` 同士の連結**: 両方が `list` の場合、新しいリストとして連結します（元のリストは変更しない）。
4. 上記以外の組み合わせ（`bool`、`None`、`dict` を含む場合や、異なる型同士の `+`）はすべて `ConfigError` を送出します。

### 3.5 ブロック継承 (`<path> : <parent_path> { ... }`)
1. `<parent_path>` の解決:
   - `<path>` の対象となるブロックの**1つ外側のスコープ**（`<path>` が `a.b.c` のようにドットを含む場合は、`a.b` のスコープ）を起点として、3.1 と同じレキシカルスコープ規則で `<parent_path>` を探索します。
   - 参照先が存在しない場合や、参照先が辞書（ブロック）でない場合は `ConfigError` です。
   - 自分自身や自分の子孫ブロックを継承することはできません（循環参照として `ConfigError`）。
2. マージ規則:
   - 親ブロック（親も継承を持っている場合は、親の継承や内部の式が解決された状態）の全キー・値をディープコピーし、その上に子ブロック内の定義をディープマージ（辞書同士は再帰マージ、非辞書は上書き）します。
   - 同一の `<path>` に対して複数回ブロック定義があり、そのうち複数で継承 `: <parent>` が指定されている場合は `ConfigError` とします（1つのブロックに対する継承指定は最大1回まで）。
3. **動的スコープ（遅延評価）に関する重要規則**:
   - 親ブロック内で `url = "http://${host}:${port}"` のように変数を参照している場合、子ブロックにコピーされた `url` の式は、**子ブロックのスコープで再評価**されます。
   - つまり、子ブロックで `port` が上書きされていれば、子の `url` には子の `port` の値が使われます。一方、親ブロックで参照していた変数が親の外側のスコープにあった場合、子ブロックが別のスコープ階層にあっても、子ブロック側で見つからなければ子ブロックの外側のスコープを探索します（つまり、AST/未評価の式そのものが子ブロックにコピーされたものとして扱います）。

### 3.6 循環参照の検出
- 変数の参照関係（例: `a = ${b}`, `b = ${a}`）や、ブロック継承の連鎖（例: `A : B {}`, `B : A {}`）、あるいはその組み合わせにおいて循環が発生している場合は、無限ループに陥ることなく検出し、`ConfigError` を送出してください。
- ただし、最終的な評価結果を得るために必要のない箇所であっても、**ファイル内に記述されたすべてのキーおよびブロックは必ず評価**されなければなりません。

---

## 4. 設定例

### 入力例
```hcl
# グローバル設定
base_domain = "example.com"
default_port = 8000

template.service {
    host = "${sub}.${base_domain}"
    port = ${default_port}
    tags = ["v1"]
    timeout = 30
}

// 本番用APIサービス（テンプレートを継承）
prod.api : template.service {
    sub = "api"
    port = ${default_port} + 80
    tags = ["prod"] + ["api"]
    env_mode = "${env:APP_ENV:-production}"
}

prod.api. { # <- 構文エラーの例ではなく、正常な追加設定なら prod.api.timeout = 60 のように書く
```
（※最後の行を除いた場合の）`parse_config(text, env={})` の返り値:
```python
{
    "base_domain": "example.com",
    "default_port": 8000,
    "template": {
        "service": {
            "host": "${sub}.${base_domain}", # ※注意: 下記「補足」参照！
            ...
        }
    }
}
```
**【補足・重要】**
上記の例において、`template.service` 自身には `sub` が定義されていません。
3.6 の規則「ファイル内に記述されたすべてのキーおよびブロックは必ず評価されなければならない」に従い、もし `template.service` 内に未定義の `${sub}` があれば `template.service.host` の評価時に `ConfigError` になります。
したがって、`template.service` 側にもデフォルトの `sub = "default"` が定義されている必要があります。未定義の変数を含むテンプレート単体は許容されません。

=== FILE: ref/config_parser.py ===
from typing import Any
from dataclasses import dataclass, field
import re


class ConfigError(Exception):
    """構文エラー、型エラー、未定義参照、循環参照などの設定エラー全般を表す例外"""
    pass


# --- Lexer ---

@dataclass
class Token:
    type: str
    value: Any
    line: int
    col: int


IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_-]*')
NUMBER_RE = re.compile(
    r'^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?'
)


def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(text)
    line = 1
    col = 1

    while i < n:
        ch = text[i]

        # Whitespace (spaces and tabs)
        if ch in (' ', '\t'):
            i += 1
            col += 1
            continue

        # Newlines
        if ch == '\r':
            if i + 1 < n and text[i + 1] == '\n':
                i += 2
            else:
                i += 1
            tokens.append(Token('NEWLINE', '\n', line, col))
            line += 1
            col = 1
            continue
        if ch == '\n':
            i += 1
            tokens.append(Token('NEWLINE', '\n', line, col))
            line += 1
            col = 1
            continue

        # Comments
        if ch == '#' or (ch == '/' and i + 1 < n and text[i + 1] == '/'):
            while i < n and text[i] not in ('\n', '\r'):
                i += 1
                col += 1
            continue

        if ch == '/' and i + 1 < n and text[i + 1] == '*':
            start_line, start_col = line, col
            i += 2
            col += 2
            closed = False
            while i < n:
                if text[i] == '*' and i + 1 < n and text[i + 1] == '/':
                    i += 2
                    col += 2
                    closed = True
                    break
                if text[i] == '\r':
                    if i + 1 < n and text[i + 1] == '\n':
                        i += 2
                    else:
                        i += 1
                    line += 1
                    col = 1
                elif text[i] == '\n':
                    i += 1
                    line += 1
                    col = 1
                else:
                    i += 1
                    col += 1
            if not closed:
                raise ConfigError(f"Unclosed block comment at {start_line}:{start_col}")
            continue

        # Single-char punctuation
        if ch in '{}[],=;:':
            tokens.append(Token(ch, ch, line, col))
            i += 1
            col += 1
            continue

        # Dot
        if ch == '.':
            tokens.append(Token('.', '.', line, col))
            i += 1
            col += 1
            continue

        # String literal
        if ch == '"':
            start_line, start_col = line, col
            i += 1
            col += 1
            parts: list[tuple[str, str]] = []  # ('LIT', str) or ('INTERP', str)
            buf: list[str] = []
            closed = False
            while i < n:
                c = text[i]
                if c in ('\n', '\r'):
                    raise ConfigError(f"Unterminated string literal at {start_line}:{start_col}")
                if c == '"':
                    i += 1
                    col += 1
                    closed = True
                    break
                if c == '\\':
                    if i + 1 >= n:
                        raise ConfigError(f"Unterminated escape in string at {line}:{col}")
                    esc = text[i + 1]
                    if esc == '"':
                        buf.append('"')
                    elif esc == '\\':
                        buf.append('\\')
                    elif esc == 'n':
                        buf.append('\n')
                    elif esc == 't':
                        buf.append('\t')
                    elif esc == 'r':
                        buf.append('\r')
                    elif esc == '$':
                        buf.append('$')
                    else:
                        raise ConfigError(f"Invalid escape sequence \\{esc} at {line}:{col}")
                    i += 2
                    col += 2
                    continue
                if c == '$' and i + 1 < n and text[i + 1] == '{':
                    if buf:
                        parts.append(('LIT', ''.join(buf)))
                        buf = []
                    i += 2
                    col += 2
                    interp_buf: list[str] = []
                    found_close = False
                    while i < n:
                        if text[i] in ('\n', '\r'):
                            raise ConfigError(f"Unterminated interpolation at {line}:{col}")
                        if text[i] == '}':
                            i += 1
                            col += 1
                            found_close = True
                            break
                        interp_buf.append(text[i])
                        i += 1
                        col += 1
                    if not found_close:
                        raise ConfigError(f"Unterminated interpolation at {start_line}:{start_col}")
                    interp_content = ''.join(interp_buf)
                    if not interp_content:
                        raise ConfigError(f"Empty interpolation at {line}:{col}")
                    parts.append(('INTERP', interp_content))
                    continue
                buf.append(c)
                i += 1
                col += 1
            if not closed:
                raise ConfigError(f"Unterminated string literal at {start_line}:{start_col}")
            if buf or not parts:
                parts.append(('LIT', ''.join(buf)))
            tokens.append(Token('STRING', parts, start_line, start_col))
            continue

        # Reference ${...}
        if ch == '$' and i + 1 < n and text[i + 1] == '{':
            start_line, start_col = line, col
            i += 2
            col += 2
            ref_buf: list[str] = []
            found_close = False
            while i < n:
                if text[i] in ('\n', '\r'):
                    raise ConfigError(f"Newline in reference at {start_line}:{start_col}")
                if text[i] == '}':
                    i += 1
                    col += 1
                    found_close = True
                    break
                ref_buf.append(text[i])
                i += 1
                col += 1
            if not found_close:
                raise ConfigError(f"Unterminated reference at {start_line}:{start_col}")
            ref_content = ''.join(ref_buf)
            if not ref_content:
                raise ConfigError(f"Empty reference at {start_line}:{start_col}")
            tokens.append(Token('REF', ref_content, start_line, start_col))
            continue

        # Numbers or '+' operator
        if ch in '+-' or ch.isdigit():
            # Determine if '+' is binary operator or unary sign on number
            # Wait: in our grammar, '+' can be binary operator between terms, OR leading sign of a number term.
            # If previous meaningful token (ignoring NEWLINE) can end a term, '+' is binary operator!
            prev_tok = None
            for t in reversed(tokens):
                if t.type != 'NEWLINE':
                    prev_tok = t
                    break
            is_after_term = prev_tok is not None and prev_tok.type in (
                'NUMBER', 'STRING', 'IDENT', 'REF', ']'
            )
            if ch == '+' and (is_after_term or not (i + 1 < n and text[i + 1].isdigit())):
                tokens.append(Token('+', '+', line, col))
                i += 1
                col += 1
                continue

            # Otherwise try matching a number literal
            sub = text[i:]
            # Check for invalid leading zeros like 01, -01, +01
            m_invalid_zero = re.match(r'^[+-]?0[0-9]+', sub)
            if m_invalid_zero:
                raise ConfigError(f"Invalid leading zero in number at {line}:{col}")
            m = NUMBER_RE.match(sub)
            if not m:
                raise ConfigError(f"Invalid number literal at {line}:{col}")
            num_str = m.group(0)
            after_idx = i + len(num_str)
            # Check trailing invalid characters like `123abc` or `1.2.3` or `5.`
            if after_idx < n and (text[after_idx].isalpha() or text[after_idx] in ('_', '.')):
                raise ConfigError(f"Invalid characters after number at {line}:{col}")
            if '.' in num_str or 'e' in num_str or 'E' in num_str:
                val: int | float = float(num_str)
            else:
                val = int(num_str)
            tokens.append(Token('NUMBER', val, line, col))
            i += len(num_str)
            col += len(num_str)
            continue

        # Identifiers / Keywords
        m_ident = IDENT_RE.match(text[i:])
        if m_ident:
            ident_str = m_ident.group(0)
            tokens.append(Token('IDENT', ident_str, line, col))
            i += len(ident_str)
            col += len(ident_str)
            continue

        raise ConfigError(f"Unexpected character {ch!r} at {line}:{col}")

    tokens.append(Token('EOF', None, line, col))
    return tokens


# --- AST Definitions ---

@dataclass
class ExprNode:
    terms: list['TermNode']


class TermNode:
    pass


@dataclass
class LiteralNode(TermNode):
    value: Any  # int, float, bool, None


@dataclass
class StringNode(TermNode):
    parts: list[tuple[str, Any]]  # ('LIT', str) or ('REF', RefSpec)


@dataclass
class ListNode(TermNode):
    elements: list[ExprNode]


@dataclass
class RefSpec:
    kind: str  # 'VAR' or 'ENV'
    path: list[str] = field(default_factory=list)
    env_var: str = ""
    has_default: bool = False
    default_val: str = ""


@dataclass
class RefNode(TermNode):
    spec: RefSpec


@dataclass
class BlockScope:
    parent_scope: 'BlockScope | None' = None
    inherit_paths: list[list[str]] = field(default_factory=list)
    # key -> BlockScope or ExprNode
    entries: dict[str, 'BlockScope | ExprNode'] = field(default_factory=dict)
    # Track whether a key was explicitly set as a value or block in THIS scope
    key_kinds: dict[str, str] = field(default_factory=dict)  # 'BLOCK' or 'EXPR'

    def clone_for_child(self, new_parent: 'BlockScope | None') -> 'BlockScope':
        new_scope = BlockScope(parent_scope=new_parent)
        new_scope.inherit_paths = [list(p) for p in self.inherit_paths]
        for k, v in self.entries.items():
            new_scope.key_kinds[k] = self.key_kinds[k]
            if isinstance(v, BlockScope):
                new_scope.entries[k] = v.clone_for_child(new_scope)
            else:
                new_scope.entries[k] = v
        return new_scope


def parse_ref_content(content: str) -> RefSpec:
    if content.startswith('env:'):
        rest = content[4:]
        if ':-' in rest:
            var_name, default_val = rest.split(':-', 1)
            has_default = True
        else:
            var_name = rest
            default_val = ""
            has_default = False
        if not re.match(r'^[A-Za-z0-9_]+$', var_name):
            raise ConfigError(f"Invalid environment variable name: {var_name!r}")
        if '${' in default_val:
            raise ConfigError("Nested interpolation in env default is not supported")
        return RefSpec(
            kind='ENV',
            env_var=var_name,
            has_default=has_default,
            default_val=default_val,
        )
    else:
        if not content or content.startswith('.') or content.endswith('.') or '..' in content:
            raise ConfigError(f"Invalid reference path: {content!r}")
        parts = content.split('.')
        for p in parts:
            if not IDENT_RE.match(p) or IDENT_RE.match(p).group(0) != p:
                raise ConfigError(f"Invalid identifier {p!r} in reference {content!r}")
        return RefSpec(kind='VAR', path=parts)


# --- Parser ---

class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.pos = 0

    def current(self) -> Token:
        return self.tokens[self.pos]

    def consume(self, expected_type: str | None = None) -> Token:
        tok = self.current()
        if expected_type is not None and tok.type != expected_type:
            raise ConfigError(
                f"Expected {expected_type}, got {tok.type} at {tok.line}:{tok.col}"
            )
        self.pos += 1
        return tok

    def skip_newlines(self) -> None:
        while self.current().type == 'NEWLINE':
            self.pos += 1

    def skip_separators(self) -> None:
        while self.current().type in ('NEWLINE', ';'):
            self.pos += 1

    def parse_root(self) -> BlockScope:
        root = BlockScope(parent_scope=None)
        self.skip_separators()
        while self.current().type != 'EOF':
            self.parse_statement(root)
            if self.current().type not in ('NEWLINE', ';', 'EOF'):
                tok = self.current()
                raise ConfigError(
                    f"Expected newline or ';' after statement, got {tok.type} at {tok.line}:{tok.col}"
                )
            self.skip_separators()
        return root

    def parse_path(self) -> list[str]:
        parts: list[str] = []
        tok = self.consume('IDENT')
        parts.append(tok.value)
        while self.current().type == '.':
            self.consume('.')
            if self.current().type != 'IDENT':
                t = self.current()
                raise ConfigError(f"Expected identifier after '.', got {t.type} at {t.line}:{t.col}")
            parts.append(self.consume('IDENT').value)
        return parts

    def ensure_subscope(self, scope: BlockScope, path: list[str]) -> BlockScope:
        curr = scope
        for part in path:
            if part in curr.entries:
                if curr.key_kinds[part] != 'BLOCK':
                    raise ConfigError(f"Type conflict: {part!r} is already defined as a value")
                sub = curr.entries[part]
                assert isinstance(sub, BlockScope)
                curr = sub
            else:
                sub = BlockScope(parent_scope=curr)
                curr.entries[part] = sub
                curr.key_kinds[part] = 'BLOCK'
                curr = sub
        return curr

    def parse_statement(self, scope: BlockScope) -> None:
        path = self.parse_path()
        tok = self.current()

        if tok.type == '=':
            self.consume('=')
            expr = self.parse_expr()
            target_scope = self.ensure_subscope(scope, path[:-1])
            last_key = path[-1]
            if last_key in target_scope.entries and target_scope.key_kinds[last_key] == 'BLOCK':
                raise ConfigError(f"Type conflict: cannot overwrite block {last_key!r} with a value")
            target_scope.entries[last_key] = expr
            target_scope.key_kinds[last_key] = 'EXPR'
            return

        # Otherwise it must be a block definition (with optional inheritance and optional newlines before '{')
        parent_path: list[str] | None = None
        if tok.type == ':':
            self.consume(':')
            parent_path = self.parse_path()

        self.skip_newlines()
        if self.current().type != '{':
            t = self.current()
            raise ConfigError(f"Expected '=' or '{{' after path, got {t.type} at {t.line}:{t.col}")
        self.consume('{')

        block_scope = self.ensure_subscope(scope, path)
        if parent_path is not None:
            if block_scope.inherit_paths:
                raise ConfigError(f"Multiple inheritance specifications for block {'.'.join(path)}")
            block_scope.inherit_paths.append(parent_path)

        self.skip_separators()
        while self.current().type != '}':
            if self.current().type == 'EOF':
                raise ConfigError("Unclosed '{' before end of file")
            self.parse_statement(block_scope)
            if self.current().type not in ('NEWLINE', ';', '}'):
                t = self.current()
                raise ConfigError(
                    f"Expected separator or '}}' after statement in block, got {t.type} at {t.line}:{t.col}"
                )
            self.skip_separators()
        self.consume('}')

    def parse_expr(self) -> ExprNode:
        terms = [self.parse_term()]
        # '+' cannot be preceded by a newline, only followed by optional newlines
        while self.current().type == '+':
            self.consume('+')
            self.skip_newlines()
            terms.append(self.parse_term())
        return ExprNode(terms=terms)

    def parse_term(self) -> TermNode:
        tok = self.current()
        if tok.type == 'NUMBER':
            self.consume('NUMBER')
            return LiteralNode(tok.value)
        if tok.type == 'IDENT':
            self.consume('IDENT')
            if tok.value == 'true':
                return LiteralNode(True)
            if tok.value == 'false':
                return LiteralNode(False)
            if tok.value == 'null':
                return LiteralNode(None)
            raise ConfigError(f"Unexpected identifier {tok.value!r} in expression at {tok.line}:{tok.col}")
        if tok.type == 'STRING':
            self.consume('STRING')
            parsed_parts: list[tuple[str, Any]] = []
            for kind, val in tok.value:
                if kind == 'LIT':
                    parsed_parts.append(('LIT', val))
                else:
                    parsed_parts.append(('REF', parse_ref_content(val)))
            return StringNode(parts=parsed_parts)
        if tok.type == 'REF':
            self.consume('REF')
            return RefNode(spec=parse_ref_content(tok.value))
        if tok.type == '[':
            return self.parse_list()

        raise ConfigError(f"Unexpected token {tok.type} in expression at {tok.line}:{tok.col}")

    def parse_list(self) -> ListNode:
        self.consume('[')
        self.skip_newlines()
        elements: list[ExprNode] = []
        while self.current().type != ']':
            if self.current().type == 'EOF':
                raise ConfigError("Unclosed '[' before end of file")
            elements.append(self.parse_expr())
            self.skip_newlines()
            if self.current().type == ',':
                self.consume(',')
                self.skip_newlines()
                if self.current().type == ',':
                    t = self.current()
                    raise ConfigError(f"Unexpected ',' in list at {t.line}:{t.col}")
            elif self.current().type == ']':
                break
            else:
                t = self.current()
                raise ConfigError(f"Expected ',' or ']' in list, got {t.type} at {t.line}:{t.col}")
        self.consume(']')
        return ListNode(elements=elements)


# --- Evaluator ---

class Evaluator:
    def __init__(self, root: BlockScope, env: dict[str, str]):
        self.root = root
        self.env = env
        self.resolving_inheritance: set[int] = set()
        self.resolved_inheritance: set[int] = set()
        # (id(scope), key) currently being evaluated
        self.evaluating_keys: set[tuple[int, str]] = set()
        self.evaluated_cache: dict[tuple[int, str], Any] = {}

    def resolve_all_inheritance(self, scope: BlockScope) -> None:
        self._resolve_scope_inheritance(scope)
        for k, v in list(scope.entries.items()):
            if isinstance(v, BlockScope):
                self.resolve_all_inheritance(v)

    def _is_ancestor_or_self(self, target: BlockScope, candidate: BlockScope) -> bool:
        curr: BlockScope | None = candidate
        while curr is not None:
            if curr is target:
                return True
            curr = curr.parent_scope
        return False

    def _resolve_scope_inheritance(self, scope: BlockScope) -> None:
        sid = id(scope)
        if sid in self.resolved_inheritance:
            return
        if sid in self.resolving_inheritance:
            raise ConfigError("Circular block inheritance detected")

        self.resolving_inheritance.add(sid)

        # Ensure ancestors have their inheritance resolved first so lexical lookup works accurately
        if scope.parent_scope is not None and id(scope.parent_scope) not in self.resolved_inheritance:
            # Only resolve parent if not currently in resolving_inheritance; if it is, that's fine
            # as long as parent finished merging its own parents before descending.
            pass

        if scope.inherit_paths:
            parent_path = scope.inherit_paths[0]
            if scope.parent_scope is None:
                raise ConfigError("Root cannot inherit")
            base_scope = self.lookup_block(scope.parent_scope, parent_path)
            if self._is_ancestor_or_self(scope, base_scope) or self._is_ancestor_or_self(base_scope, scope):
                raise ConfigError("Cannot inherit from self or ancestor/descendant block")
            self._resolve_scope_inheritance(base_scope)
            # Also recursively resolve any child blocks inside base_scope
            for v in list(base_scope.entries.values()):
                if isinstance(v, BlockScope):
                    self.resolve_all_inheritance(v)

            self._merge_from_parent(scope, base_scope)

        self.resolving_inheritance.remove(sid)
        self.resolved_inheritance.add(sid)

    def _merge_from_parent(self, child: BlockScope, parent: BlockScope) -> None:
        for k, pv in parent.entries.items():
            p_kind = parent.key_kinds[k]
            if k not in child.entries:
                child.key_kinds[k] = p_kind
                if isinstance(pv, BlockScope):
                    child.entries[k] = pv.clone_for_child(child)
                else:
                    child.entries[k] = pv
            else:
                c_kind = child.key_kinds[k]
                if p_kind != c_kind:
                    raise ConfigError(f"Type conflict in inheritance for key {k!r}")
                if p_kind == 'BLOCK':
                    c_sub = child.entries[k]
                    assert isinstance(c_sub, BlockScope) and isinstance(pv, BlockScope)
                    # Resolve child sub-block's own inheritance if any before merging parent sub-block
                    self._resolve_scope_inheritance(c_sub)
                    self._merge_from_parent(c_sub, pv)
                else:
                    # Child expression overrides parent expression
                    pass

    def lookup_block(self, start_scope: BlockScope, path: list[str]) -> BlockScope:
        head = path[0]
        curr_scope: BlockScope | None = start_scope
        found_scope: BlockScope | None = None

        while curr_scope is not None:
            # Make sure curr_scope's inheritance is resolved so all its keys are present
            if id(curr_scope) not in self.resolved_inheritance and id(curr_scope) not in self.resolving_inheritance:
                self._resolve_scope_inheritance(curr_scope)
            if head in curr_scope.entries:
                found_scope = curr_scope
                break
            curr_scope = curr_scope.parent_scope

        if found_scope is None:
            raise ConfigError(f"Undefined block reference: {'.'.join(path)}")

        node: BlockScope | ExprNode = found_scope.entries[head]
        for part in path[1:]:
            if not isinstance(node, BlockScope):
                raise ConfigError(f"Cannot traverse non-block in {'.'.join(path)}")
            if id(node) not in self.resolved_inheritance and id(node) not in self.resolving_inheritance:
                self._resolve_scope_inheritance(node)
            if part not in node.entries:
                raise ConfigError(f"Undefined key {part!r} in block reference {'.'.join(path)}")
            node = node.entries[part]

        if not isinstance(node, BlockScope):
            raise ConfigError(f"Reference {'.'.join(path)} does not point to a block")
        return node

    def lookup_value(self, start_scope: BlockScope, path: list[str]) -> Any:
        head = path[0]
        curr_scope: BlockScope | None = start_scope
        found_scope: BlockScope | None = None

        while curr_scope is not None:
            if head in curr_scope.entries:
                found_scope = curr_scope
                break
            curr_scope = curr_scope.parent_scope

        if found_scope is None:
            raise ConfigError(f"Undefined variable reference: {'.'.join(path)}")

        curr = found_scope
        for part in path[:-1]:
            entry = curr.entries.get(part)
            if not isinstance(entry, BlockScope):
                raise ConfigError(f"Cannot traverse non-block {part!r} in {'.'.join(path)}")
            curr = entry

        last_key = path[-1]
        if last_key not in curr.entries:
            raise ConfigError(f"Undefined variable reference: {'.'.join(path)}")

        target = curr.entries[last_key]
        if isinstance(target, BlockScope):
            raise ConfigError(f"Cannot reference block {'.'.join(path)} as a value")

        return self.eval_key(curr, last_key)

    def eval_key(self, scope: BlockScope, key: str) -> Any:
        cache_key = (id(scope), key)
        if cache_key in self.evaluated_cache:
            val = self.evaluated_cache[cache_key]
            return list(val) if isinstance(val, list) else val
        if cache_key in self.evaluating_keys:
            raise ConfigError(f"Circular variable reference involving {key!r}")

        self.evaluating_keys.add(cache_key)
        expr = scope.entries[key]
        assert isinstance(expr, ExprNode)
        val = self.eval_expr(scope, expr)
        self.evaluating_keys.remove(cache_key)
        self.evaluated_cache[cache_key] = val
        return list(val) if isinstance(val, list) else val

    def eval_expr(self, scope: BlockScope, expr: ExprNode) -> Any:
        result = self.eval_term(scope, expr.terms[0])
        for term in expr.terms[1:]:
            right = self.eval_term(scope, term)
            result = self.apply_plus(result, right)
        return result

    def apply_plus(self, left: Any, right: Any) -> Any:
        # Reject bools explicitly since isinstance(True, int) is True in Python
        if isinstance(left, bool) or isinstance(right, bool):
            raise ConfigError("Cannot use '+' operator with boolean values")
        if isinstance(left, (int, float)) and isinstance(right, (int, float)):
            return left + right
        if isinstance(left, str) and isinstance(right, str):
            return left + right
        if isinstance(left, list) and isinstance(right, list):
            return left + right
        raise ConfigError(
            f"Type mismatch for '+' operator: {type(left).__name__} and {type(right).__name__}"
        )

    def eval_ref_spec(self, scope: BlockScope, spec: RefSpec) -> Any:
        if spec.kind == 'ENV':
            if spec.has_default:
                val = self.env.get(spec.env_var, "")
                return val if val != "" else spec.default_val
            else:
                if spec.env_var not in self.env:
                    raise ConfigError(f"Undefined environment variable: {spec.env_var}")
                return self.env[spec.env_var]
        else:
            return self.lookup_value(scope, spec.path)

    def eval_term(self, scope: BlockScope, term: TermNode) -> Any:
        if isinstance(term, LiteralNode):
            return term.value
        if isinstance(term, RefNode):
            return self.eval_ref_spec(scope, term.spec)
        if isinstance(term, ListNode):
            return [self.eval_expr(scope, el) for el in term.elements]
        if isinstance(term, StringNode):
            out: list[str] = []
            for kind, part in term.parts:
                if kind == 'LIT':
                    out.append(part)
                else:
                    val = self.eval_ref_spec(scope, part)
                    out.append(self.format_for_interpolation(val))
            return ''.join(out)
        raise ConfigError("Unknown term node")

    def format_for_interpolation(self, val: Any) -> str:
        if val is None:
            return "null"
        if isinstance(val, bool):
            return "true" if val else "false"
        if isinstance(val, (int, float, str)):
            return str(val)
        raise ConfigError(f"Cannot interpolate {type(val).__name__} into string")

    def evaluate_scope_to_dict(self, scope: BlockScope) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in scope.entries.items():
            if isinstance(v, BlockScope):
                result[k] = self.evaluate_scope_to_dict(v)
            else:
                result[k] = self.eval_key(scope, k)
        return result


def parse_config(text: str, env: dict[str, str] | None = None) -> dict[str, Any]:
    if not isinstance(text, str):
        raise ConfigError("Config text must be a string")
    env_dict = dict(env) if env is not None else {}
    tokens = tokenize(text)
    parser = Parser(tokens)
    root_scope = parser.parse_root()
    evaluator = Evaluator(root_scope, env_dict)
    evaluator.resolve_all_inheritance(root_scope)
    return evaluator.evaluate_scope_to_dict(root_scope)

=== FILE: tests/test_hidden.py ===
import unittest
from config_parser import parse_config, ConfigError


class TestConfigParserHidden(unittest.TestCase):

    def test_01_basic_types_and_comments(self):
        cfg = """
        # Line comment with #
        // Line comment with //
        /* Multi-line
           block comment */
        int_val = 42
        neg_int = -100
        pos_int = +7
        zero_val = -0
        float_val = 3.1415
        exp_val = -2.5e-2
        bool_t = true
        bool_f = false
        null_val = null
        str_val = "hello\\nworld\\t\\"escaped\\"\\\\\\$100\\r"
        empty_list = []
        nested_list = [1, [2, 3,], ]
        """
        res = parse_config(cfg)
        self.assertEqual(res["int_val"], 42)
        self.assertIs(type(res["int_val"]), int)
        self.assertEqual(res["neg_int"], -100)
        self.assertEqual(res["pos_int"], 7)
        self.assertEqual(res["zero_val"], 0)
        self.assertAlmostEqual(res["float_val"], 3.1415)
        self.assertAlmostEqual(res["exp_val"], -0.025)
        self.assertIs(res["bool_t"], True)
        self.assertIs(res["bool_f"], False)
        self.assertIsNone(res["null_val"])
        self.assertEqual(res["str_val"], "hello\nworld\t\"escaped\"\\$100\r")
        self.assertEqual(res["empty_list"], [])
        self.assertEqual(res["nested_list"], [1, [2, 3]])

    def test_02_semicolons_and_reserved_words_as_keys(self):
        cfg = """
        ;;
        true = false; false = true; null = "not_null";
        block.true.null {
            false = [true, false, null]
        };
        ref_test = ${block.true.null.false}
        """
        res = parse_config(cfg)
        self.assertIs(res["true"], False)
        self.assertIs(res["false"], True)
        self.assertEqual(res["null"], "not_null")
        self.assertEqual(res["block"]["true"]["null"]["false"], [True, False, None])
        self.assertEqual(res["ref_test"], [True, False, None])

    def test_03_deep_merge_and_overwrites(self):
        cfg = """
        a.b.x = 1
        a {
            b {
                y = 2
                x = 10
            }
            c = 3
        }
        a.b.z = 30
        """
        res = parse_config(cfg)
        self.assertEqual(res, {
            "a": {
                "b": {"x": 10, "y": 2, "z": 30},
                "c": 3,
            }
        })

    def test_04_operators_and_line_continuation(self):
        cfg = """
        num_sum = 10 +
                  20 + -5
        float_sum = 10 + 0.5
        str_concat = "foo" +
                     "bar" + "baz"
        list_concat = [1, 2] +
                      [3] + []
        """
        res = parse_config(cfg)
        self.assertEqual(res["num_sum"], 25)
        self.assertIs(type(res["num_sum"]), int)
        self.assertEqual(res["float_sum"], 10.5)
        self.assertIs(type(res["float_sum"]), float)
        self.assertEqual(res["str_concat"], "foobarbaz")
        self.assertEqual(res["list_concat"], [1, 2, 3])

    def test_05_interpolation_and_escaped_interpolation(self):
        cfg = """
        s = "str"
        i = 99
        f = 1.5
        bt = true
        bf = false
        n = null
        combined = "${s}|${i}|${f}|${bt}|${bf}|${n}|\\${not_interp}"
        """
        res = parse_config(cfg)
        self.assertEqual(res["combined"], "str|99|1.5|true|false|null|${not_interp}")

    def test_06_lexical_scope_and_shadowing(self):
        cfg = """
        x = "global_x"
        y = "global_y"
        db {
            host = "db_global"
            port = 5432
        }
        service {
            x = "service_x"
            inner {
                val_x = ${x}
                val_y = ${y}
                val_db = "${db.host}:${db.port}"
            }
        }
        """
        res = parse_config(cfg)
        self.assertEqual(res["service"]["inner"]["val_x"], "service_x")
        self.assertEqual(res["service"]["inner"]["val_y"], "global_y")
        self.assertEqual(res["service"]["inner"]["val_db"], "db_global:5432")

    def test_07_shadowing_does_not_fallback_on_partial_match(self):
        cfg = """
        db {
            host = "global_host"
            port = 5432
        }
        app {
            db {
                host = "local_host"
            }
            # app.db exists and shadows root db, so db.port must fail!
            target_port = ${db.port}
        }
        """
        with self.assertRaises(ConfigError):
            parse_config(cfg)

    def test_08_forward_references_and_list_immutability(self):
        cfg = """
        combined = ${base_list} + [4]
        base_list = ${initial} + [2, 3]
        initial = [1]
        """
        res = parse_config(cfg)
        self.assertEqual(res["initial"], [1])
        self.assertEqual(res["base_list"], [1, 2, 3])
        self.assertEqual(res["combined"], [1, 2, 3, 4])

    def test_09_env_variables(self):
        cfg = """
        a = ${env:HOST}
        b = ${env:PORT:-8080}
        c = ${env:EMPTY_VAR:-fallback}
        d = ${env:MISSING_VAR:-}
        e = "url=http://${env:HOST}:${env:PORT:-9000}/api"
        """
        env = {"HOST": "127.0.0.1", "EMPTY_VAR": ""}
        res = parse_config(cfg, env=env)
        self.assertEqual(res["a"], "127.0.0.1")
        self.assertEqual(res["b"], "8080")
        self.assertEqual(res["c"], "fallback")
        self.assertEqual(res["d"], "")
        self.assertEqual(res["e"], "url=http://127.0.0.1:9000/api")

        # Missing required env var should raise ConfigError
        with self.assertRaises(ConfigError):
            parse_config("x = ${env:NOT_SET}", env={})

    def test_10_inheritance_and_late_binding(self):
        cfg = """
        global_prefix = "v1"

        base_tpl {
            name = "default"
            port = 80
            endpoint = "${global_prefix}/${name}:${port}"
            nested {
                enabled = true
                 label = "lbl-${name}"
            }
        }

        mid_tpl : base_tpl {
            port = 8080
            nested {
                retries = 3
            }
        }

        prod_svc : mid_tpl {
            global_prefix = "v2"
            name = "auth"
        }
        """
        res = parse_config(cfg)
        self.assertEqual(res["base_tpl"]["endpoint"], "v1/default:80")
        self.assertEqual(res["base_tpl"]["nested"]["label"], "lbl-default")
        self.assertEqual(res["mid_tpl"]["endpoint"], "v1/default:8080")
        self.assertEqual(res["mid_tpl"]["nested"], {"enabled": True, "label": "lbl-default", "retries": 3})
        self.assertEqual(res["prod_svc"]["endpoint"], "v2/auth:8080")
        self.assertEqual(res["prod_svc"]["nested"], {"enabled": True, "label": "lbl-auth", "retries": 3})

    def test_11_cycle_detection_variables_and_blocks(self):
        # Direct variable cycle
        with self.assertRaises(ConfigError):
            parse_config("a = ${a}")

        # Mutual variable cycle
        with self.assertRaises(ConfigError):
            parse_config("a = ${b}\nb = ${c}\nc = ${a}")

        # Block inheritance cycle
        with self.assertRaises(ConfigError):
            parse_config("a : b {}\nb : a {}")

        # Self / ancestor inheritance cycle
        with self.assertRaises(ConfigError):
            parse_config("a { b : a {} }")

        with self.assertRaises(ConfigError):
            parse_config("a : a.b { b {} }")

    def test_12_type_conflicts_and_invalid_operations(self):
        # Overwriting block with scalar
        with self.assertRaises(ConfigError):
            parse_config("a { x = 1 }\na = 2")

        # Overwriting scalar with block
        with self.assertRaises(ConfigError):
            parse_config("a = 2\na { x = 1 }")

        # Traversing scalar in dotted path
        with self.assertRaises(ConfigError):
            parse_config("a = 2\na.b = 3")

        # Inheritance type conflict (block in parent, scalar in child)
        with self.assertRaises(ConfigError):
            parse_config("p { sub { x = 1 } }\nc : p { sub = 10 }")

        # Invalid '+' combinations
        for bad_expr in [
            '"str" + 10',
            '10 + "str"',
            'true + false',
            'true + 1',
            '[1] + 2',
            'null + null',
        ]:
            with self.assertRaises(ConfigError, msg=f"Failed to reject: {bad_expr}"):
                parse_config(f"x = {bad_expr}")

        # Interpolating list or block into string
        with self.assertRaises(ConfigError):
            parse_config('arr = [1, 2]\ns = "val: ${arr}"')

        # Referencing block as value
        with self.assertRaises(ConfigError):
            parse_config('b { x = 1 }\nv = ${b}')

    def test_13_syntax_and_lexical_errors(self):
        bad_configs = [
            'a = 01',                  # leading zero in int
            'a = -007',                # leading zero in negative int
            'a = 01.5',                # leading zero in float
            'a = .5',                  # leading dot in float
            'a = 5.',                  # trailing dot in float
            'a = "unterminated',       # unterminated string
            'a = "line\nbreak"',       # raw newline in string
            'a = "bad \\q escape"',    # invalid escape
            '/* unclosed comment',     # unclosed block comment
            'a = 1 b = 2',             # missing separator between statements
            'a..b = 1',                # double dot in path
            '.a = 1',                  # leading dot in path
            'a. = 1',                  # trailing dot in path
            'a = [1,,2]',              # double comma in list
            'a = [,]',                 # empty comma in list
            'a = "hello"\n + "world"', # newline before '+'
            'b : p1 {}\nb : p2 {}',    # multiple inheritance on same block
        ]
        for cfg in bad_configs:
            with self.assertRaises(ConfigError, msg=f"Failed to raise ConfigError for:\n{cfg}"):
                parse_config(cfg)

    def test_14_hyphenated_identifiers_and_subtraction_lookalike(self):
        cfg = """
        my-service_1 {
            max-retry-count = 5
            base-val = 10
            calc = ${base-val} + -3
            ref-val = ${my-service_1.max-retry-count}
        }
        """
        res = parse_config(cfg)
        self.assertEqual(res["my-service_1"]["max-retry-count"], 5)
        self.assertEqual(res["my-service_1"]["calc"], 7)
        self.assertEqual(res["my-service_1"]["ref-val"], 5)

    def test_15_inheritance_with_pre_existing_dotted_definitions(self):
        cfg = """
        tpl {
            a = 1
            b = 2
            nested {
                x = 10
                y = 20
            }
        }
        # Define part of child before the block with ': tpl'
        child.a = 100
        child.nested.x = 1000
        child : tpl {
            b = 200
        }
        child.nested.z = 3000
        """
        res = parse_config(cfg)
        self.assertEqual(res["child"], {
            "a": 100,
            "b": 200,
            "nested": {
                "x": 1000,
                "y": 20,
                "z": 3000,
            }
        })


if __name__ == "__main__":
    unittest.main()

=== END ===

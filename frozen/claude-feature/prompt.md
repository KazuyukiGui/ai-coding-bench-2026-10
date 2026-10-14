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

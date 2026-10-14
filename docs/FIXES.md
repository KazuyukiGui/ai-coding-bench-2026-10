# 見直しによる手直しの記録（凍結前）

方針: high（正しく解いても落ちる）・medium（妥当な別解が落ちる恐れ）は必ず直す。課題文のわかりにくさの low は課題文だけ直す。試験の書き方の low は直さない（後から試験を強めると難しさが変わるため）。直したのは wl（Claude Opus 5.5・このセッション）。

| 課題 | 指摘元 | 重さ | 直したこと |
|---|---|---|---|
| astra-feature | Claude | high | test_05 の期待値を [(0,3),(9,10)] → [(0,3),(4,7),(9,10)]。模範解答も指摘と同じ値を返していた（試験の誤り） |
| astra-feature | Claude | medium | 課題文に「requests は list 型でなければならない（タプル・辞書・None は ValueError）」を明記 |
| astra-bugfix | Claude | low | 課題文に remaining＝残数量・available＝利用可能数量の対応を明記 |
| astra-spec | Claude | low | スナップショットの例が「形を示す例で、操作例を順に適用した結果ではない」と明記 |
| astra-multifile | Claude | low | 「無条件には無視しません」→「無視せず、通常のレコードとして検証します」 |
| astra-multifile | Claude | low×3 | 試験の書き方の指摘（使わない変数・常に真の assert・空の検証）。方針により直さない |
| claude-spec | wl の機械検証 | high | 「00 00 01 01 00」の期待値に12月31日が入っていた（月は1月だけ）→ 1/1・1/7・1/14 に修正 |
| claude-spec | wl の機械検証 | high | prev_before(2105-01-01) は探索範囲に 2104-02-29 が入るので None ではない → 2104-02-29 に修正 |
| claude-spec | Sol | medium | 性能の試験の上限を 4秒 → 20秒（模範解答 0.04秒・分単位の総当たり 約70秒、mini 実測） |

見直しで指摘が無かった組: astra-*（Argon は4題とも0件）・claude-feature・claude-multifile（Sol・Argon とも0件）・claude-spec（Argon 0件）。
注: claude-spec の試験の誤り2件は、どの審査員も指摘せず、模範解答を動かして初めて見つかった。Argon は astra-feature の high（試験の誤り）も見逃した。
| claude-bugfix | wl の機械検証 | high | test_with_rule の4/1の合計 5800 → 6800（手計算: 3/31 9:00〜4/1 8:00 上限なし＝昼5,200＋夜1,000、21:00〜23:30＝600。模範解答が正しく試験の誤り） |
凍結 2026-10-14 15:30:30 8題
| argon-bugfix | wl の機械検証 | medium | 「0x_10」を誤りとする試験を削除。課題文は「Python の数値リテラルと同様」で、Python では 0x_10 は有効（読みが割れる） |
| argon-bugfix | wl の機械検証 | high | 行継続の試験から「継続中のコメントだけの行」を削除。課題文は「コメントだけの行で継続は終わる」と定めており、試験は継続することを期待していた（模範解答が正しい） |
| argon-multifile | wl の機械検証 | high | test_14 の前提「target は3ユニット」が処理順（priority 降順）と食い違い、target が先に4ユニットを取っていた → 先に取らせる予約の priority を5にして試験の意図を保った（模範解答が正しい） |
| argon-bugfix | Claude | high | 課題文に「数値の形なのに Python の数値リテラルとして不正な値（1__000・1000_・1._5・1e5_ 等）は文字列にせず ConfigError」を明記。試験と模範解答はこの扱いだが、課題文の読みでは str になった |
| argon-bugfix | Claude | low×2 | 課題文: `\$` の崩れた括弧書きを「= と := のどちらでも $ になる」に書き直し／参照の型引き継ぎを「深いコピー」と明記（試験は assertIsNot） |
| argon-spec | Claude | medium | 3.5.2 の「親の…内部の式が解決された状態」を「キーの構成だけ解決・式は未評価」に改め、多段継承でも最終的な子のスコープで評価と明記（test_10） |
| argon-spec | Claude | medium | 2.4 項6 の「辞書ならディープコピー／辞書は代入不可」の矛盾を「辞書の参照は単独でも式やリストの中でも ConfigError」に一本化（test_12） |
| argon-spec | Claude | medium | 3.5.1 に「祖先」の継承も ConfigError と追加（test_11 の a { b : a {} }） |
| argon-spec | Claude | medium | 3.5.2 に「継承で引き継いだ内容は優先度が最も低く、同じパスへの定義は形式・前後を問わず親のコピーより優先」と追加（test_15） |
| argon-spec | Claude | low | 4. 設定例の壊れた最後の行と未評価の返り値を、模範解答の実際の返り値に差し替え（sub = "default" を追加） |
| argon-spec | Claude | low | test_13 の複数継承の試験が未定義参照で落ちている指摘。試験の書き方の low なので直さない |
| argon-feature | Claude | medium | given の壊れた `def _ validate_slot`（SyntaxError・中身は後ろの定義と同じ）を削除し、given が import できる形に |
| argon-feature | Claude | low | 試験のコメントと値の食い違い。試験の書き方の low なので直さない |
| argon-multifile | Claude | low×2 | 課題文: 旧 cancel は「残しても消してもよい」と明記／release が返すのは「削除直前に保存されていた（部分解放後の）Allocation」と明記 |
確認 2026-10-14 17時台: 4題とも模範解答で全件合格（16・15・16・15件）。Sol の見直し（18:33〜）はこの版に対して行う
凍結 2026-10-14 18:38:06 Argon の4題（FROZEN-2.sha256）。Sol の見直しは4題とも0件

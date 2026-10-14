# AI コーディング比較 2026-10（Claude / Codex / Gemini 4 Argon）

Claude Opus 5.5、GPT-5.6 Sol、GPT-6 Astra、Gemini 4 Argon に、同じ12題のコーディング課題を計120回解かせ、隠し試験で採点した記録です。
題は Claude、Astra、Argon が4題ずつ作り、作り手以外の2社が見直してから凍結しました。

記事: https://zenn.dev/gui/articles/ai-coding-bench-claude-codex-gemini

## 結果

| モデル | 全件合格 | 試験の平均合格率 | 時間の中央値 | 出力トークンの中央値（思考分を含む） |
|---|---|---|---|---|
| Claude Opus 5.5 | 36/36 | 100% | 42秒 | 5,367 |
| GPT-5.6 Sol | 33/36 | 99.6% | 31秒 | 3,216 |
| GPT-6 Astra | 11/12 | 99.5% | 59秒 | 2,818 |
| Gemini 4 Argon | 35/36 | 97.2% | 122秒 | 11,084 |

- 12題のうち10題は、4モデルとも全回で全件合格でした
- 不合格は5回だけです（argon-bugfix で Sol 2回・Astra 1回・Argon 1回、claude-spec で Sol 1回）。Sol と Astra が落とした試験は回ごとに違います
- Argon の不合格1回（argon-bugfix の argon-1）は、答えのコードの1行の字下げが1文字ずれた構文エラーで、試験を読み込めず0件合格です。答えの解析の失敗ではありません
- Astra は ChatGPT Plus の利用枠に何度も当たったため、各題1回です。回数が違うので、ほかのモデルと数字を直接比べないでください
- 1回ごとの結果は `results.csv`、答えと採点は `runs/` にあります

## 条件

- 同じ課題文と添付ファイルを本文として渡し、変更後のファイル全体を返させる（リポジトリ、ネット、実行環境は使わせない）
- 考える深さはすべて high。出力の上限は Claude と Argon を65,536トークン
- Claude: `claude -p`（ツールなし）／Sol と Astra: `codex exec`（読み取り専用、シェルなし）／Argon: Gemini API の GenerateContent
- Argon の36回のうち30回はストリーミングなし、6回（argon-bugfix と argon-spec）はストリーミングで実行しました。ストリーミングなしの REST は1回32,768トークンまでのため、この6回は最初の実行で答えが空になりました。その旧6回は `runs-excluded/argon-rest-32k/` に残しています
- 実行日 2026-10-14〜15。Claude Code 2.1.287、codex-cli 0.153.4、Python 3.12

## 中身

| パス | 内容 |
|---|---|
| `frozen/<作り手>-<分類>/` | 凍結した課題（課題文 `prompt.md`、渡したファイル `given/`、模範解答 `ref/`、隠し試験 `tests/`） |
| `FROZEN-1.sha256` `FROZEN-2.sha256` | 凍結時の指紋。`cd frozen && sha256sum -c ../FROZEN-*.sha256` で照合できる |
| `runs/<課題>/<モデル>-<回>/` | 解く側への依頼文、答え、採点結果、トークン数と時間 |
| `runs-excluded/` | 集計から外した回（上記の旧6回） |
| `authoring/` `AUTHORING.md` | 題を作らせた指示と生の答え |
| `reviews/` `REVIEW.md` | 見直しの指示と各社の指摘 |
| `docs/FIXES.md` | 見直しと機械検証で凍結前に直した内容 |
| `bench.py` `run_all.sh` `run_codex.sh` `author.sh` `review.sh` `argon.sh` | 実行と採点のスクリプト |

## 再現

採点だけなら Python 3.11 以上で動きます。

```bash
python3 bench.py grade frozen/argon-bugfix runs/argon-bugfix/argon-2/answer.md
python3 bench.py validate frozen/claude-spec   # 模範解答は全件合格、最初のファイルは不合格になることを確認
```

解かせ直すには各社の CLI と鍵が要ります（`claude`、`codex`、環境変数 `GEMINI_API_KEY`）。

```bash
bash run_all.sh claude 3      # Claude または Argon（argon）
bash run_codex.sh sol 3       # Sol または Astra（astra）
```

済んだ回は飛ばすので、`runs/` を空にしてから回してください。

## 注意

- 題は12題で、不合格が出たのは2題です。モデルの順位を付けられる規模ではありません
- 実行の仕組みと試験の手直しは Claude Code（Claude Opus 5.5）が担いました
- 時間は目安です。Claude と Codex は CLI 経由、Argon は API に直接つないでいて経路が違い、各社のサービスの混み具合でも変わります
- トークン数は各社の API の記録の値で、数え方は各社で同じとは限りません。Claude と Codex の出力は思考分を含み、Argon は出力と思考が別に記録されるので、表では足した値を出しています

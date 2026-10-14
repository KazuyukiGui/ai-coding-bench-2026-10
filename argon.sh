#!/usr/bin/env bash
# argon.sh — Gemini 4 Argon（gemini-4-argon）に質問やファイルを渡して答えを受け取る（AI コーディング比較で使った版）
# 料金: 無料枠なし・従量課金。100万トークンあたり 入力$2・出力$10（2026-11-30まで）→ 入力$4・出力$20（2026-12-01から）。出力には考える分のトークンも入る
#   https://ai.google.dev/gemini-api/docs/pricing
#
# 使い方:
#   scripts/argon.sh "質問"
#   echo "質問" | scripts/argon.sh
#   scripts/argon.sh -f 原稿.md -f 補足.md "この原稿の論理の穴を指摘して"   ファイルを添えて聞く（何本でも）
#   scripts/argon.sh -s "辛口の査読者として答える" -f a.md "見直して"       役割の指示（システム指示）
#   scripts/argon.sh -e low "…"     考える深さ low|medium|high（既定 high・--web の時は既定 medium）
#   scripts/argon.sh --web "…"      Google 検索を使って答える（根拠の URL を末尾に付ける・月5,000回まで無料、超えると1,000回あたり$14）
#   scripts/argon.sh -o 出力.md "…" 答えをファイルにも書く
#   ARGON_TIMEOUT=1200 scripts/argon.sh …  通信の待ち時間の上限（秒・既定600）
#   ARGON_MAX_OUTPUT=65536 scripts/argon.sh …  出力の上限トークン（考えた分を含む・未指定は API の既定＝32,768 で切れた）
#   ARGON_STREAM=1 ARGON_MAX_OUTPUT=65536 scripts/argon.sh …  ストリーミングで呼ぶ（ストリーミングなしの REST は 65,536 を指定しても 32,768 で止まる）
#   scripts/argon.sh --month                                            今月の使用額の目安だけ出す
# 出力: 答えは標準出力、トークン数と額の目安は標準エラー
# 鍵: 環境変数 GEMINI_API_KEY
# 使用記録: ~/.local/state/ai-coding-bench/usage.tsv（日時・モデル・入力・出力・考えた分・額の目安）
# 注意: 文章は Google に送られる（有料枠なので学習には使われない）。個人情報は送らない
set -euo pipefail
MODEL="${ARGON_MODEL:-gemini-4-argon}"
LOGDIR="$HOME/.local/state/ai-coding-bench"; LOG="$LOGDIR/usage.tsv"
mkdir -p "$LOGDIR"

month_total() {
  local m; m=$(date +%Y-%m)
  [ -s "$LOG" ] || { echo "今月（$m）: 記録なし" >&2; return; }
  awk -F'\t' -v m="$m" 'index($1,m)==1{ a+=$6 } END{printf "今月（%s）の Argon: 約$%.3f（トークン数からの目安）\n", m, a}' "$LOG" >&2
}

FILES=(); SYS=""; LEVEL=""; WEB=0; OUTFILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    -f) [ -r "${2:-}" ] || { echo "読めないファイル: ${2:-}" >&2; exit 1; }; FILES+=("$2"); shift 2 ;;
    -s) SYS="${2:-}"; shift 2 ;;
    -e) case "${2:-}" in low|medium|high) LEVEL="$2" ;; *) echo "-e は low|medium|high" >&2; exit 1 ;; esac; shift 2 ;;
    --web) WEB=1; shift ;;
    -o) OUTFILE="${2:?}"; shift 2 ;;
    --month) month_total; exit 0 ;;
    -h|--help) sed -n '2,21p' "$0"; exit 0 ;;
    *) break ;;
  esac
done
Q="${*:-}"
[ -n "$Q" ] || { [ -t 0 ] && { sed -n '2,21p' "$0"; exit 1; }; Q=$(cat); }
[ -n "$Q" ] || { echo "質問が空" >&2; exit 1; }

KEY="${GEMINI_API_KEY:-}"
[ -n "$KEY" ] || { echo "鍵が無い: GEMINI_API_KEY を設定する" >&2; exit 2; }

TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
# ファイルは「=== ファイル名 ===」で区切って質問の前に並べる
: > "$TMP/prompt.txt"
for f in "${FILES[@]}"; do printf '=== %s ===\n' "$(basename "$f")" >> "$TMP/prompt.txt"; cat "$f" >> "$TMP/prompt.txt"; printf '\n\n' >> "$TMP/prompt.txt"; done
printf '%s\n' "$Q" >> "$TMP/prompt.txt"

# 深さの既定: 検索ありは medium（high＋検索は7分〜10分超かかった）、検索なしは high。-e で明示すればそれに従う
[ -n "$LEVEL" ] || { [ "$WEB" = 1 ] && LEVEL=medium || LEVEL=high; }
# 出力の上限（考えた分を含む）。未指定だと 32,768 で切れた（2026-10-14 課題作りで2回）。ARGON_MAX_OUTPUT で指定
jq -n --rawfile t "$TMP/prompt.txt" --arg s "$SYS" --arg l "$LEVEL" --argjson w "$WEB" --argjson mo "${ARGON_MAX_OUTPUT:-0}" \
  '{contents:[{role:"user",parts:[{text:$t}]}], generationConfig:({thinkingConfig:{thinkingLevel:$l}} + (if $mo>0 then {maxOutputTokens:$mo} else {} end))}
   + (if $s=="" then {} else {systemInstruction:{parts:[{text:$s}]}} end)
   + (if $w==1 then {tools:[{google_search:{}}]} else {} end)' > "$TMP/req.json"

# ARGON_STREAM=1 はストリーミングで呼ぶ。ストリーミングなしの REST は1回 32,768 トークンまで、ストリーミングは 65,536 まで（公式 generate-content/latest-model）。
# 届いた断片は1つの応答の形にまとめ直し、後ろの処理はそのまま使う（2026-10-15 AIコーディング比較で追加）
if [ "${ARGON_STREAM:-0}" = 1 ]; then
  code=$(curl -sS -N -m "${ARGON_TIMEOUT:-600}" -o "$TMP/res.sse" -w '%{http_code}' -X POST \
    "https://generativelanguage.googleapis.com/v1beta/models/$MODEL:streamGenerateContent?alt=sse" \
    -H "x-goog-api-key: $KEY" -H "Content-Type: application/json" -d @"$TMP/req.json") || code=000
  if [ "$code" = 200 ]; then
    sed -n 's/^data: //p' "$TMP/res.sse" | jq -s '{candidates:[{content:{parts:[.[].candidates[0].content.parts[]?]},
        finishReason:([.[].candidates[0].finishReason // empty] | last),
        groundingMetadata:([.[].candidates[0].groundingMetadata // empty] | last)}],
      usageMetadata:([.[].usageMetadata // empty] | last)}' > "$TMP/res.json"
  else
    cp "$TMP/res.sse" "$TMP/res.json" 2>/dev/null || true
  fi
else
  code=$(curl -sS -m "${ARGON_TIMEOUT:-600}" -o "$TMP/res.json" -w '%{http_code}' -X POST \
    "https://generativelanguage.googleapis.com/v1beta/models/$MODEL:generateContent" \
    -H "x-goog-api-key: $KEY" -H "Content-Type: application/json" -d @"$TMP/req.json") || code=000
fi
if [ "$code" != 200 ]; then
  echo "失敗 HTTP $code: $(jq -r '.error.message // empty' "$TMP/res.json" 2>/dev/null | head -c 400)" >&2; exit 3
fi

{
  jq -r '[.candidates[0].content.parts[]? | select(.thought != true) | .text // empty] | join("")' "$TMP/res.json"
  # Web 検索を使った時は、根拠にしたページを末尾に並べる
  jq -r '[.candidates[0].groundingMetadata.groundingChunks[]?.web | select(.) | "- \(.title // "") \(.uri)"] | if length>0 then "\n参照したページ（Google 検索）:\n" + join("\n") else empty end' "$TMP/res.json"
} > "$TMP/answer.txt"
cat "$TMP/answer.txt"
[ -n "$OUTFILE" ] && cp "$TMP/answer.txt" "$OUTFILE"
reason=$(jq -r '.candidates[0].finishReason // "?"' "$TMP/res.json")
[ "$reason" = STOP ] || echo "（終わり方: $reason — 途中で切れた・止められた可能性）" >&2

read -r IN OUT TH < <(jq -r '.usageMetadata | "\(.promptTokenCount // 0) \(.candidatesTokenCount // 0) \(.thoughtsTokenCount // 0)"' "$TMP/res.json")
if [ "$(date +%Y%m%d)" -lt 20261201 ]; then PIN=2; POUT=10; else PIN=4; POUT=20; fi
COST=$(awk -v i="$IN" -v o="$OUT" -v t="$TH" -v pi="$PIN" -v po="$POUT" 'BEGIN{printf "%.4f", (i*pi + (o+t)*po)/1e6}')
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$MODEL" "$IN" "$OUT" "$TH" "$COST" >> "$LOG"
echo "--- 入力 $IN・出力 $OUT・考えた分 $TH トークン／約\$$COST" >&2
month_total

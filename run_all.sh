#!/usr/bin/env bash
# run_all.sh <model> <回数> — 凍結した全課題を、指定モデルで回数ぶん解かせて採点し results.csv に追記する
# 済んだ回（runs/<課題>/<model>-<n>/grade.json がある）は飛ばすので、途中で止まっても続きから回せる
# 呼び出しが答えを返さずに失敗した回は採点しない（空の答えを不合格と数えない）。その回は _failed/<model>-callfail/ へ退避する。
# エラーなしで答えが空の回はモデル自身の不合格として採点し、grade.json を status=no-answer・passed=0 にする（2026-10-14 夜 追加）。
# 利用枠・支出上限・rate limit（429 等）の時はそこで止まる（終了コード2）。理由不明の失敗が2回続いても止まる（終了コード3）。2026-10-14 に Argon の支出上限で空の10回が不合格扱いになったため
set -uo pipefail
M="$1"; N="$2"; HERE="$(cd "$(dirname "$0")" && pwd)"
export TMPDIR="${TMPDIR:-/tmp}"
CSV="$HERE/results.csv"
fails=0
[ -s "$CSV" ] || echo "task,author,category,model,rep,ok,seconds,input_tokens,output_tokens,thinking_tokens,cost_usd,cost_usd_equiv,tool_items,run,passed,status,missing,lines" > "$CSV"
for T in "$HERE"/frozen/*/; do
  T="${T%/}"; name="$(basename "$T")"
  for i in $(seq 1 "$N"); do
    R="$HERE/runs/$name/$M-$i"; [ -s "$R/grade.json" ] && continue
    mkdir -p "$R"
    python3 "$HERE/bench.py" solve-prompt "$T" > "$R/prompt.md"
    python3 "$HERE/bench.py" call "$M" "$R/prompt.md" "$R" > "$R/call.json" 2> "$R/call.err" || true
    why=$(python3 - "$R" <<'PY'
import json, sys
from pathlib import Path
r = Path(sys.argv[1]); m = json.loads((r / "meta.json").read_text()) if (r / "meta.json").exists() else {}
a = (r / "answer.md").read_text().strip() if (r / "answer.md").exists() else ""
if a and m: sys.exit(0)
if m.get("ok") and not m.get("stderr"): sys.exit(0)  # エラーなしで答えが空＝モデル自身の不合格（例: Argon が出力上限を考える段階で使い切る）。採点して no-answer にする
t = (m.get("stderr") or "") + ((r / "call.err").read_text() if (r / "call.err").exists() else "")
lim = m.get("limit") or any(k in t.lower() for k in ("429", "spending cap", "rate limit", "usage limit", "quota"))
print("limit" if lim else "fail")
PY
)
    if [ -n "$why" ]; then
      mkdir -p "$HERE/_failed/$M-callfail"; mv "$R" "$HERE/_failed/$M-callfail/$name-$M-$i-$(date +%H%M%S)"
      if [ "$why" = limit ]; then echo "$(date +%H:%M:%S) 利用枠・上限で停止: $name $M-$i"; exit 2; fi
      fails=$((fails + 1)); [ "$fails" -ge 2 ] && { echo "$(date +%H:%M:%S) 呼び出し失敗が2回続いたので停止: $name $M-$i"; exit 3; }
      echo "$(date +%H:%M:%S) 呼び出し失敗（退避して次へ）: $name $M-$i"; continue
    fi
    fails=0
    python3 "$HERE/bench.py" grade "$T" "$R/answer.md" > "$R/grade.json" 2>> "$R/call.err" || echo '{"run":0,"passed":0,"status":"grade-error"}' > "$R/grade.json"
    python3 - "$R" <<'PY'
import json, sys
from pathlib import Path
r = Path(sys.argv[1])
if not (r / "answer.md").read_text().strip():
    g = json.loads((r / "grade.json").read_text())
    g.update(status="no-answer", passed_given_fallback=g.get("passed"), passed=0,
             note="答えが空。採点器は given で試験を回した（passed_given_fallback）。集計では 0 件合格")
    (r / "grade.json").write_text(json.dumps(g, ensure_ascii=False))
PY
    python3 - "$T" "$R" "$M" "$i" >> "$CSV" <<'EOF'
import json, sys, csv
from pathlib import Path
t, r, m, i = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
meta = json.loads((t / "meta.json").read_text())
c = json.loads((r / "meta.json").read_text()) if (r / "meta.json").exists() else {}
g = json.loads((r / "grade.json").read_text())
author, cat = t.name.split("-", 1)
csv.writer(sys.stdout).writerow([t.name, author, cat, m, i, c.get("ok"), c.get("seconds"), c.get("input_tokens"), c.get("output_tokens"),
    c.get("thinking_tokens"), c.get("cost_usd"), c.get("cost_usd_equiv"), c.get("tool_items"), g.get("run"), g.get("passed"),
    g.get("status"), ";".join(g.get("missing", [])), g.get("lines")])
EOF
    echo "$(date +%H:%M:%S) $name $M-$i $(python3 -c "import json;g=json.load(open('$R/grade.json'));print(g.get('passed'),'/',g.get('run'),g.get('status'))")"
  done
done
echo "$(date +%H:%M:%S) $M 完了"

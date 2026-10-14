#!/usr/bin/env python3
"""AI コーディング比較の実行・採点（2026-10-14〜）。

条件をそろえるため、どのモデルにもツールを使わせず、課題文と添付ファイルを本文で渡して
「ファイル全体」を返させる。採点は隠し試験（unittest）を一時フォルダで動かす。

使い方:
  bench.py call <model> <prompt.md> <out_dir>      1回呼ぶ（answer.md と meta.json を書く）
  bench.py parse <answer.md> <dest_dir>            「=== FILE: パス ===」形式を取り出す
  bench.py validate <task_dir>                     模範解答で全件合格・最初のファイルでは不合格を確認
  bench.py solve-prompt <task_dir>                 解く側への依頼文を標準出力へ
  bench.py grade <task_dir> <answer.md>            採点結果を JSON で標準出力へ
model: claude | sol | astra | argon
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ARGON = str(HERE / "argon.sh")
EMPTY = Path(os.environ.get("BENCH_EMPTY", Path.home() / ".cache/ai-coding-bench/empty"))
FILE_RE = re.compile(r"^=== FILE: (.+?) ===\s*$")
END_RE = re.compile(r"^=== END ===\s*$")
CALL_TIMEOUT = int(os.environ.get("BENCH_TIMEOUT", "1800"))


def parse_files(text):
    """「=== FILE: パス ===」で始まるブロックを {パス: 本文} にする。前後のコードフェンスは外す。"""
    files, cur, buf = {}, None, []

    def close():
        if cur is None:
            return
        lines = buf[:]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if lines and lines[0].lstrip().startswith("```"):
            lines.pop(0)
            if lines and lines[-1].strip().startswith("```"):
                lines.pop()
        files[cur] = "\n".join(lines) + "\n"

    for line in text.splitlines():
        m = FILE_RE.match(line)
        if m:
            close()
            cur, buf = m.group(1).strip(), []
        elif END_RE.match(line):
            close()
            cur, buf = None, []
        elif cur is not None:
            buf.append(line)
    close()
    return files


def safe_rel(p):
    q = Path(p)
    if q.is_absolute() or ".." in q.parts:
        raise ValueError(f"不正なパス: {p}")
    return q


def write_files(files, dest):
    dest = Path(dest)
    for rel, body in files.items():
        out = dest / safe_rel(rel)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")


def run_tests(workdir, test_file, timeout=300):
    """workdir をカレントにして test_file を動かし、件数を返す。"""
    runner = (
        "import json,sys,unittest\n"
        "s=unittest.defaultTestLoader.discover('.', pattern='test_hidden.py')\n"
        "r=unittest.TextTestRunner(stream=open('/dev/null','w'),verbosity=0).run(s)\n"
        "base=lambda t:getattr(t,'test_case',t).id()\n"
        "bad=sorted({base(t) for t,_ in r.failures+r.errors})\n"
        "print(json.dumps({'run':r.testsRun,'fail':len({base(t) for t,_ in r.failures}),'error':len({base(t) for t,_ in r.errors}),"
        "'skip':len(r.skipped),'bad':len(bad),'names':bad}))\n"
    )
    shutil.copy(test_file, Path(workdir) / "test_hidden.py")
    try:
        p = subprocess.run([sys.executable, "-c", runner], cwd=workdir, capture_output=True,
                           text=True, timeout=timeout, env={"PATH": "/usr/bin:/bin", "PYTHONHASHSEED": "0"})
    except subprocess.TimeoutExpired:
        return {"run": 0, "fail": 0, "error": 0, "passed": 0, "status": "timeout"}
    try:
        d = json.loads(p.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return {"run": 0, "fail": 0, "error": 0, "passed": 0, "status": "crash", "stderr": p.stderr[-2000:]}
    d["passed"] = max(0, d["run"] - d["bad"])  # 小試験（subTest）は試験1件として数える
    d["status"] = "ok" if d["run"] and d["passed"] == d["run"] else "fail"
    return d


def load_task(task_dir):
    t = Path(task_dir)
    meta = json.loads((t / "meta.json").read_text(encoding="utf-8"))
    return t, meta


def stage(task_dir, overlay):
    """given/ を一時フォルダに写し、overlay（{相対パス: 本文}）で上書きした作業場所を返す。"""
    t, meta = load_task(task_dir)
    tmp = Path(tempfile.mkdtemp(prefix="bench-"))
    given = t / "given"
    if given.is_dir():
        for f in given.rglob("*"):
            if f.is_file():
                out = tmp / f.relative_to(given)
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(f, out)
    for rel, body in overlay.items():
        out = tmp / safe_rel(rel)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
    return tmp


def strip_given(rel):
    q = safe_rel(rel)
    return Path(*q.parts[1:]) if q.parts and q.parts[0] in ("given", "ref") else q


def validate(task_dir):
    t, meta = load_task(task_dir)
    ref = {str(f.relative_to(t / "ref")): f.read_text(encoding="utf-8") for f in (t / "ref").rglob("*") if f.is_file()}
    w1 = stage(t, ref)
    good = run_tests(w1, t / "tests" / "test_hidden.py")
    w0 = stage(t, {})
    base = run_tests(w0, t / "tests" / "test_hidden.py")
    ref_lines = sum(len(b.splitlines()) for b in ref.values())
    return {"task": t.name, "ref": good, "given": base, "ref_lines": ref_lines,
            "ok": good["status"] == "ok" and good["run"] >= 15 and base["status"] != "ok"}


def solve_prompt(task_dir):
    t, meta = load_task(task_dir)
    parts = [(t / "prompt.md").read_text(encoding="utf-8").strip(), ""]
    given = t / "given"
    files = [f for f in sorted(given.rglob("*")) if f.is_file()] if given.is_dir() else []
    if files:
        parts.append("添付ファイル:")
        for f in files:
            parts.append(f"=== FILE: {f.relative_to(given)} ===")
            parts.append(f.read_text(encoding="utf-8").rstrip("\n"))
        parts.append("=== END ===")
        parts.append("")
    answers = [str(strip_given(a)) for a in meta["answer"]]
    parts.append("答え方: 次のファイルの全体（変更しないファイルは不要）を、説明なしで、次の形式だけで返してください。"
                 "各ファイルは「=== FILE: パス ===」の行で始め、最後に「=== END ===」の行を置きます。"
                 "ツールは使えません。Python 3.11・標準ライブラリのみ。")
    parts.append("返すファイル: " + "、".join(answers))
    return "\n".join(parts) + "\n"


def grade(task_dir, answer_md):
    t, meta = load_task(task_dir)
    text = Path(answer_md).read_text(encoding="utf-8")
    files = {str(strip_given(k)): v for k, v in parse_files(text).items()}
    want = [str(strip_given(a)) for a in meta["answer"]]
    missing = [w for w in want if w not in files]
    if not files and len(want) == 1:
        blocks = re.findall(r"```(?:python|py)?\n(.*?)```", text, re.S)
        if blocks:
            files = {want[0]: max(blocks, key=len)}
            missing = []
    overlay = {k: v for k, v in files.items() if k in want}
    w = stage(t, overlay)
    r = run_tests(w, t / "tests" / "test_hidden.py")
    r["missing"] = missing
    r["lines"] = sum(len(v.splitlines()) for v in overlay.values())
    return r


def call(model, prompt_file, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    prompt = Path(prompt_file).read_text(encoding="utf-8")
    EMPTY.mkdir(parents=True, exist_ok=True)
    meta = {"model": model, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    t0 = time.time()
    if model == "claude":
        cmd = ["claude", "-p", "--setting-sources", "", "--tools", "", "--strict-mcp-config",
               "--no-session-persistence", "--model", "claude-opus-5-5", "--effort", "high",
               "--output-format", "json"]
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=EMPTY, timeout=CALL_TIMEOUT,
                           env={**os.environ, "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "65536"})
        try:
            d = json.loads(p.stdout)
            answer = d.get("result") or ""
            u = d.get("usage", {})
            meta.update(ok=not d.get("is_error"), input_tokens=u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0),
                        output_tokens=u.get("output_tokens"), thinking_tokens=u.get("output_tokens_details", {}).get("thinking_tokens"),
                        cost_usd_equiv=d.get("total_cost_usd"))
        except json.JSONDecodeError:
            answer, meta["ok"], meta["stderr"] = "", False, (p.stderr or p.stdout)[-2000:]
    elif model in ("sol", "astra"):
        mid = {"sol": "gpt-5.6-sol", "astra": "gpt-6-astra"}[model]
        last = out / "codex-last.txt"
        cmd = ["codex", "exec", "--skip-git-repo-check", "-m", mid, "-s", "read-only",
               "-c", "model_reasoning_effort=high", "-c", "features.shell_tool=false",
               "--json", "-o", str(last), "-"]
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=EMPTY, timeout=CALL_TIMEOUT)
        events = [json.loads(l) for l in p.stdout.splitlines() if l.startswith("{")]
        used = [e for e in events if e.get("type") == "turn.completed"]
        u = used[-1]["usage"] if used else {}
        tools = sum(1 for e in events if e.get("item", {}).get("type") not in (None, "agent_message", "reasoning", "error"))
        answer = last.read_text(encoding="utf-8") if last.exists() else ""
        fails = [e.get("message") or e.get("error", {}).get("message") for e in events if e.get("type") in ("error", "turn.failed")]
        if fails:
            meta["fatal"] = fails[-1]
            meta["limit"] = any("usage limit" in (f or "") or "rate limit" in (f or "").lower() for f in fails)
        meta.update(ok=bool(answer) and p.returncode == 0, model_id=mid, input_tokens=u.get("input_tokens"),
                    cached_input_tokens=u.get("cached_input_tokens"), output_tokens=u.get("output_tokens"),
                    thinking_tokens=u.get("reasoning_output_tokens"), tool_items=tools,
                    errors=[e["item"].get("message") for e in events if e.get("item", {}).get("type") == "error"])
        if p.returncode:
            meta["stderr"] = p.stderr[-2000:]
    elif model == "argon":
        ans = out / "argon.md"
        p = subprocess.run(["bash", ARGON, "-e", os.environ.get("BENCH_ARGON_EFFORT", "high"), "-o", str(ans), prompt], capture_output=True, text=True,
                           timeout=CALL_TIMEOUT, env={**os.environ, "ARGON_TIMEOUT": str(CALL_TIMEOUT - 60), "ARGON_MAX_OUTPUT": "65536",
                                                      "ARGON_STREAM": "1"})
        # 2026-10-15 からストリーミング。ストリーミングなしの REST は 65,536 を指定しても1回 32,768 で止まる（公式）。10-14 の回は stream なし
        answer = ans.read_text(encoding="utf-8") if ans.exists() else ""
        m = re.search(r"入力 (\d+)・出力 (\d+)・考えた分 (\d+) トークン／約\$([0-9.]+)", p.stderr)
        meta.update(ok=bool(answer) and p.returncode == 0, truncated="MAX_TOKENS" in p.stderr,
                    effort=os.environ.get("BENCH_ARGON_EFFORT", "high"), stream=True)
        if m:
            meta.update(input_tokens=int(m[1]), output_tokens=int(m[2]), thinking_tokens=int(m[3]), cost_usd=float(m[4]))
        if p.returncode:
            meta["stderr"] = p.stderr[-2000:]
    else:
        raise SystemExit(f"不明なモデル: {model}")
    meta["seconds"] = round(time.time() - t0, 1)
    (out / "answer.md").write_text(answer, encoding="utf-8")
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__)
        return 1
    if a[0] == "call":
        print(json.dumps(call(a[1], a[2], a[3]), ensure_ascii=False))
    elif a[0] == "parse":
        files = parse_files(Path(a[1]).read_text(encoding="utf-8"))
        write_files(files, a[2])
        print(json.dumps(sorted(files), ensure_ascii=False))
    elif a[0] == "validate":
        print(json.dumps(validate(a[1]), ensure_ascii=False))
    elif a[0] == "solve-prompt":
        sys.stdout.write(solve_prompt(a[1]))
    elif a[0] == "grade":
        print(json.dumps(grade(a[1], a[2]), ensure_ascii=False))
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

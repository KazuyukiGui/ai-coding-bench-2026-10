```json
{"issues": [{"severity": "low", "where": "課題文「スナップショット」節の lots 要素の説明", "problem": "lots 要素のキー remaining と available が、本文の「残数量」「利用可能数量」に対応することが明記されていない。例示（remaining 10, available 7）から推測はできるが、定義としては書かれていない。test_snapshot_exact_shape などの試験はこの対応を前提にしている。", "fix": "課題文に「remaining はロットの残数量、available は利用可能数量（残数量 − active な全予約による割り当て数量）」と明記する。"}]}
```
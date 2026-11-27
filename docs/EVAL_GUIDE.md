# Strix Evaluation Guide

This guide explains how to label test cases for `scripts/run_eval.py`.

> **Note:** `data/` is git-ignored. Never commit real videos or personal labels.

---

## 1. Case Manifest (`data/samples/manifest.csv`)

Required columns:

| Column | Required | Format / Values | Description |
| --- | --- | --- | --- |
| `case_id` | yes | string (unique) | Short case identifier (e.g. `atm_155`). |
| `clip` | yes | path string | Path to video clip (e.g. `data/samples/sample2.mp4`). |
| `atm_id` | no | string | ATM zone ID from `pipeline/config/atm_zone.json` (empty for fallback). |
| `tx_sec` | yes | float | Transaction offset in seconds. |
| `window_sec` | yes | float (> 0) | Half-window in seconds around `tx_sec`. |
| `expect_link` | yes | `person` \| `none` | Whether a person should be linked to the ATM in this window. |
| `gt_intervals` | no | `start-end;start-end` | Semicolon-separated intervals (seconds) when target person is at the ATM. |
| `manual_best_t` | no | float | Timestamp (seconds) of the clearest face picked by a human reviewer. |
| `expect_frontal` | yes | `yes` \| `no` \| `unknown` | Whether at least one frontal `match_ready` face is expected. |
| `notes` | no | string | Free-text reviewer notes (mark unverified rows `TO CONFIRM BY HUMAN`). |

---

## 2. People Timeline (`data/samples/people.csv`)

Used when `--people` is passed to `scripts/run_eval.py` for cross-clip and same-clip search evaluation (requires at least 2 distinct `person_label` values):

| Column | Required | Format | Description |
| --- | --- | --- | --- |
| `clip` | yes | path string | Clip path matching `manifest.csv`. |
| `t_start` | yes | float | Interval start time in seconds. |
| `t_end` | yes | float (> `t_start`) | Interval end time in seconds. |
| `person_label` | yes | string | Anonymous person identifier (e.g. `person_A`, `person_B`). |

---

## 3. Running Evaluation

```bash
python scripts/run_eval.py --manifest data/samples/manifest.csv
python scripts/run_eval.py --manifest data/samples/manifest.csv --people data/samples/people.csv --out docs/eval_report.md
```

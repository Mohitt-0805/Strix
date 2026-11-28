# Strix Demo Runbook

Exact step-by-step commands for the live / offline demo.

---

## 1. Setup & Preflight

```bash
cd /home/mohit/Strix
source .venv/bin/activate
export VIDEO=data/samples/sample2.mp4
python scripts/preflight.py
```
- **Say:** *"Preflight confirms our offline models, `.venv` environment, demo cache, and a live short-clip pass are all healthy before we start."*
- **If it fails:** Switch to `export DEMO_PACK_DIR=demo_pack` for cached mode, or play the pre-recorded backup clip.

---

## 2. Live Short Case (`atm_155`)

```bash
python -m pipeline.run_pipeline "$VIDEO" --atm-id atm_155 --tx 155 --window 6 --transaction-time 2026-11-26T12:00:00
```
- **Say:** *"Given just the ATM ID and transaction timestamp, Strix links the person track in the ATM zone, filters out profile/downward-looking frames, and picks the clearest match-ready faces."*
- **If it fails:** Run the cached command in Step 3 (`DEMO_PACK_DIR=demo_pack`).

---

## 3. Cached Demo Mode (`DEMO_PACK_DIR`)

```bash
DEMO_PACK_DIR=demo_pack python -m pipeline.run_pipeline "$VIDEO" --atm-id atm_155 --tx 155 --window 6
```
- **Say:** *"In offline demo mode, cached results replay progress cleanly and explicitly mark `served_from_demo_pack: true` so the UI displays a precomputed-demo badge."*
- **If it fails:** Verify `demo_pack/` with `python scripts/verify_offline.py` or show `data/outputs/sample2/tx155_w6_atm_155/result.json`.

---

## 4. Non-Destructive Enhancement

```bash
python -m pipeline.enhance --result data/outputs/sample2/tx155_w6_atm_155/result.json --frame f_153013 --scale 4
```
- **Say:** *"Enhancement crops first, upscales for human visual review, stamps a red `ENHANCED x4` banner above the crop, and never modifies the original frame."*
- **If it fails:** Show the precomputed enhanced crop in `demo_pack/atm_155/frame_153013_enh_x4.jpg`.

---

## 5. Index & Search with Enhancement Comparison

```bash
python scripts/search_enhanced.py --index data/outputs/sample2/index_s0_e247p887 --result data/outputs/sample2/tx155_w6_atm_155/result.json --frame f_153013
```
- **Say:** *"Search always ranks leads using the original crop's embedding, displays the enhanced crop's similarity only as a secondary check with a disagreement warning if they diverge, and reminds operators that results are possible leads only."*
- **If it fails:** Open `data/outputs/sample2/index_s0_e247p887/search_enhanced.jpg` and `data/outputs/sample2/index_s0_e247p887/index_sheet.jpg`.

---

## 6. Evaluation Report

```bash
cat docs/eval_report.md
```
- **Say:** *"On our labeled evaluation manifest (`docs/eval_report.md`), Strix passed 3/3 linking checks and 2/2 frontal-expectation checks across `atm_40` (32.06 s), `atm_155` (15.67 s), and `empty_120` (4.38 s)."*
- **If it fails:** Open `docs/eval_cases.csv` directly.

---

## Honest Limits & Safety Notes

Strix outputs **possible leads only** and requires human verification — it never performs automatic identification. Lanczos enhancement is strictly for human visual inspection and does not add real biometric detail; search uses the original crop embedding unless the original face is undetectable. Occluder flags (`cap`, `mask`, `helmet`) and quality thresholds are model estimates tested on a small number of practice clips (`sample2.mp4`), and the InsightFace `buffalo_l` model licence must be confirmed with organisers ([docs/LICENCES.md](file:///home/mohit/Strix/docs/LICENCES.md)).

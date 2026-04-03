"""
calibrator.py

Industrial calibration utility to measure and visualize judge agreement against human-labeled ground truth.
Supports internal trace events (metadata.human = True) and external golden manifests.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

def run_calibration(path: str, golden_path: Optional[str] = None, plot: bool = False):
    """
    Industrial Calibration Cycle (v1.2.3).
    Analyzes judge-human agreement metrics and suggests optimized success thresholds.
    """
    print(f"\n[Calibration] Loading trace from: {path}")
    trace_path = Path(path)
    if not trace_path.exists():
        print(f"[ERROR] Trace file not found: {path}")
        return

    # 1. Load Trace Events
    events = []
    if trace_path.is_dir():
        # Aggregated Loading (Industrial Calibration Standard)
        for fpath in sorted(trace_path.rglob("*.jsonl")):
            with open(fpath, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        try:
                            events.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
    else:
        with open(trace_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

    # 2. Extract Golden Labels (Ground Truth)
    golden_labels = {}
    if golden_path:
        gp = Path(golden_path)
        if gp.exists():
            with open(gp, "r", encoding="utf-8") as f:
                golden_labels = json.load(f)
            print(f"[Calibration] Loaded {len(golden_labels)} golden labels from external manifest.")
    
    # Pair Judge vs. Human scores
    judge_scores = {} # task_id -> score
    human_scores = {} # task_id -> score

    for event in events:
        ev_type = event.get("event")
        task_id = event.get("task_id") or "unknown"
        
        if ev_type == "evaluation":
            val = float(event.get("value", 0.0))
            is_human = event.get("metadata", {}).get("human", False)
            
            if is_human:
                human_scores[task_id] = val
            else:
                judge_scores[task_id] = val
        
        # Also check run_start/task_start metadata for ground truth
        elif ev_type in ["run_start", "task_start"]:
            gt = event.get("metadata", {}).get("human_label")
            if gt is not None:
                human_scores[task_id] = float(gt)

    # Merge external golden labels if task_id matches
    for tid, val in golden_labels.items():
        human_scores[tid] = float(val)

    # 3. Align and Pair
    aligned_pairs = []
    for tid, judge_val in judge_scores.items():
        if tid in human_scores:
            aligned_pairs.append((tid, judge_val, human_scores[tid]))

    if not aligned_pairs:
        print("[WARNING] No aligned Judge-Human pairs found in trace. Calibration aborted.")
        return

    print(f"[Calibration] Found {len(aligned_pairs)} paired evaluation points.")

    # 4. Calculate Metrics
    mae = sum(abs(j - h) for _, j, h in aligned_pairs) / len(aligned_pairs)
    
    # Pearson Correlation (Simple Implementation if scipy missing)
    def correlation(j_vals, h_vals):
        n = len(j_vals)
        if n < 2: return 0.0
        sum_j = sum(j_vals)
        sum_h = sum(h_vals)
        sum_j_sq = sum(j**2 for j in j_vals)
        sum_h_sq = sum(h**2 for h in h_vals)
        sum_jh = sum(j*h for j, h in zip(j_vals, h_vals))
        
        num = n * sum_jh - sum_j * sum_h
        den = ((n * sum_j_sq - sum_j**2) * (n * sum_h_sq - sum_h**2)) ** 0.5
        return num / den if den != 0 else 0.0

    j_list = [p[1] for p in aligned_pairs]
    h_list = [p[2] for p in aligned_pairs]
    corr = correlation(j_list, h_list)

    # 5. Threshold Optimization (Auto-Threshold)
    # Sweep thresholds from 0.0 to 1.0 to maximize F1-score
    best_threshold = 0.5
    best_f1 = 0.0
    
    thresholds = [i/20 for i in range(21)] # 0.0, 0.05, ..., 1.0
    for t in thresholds:
        tp = fp = fn = tn = 0
        for _, j, h in aligned_pairs:
            j_bin = 1 if j >= t else 0
            h_bin = 1 if h >= 0.5 else 0 # Human assumes success >= 0.5
            
            if j_bin == 1 and h_bin == 1: tp += 1
            elif j_bin == 1 and h_bin == 0: fp += 1
            elif j_bin == 0 and h_bin == 1: fn += 1
            else: tn += 1
        
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * (prec * rec) / (prec + rec) if (prec + rec) > 0 else 0
        
        if f1 >= best_f1:
            best_f1 = f1
            best_threshold = t

    # 6. Report Generation
    print("\n" + "=" * 50)
    print(f"{'JUDGE CALIBRATION REPORT':^50}")
    print("=" * 50)
    print(f"Total Samples:         {len(aligned_pairs)}")
    print(f"Mean Absolute Error:   {mae:.4f}")
    print(f"Correlation (Rho):     {corr:.4f}")
    print(f"Baseline F1 (0.5):     {best_f1:.4f}") # (Simple F1)
    print("-" * 50)
    print(f"RECOMENDED THRESHOLD:  {best_threshold:.2f}")
    print(f"Optimized F1 Score:    {best_f1:.4f}")
    print("=" * 50)

    # 7. Visualization (Industrial Plotting)
    if plot:
        try:
            import matplotlib.pyplot as plt
            import numpy as np
            
            plt.figure(figsize=(10, 6))
            plt.scatter(h_list, j_list, alpha=0.6, edgecolors='w', linewidth=0.5)
            plt.plot([0, 1], [0, 1], '--', color='red', alpha=0.5, label='Perfect Agreement')
            plt.axhline(y=best_threshold, color='green', linestyle=':', label=f'Auto-Threshold ({best_threshold:.2f})')
            
            plt.xlabel("Human Ground Truth Score")
            plt.ylabel("Judge AI Score")
            plt.title(f"Judge Calibration Analysis (Rho={corr:.3f})")
            plt.legend()
            plt.grid(True, alpha=0.3)
            
            plot_path = trace_path.parent / "calibration_plot.png"
            plt.savefig(plot_path)
            print(f"[OK] Calibration plot saved to {plot_path}")
            plt.close()
        except ImportError:
            print("[WARNING] matplotlib/numpy missing. Plotting skipped.")
        except Exception as e:
            print(f"[ERROR] Failed to generate plot: {e}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        run_calibration(sys.argv[1], plot="--plot" in sys.argv)

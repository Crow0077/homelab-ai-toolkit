#!/usr/bin/env python3
"""
Agent Amnesia Detector (AAD) — MVP
===================================
Detects context degradation in Hermes agent sessions.

How it works:
1. Reads the most recent Hermes session transcript
2. Splits into chunks of N turns
3. Computes embedding similarity between early and late turns
4. If similarity drops > threshold → context is degrading → alert
5. Tracks degradation over time per session
6. Flags when agent needs "memory refresh"

Wiki synthesis:
- context-engineering (agents fail because of context, not prompts)
- ouroboros-principle (memory decay = power-law, not linear)
- information-based-immunity (detect information gaps before failure)
- task-paralysis-and-ai (context rot is the machine equivalent)

Usage:
  python3 aad.py                          # Check current session
  python3 aad.py --threshold 0.4          # Custom degradation threshold
  python3 aad.py --history                # Show degradation history
"""

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from collections import defaultdict

STATE_DIR = Path.home() / ".cache" / "aad"
STATE_DIR.mkdir(parents=True, exist_ok=True)
HISTORY_FILE = STATE_DIR / "degradation_history.json"

# Simplified embedding: term frequency vector
# In production, this would use sentence-transformers or an API
def simple_embed(text: str) -> dict:
    """Bag-of-words embedding as a poor man's semantic vector."""
    words = re.findall(r'\b[a-z]{3,}\b', text.lower())
    total = max(len(words), 1)
    freq = defaultdict(int)
    for w in words:
        freq[w] += 1
    return {w: c/total for w, c in freq.items()}

def cosine_similarity(vec1: dict, vec2: dict) -> float:
    """Cosine similarity between two sparse vectors."""
    all_keys = set(vec1) | set(vec2)
    dot = sum(vec1.get(k, 0) * vec2.get(k, 0) for k in all_keys)
    mag1 = sum(v**2 for v in vec1.values()) ** 0.5
    mag2 = sum(v**2 for v in vec2.values()) ** 0.5
    if mag1 == 0 or mag2 == 0:
        return 1.0
    return dot / (mag1 * mag2)

def find_session_files() -> list[Path]:
    """Find recent Hermes session transcript files."""
    session_dir = Path.home() / ".hermes" / "sessions"
    if not session_dir.exists():
        return []
    files = sorted(session_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
    return files[:5]  # Last 5 sessions

def analyze_session(filepath: Path, threshold: float = 0.5) -> dict:
    """Analyze a single session for context degradation."""
    try:
        data = json.loads(filepath.read_text())
    except (json.JSONDecodeError, OSError):
        return {"error": f"Cannot read {filepath.name}"}
    
    # Extract messages (support different transcript formats)
    messages = []
    if isinstance(data, list):
        messages = data
    elif isinstance(data, dict):
        messages = data.get("messages", data.get("turns", []))
    
    if len(messages) < 6:
        return {"error": f"Too few messages ({len(messages)}) for analysis"}
    
    # Split into thirds: early, middle, late
    n = len(messages)
    third = n // 3
    
    early_text = " ".join(
        str(m.get("content", str(m))) for m in messages[:third]
    )
    mid_text = " ".join(
        str(m.get("content", str(m))) for m in messages[third:2*third]
    )
    late_text = " ".join(
        str(m.get("content", str(m))) for m in messages[2*third:]
    )
    
    # Compute embeddings
    early_vec = simple_embed(early_text)
    mid_vec = simple_embed(mid_text)
    late_vec = simple_embed(late_text)
    
    # Similarity scores
    early_mid_sim = cosine_similarity(early_vec, mid_vec)
    early_late_sim = cosine_similarity(early_vec, late_vec)
    mid_late_sim = cosine_similarity(mid_vec, late_vec)
    
    # Degradation = similarity drop from early to late
    degradation = early_mid_sim - early_late_sim
    degraded = degradation > threshold
    
    # Hurst-inspired: check if degradation is accelerating
    second_half_drop = mid_late_sim - early_late_sim
    accelerating = second_half_drop > 0 and degradation > 0
    
    return {
        "session": filepath.name,
        "total_messages": len(messages),
        "early_mid_similarity": round(early_mid_sim, 3),
        "mid_late_similarity": round(mid_late_sim, 3),
        "early_late_similarity": round(early_late_sim, 3),
        "degradation": round(degradation, 3),
        "degraded": degraded,
        "accelerating": accelerating,
        "verdict": "DEGRADING" if degraded else ("ACCELERATING" if accelerating else "STABLE"),
        "recommendation": "",
    }

def load_history() -> list:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []

def save_check(result: dict) -> None:
    history = load_history()
    history.append({
        "timestamp": datetime.now().isoformat(),
        **{k: v for k, v in result.items() if k not in ("recommendation",)},
    })
    # Keep last 500 entries
    HISTORY_FILE.write_text(json.dumps(history[-500:], indent=2))

def main():
    parser = argparse.ArgumentParser(description="Agent Amnesia Detector")
    parser.add_argument("--threshold", type=float, default=0.5, help="Degradation threshold (default: 0.5)")
    parser.add_argument("--history", action="store_true", help="Show degradation history")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    if args.history:
        hist = load_history()
        if not hist:
            print("No degradation history recorded yet.")
            return
        
        recent = hist[-20:]
        print(f"\n{'='*70}")
        print(f"  AGENT AMNESIA DETECTOR — Degradation History (last {len(recent)})")
        print(f"{'='*70}")
        print(f"{'Time':<20} {'Session':<30} {'Verdict':<14} {'Degradation':>8}")
        print(f"{'-'*70}")
        
        degraded_count = 0
        for entry in recent:
            ts = entry.get("timestamp", "?")[:19]
            session = entry.get("session", "?")[:29]
            verdict = entry.get("verdict", "?")
            deg = entry.get("degradation", 0)
            if verdict in ("DEGRADING", "ACCELERATING"):
                degraded_count += 1
            
            marker = "⚠" if verdict in ("DEGRADING", "ACCELERATING") else " "
            print(f"{marker}{ts:<19} {session:<30} {verdict:<14} {deg:>+8.3f}")
        
        print(f"\nDegraded sessions: {degraded_count}/{len(recent)}")
        if degraded_count > len(recent) * 0.3:
            print("⚠  High degradation rate — consider smaller context windows or sub-agents.")
        return
    
    # Analyze recent sessions
    files = find_session_files()
    if not files:
        print("No Hermes session files found.")
        print("AAD looks for transcripts in ~/.hermes/sessions/")
        return
    
    results = []
    for f in files[:3]:  # Analyze last 3 sessions
        result = analyze_session(f, args.threshold)
        if "error" in result:
            continue
        
        # Generate recommendation
        if result["degraded"]:
            if result["accelerating"]:
                result["recommendation"] = "CRITICAL: Context degrading and accelerating. Inject memory refresh NOW or spawn sub-agent."
            else:
                result["recommendation"] = "WARNING: Context is degrading. Consider summarizing early context or offloading to sub-agent."
        elif result["accelerating"]:
            result["recommendation"] = "MONITOR: Degradation is accelerating. Watch next turn closely."
        else:
            result["recommendation"] = "Context is stable. No action needed."
        
        save_check(result)
        results.append(result)
    
    if args.json:
        print(json.dumps(results, indent=2))
        return
    
    print(f"\n{'='*70}")
    print(f"  AGENT AMNESIA DETECTOR — Session Analysis")
    print(f"  Threshold: {args.threshold} | Sessions analyzed: {len(results)}")
    print(f"{'='*70}\n")
    
    for r in results:
        icon = "🔴" if r["degraded"] else ("🟡" if r["accelerating"] else "🟢")
        print(f"{icon} {r['session']}")
        print(f"   Messages: {r['total_messages']} | Early→Mid: {r['early_mid_similarity']} | "
              f"Early→Late: {r['early_late_similarity']} | Degradation: {r['degradation']:+.3f}")
        print(f"   Verdict: {r['verdict']} — {r['recommendation']}\n")
    
    degraded = sum(1 for r in results if r["degraded"])
    if degraded > 0:
        print(f"⚠  {degraded}/{len(results)} sessions show degradation.")
        print(f"   Recommendation: Smaller context windows or sub-agent delegation.\n")

if __name__ == "__main__":
    main()

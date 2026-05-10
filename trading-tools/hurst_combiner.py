#!/usr/bin/env python3
"""
Hurst Signal Combiner (HSC)
============================
Medallion-inspired multi-signal combination using Hurst exponent regimes.

Architecture:
  - Computes Hurst exponent for each signal's time series (price, RSI, MACD, volume)
  - Groups signals by H regime: persistent (H>0.55), random (0.45<H<0.55), mean-reverting (H<0.45)
  - Signals in the SAME regime compound — they share the same memory structure
  - Cross-regime signals get reduced weight (they're measuring different phenomena)
  - Kelly-inspired position sizing adjusted by entropy
  - Plugs into the existing swing_screener.py output

Wiki synthesis:
  - medallion-fund-models: many weak uncorrelated signals → one strong prediction
  - ouroboros-principle: memory (Hurst exponent) determines scaling behavior
  - entropy-risk: position sizing proportional to signal confidence entropy
  - hermetic-trading-v2: Hurst exponent as regime detector

Usage:
  python3 hurst_combiner.py                    # Run standalone test
  python3 hurst_combiner.py --ticker AAPL      # Analyze single ticker
  python3 hurst_combiner.py --watchlist         # Analyze full watchlist
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

# ── Hurst Exponent ───────────────────────────────────────────────────

def hurst_exponent(series: np.ndarray, max_lag: int = 50) -> float:
    """
    Compute Hurst exponent using rescaled range (R/S) analysis.
    H > 0.5: persistent/trending (memory reinforces direction)
    H ≈ 0.5: random walk (no memory)
    H < 0.5: mean-reverting (memory opposes direction)
    """
    if len(series) < max_lag:
        max_lag = len(series) // 2
    if max_lag < 10:
        return 0.5  # Not enough data
    
    lags = range(10, max_lag)
    tau = []
    
    for lag in lags:
        # Split series into chunks of size 'lag'
        n_chunks = len(series) // lag
        if n_chunks < 2:
            continue
        
        rs_values = []
        for i in range(n_chunks):
            chunk = series[i * lag:(i + 1) * lag]
            if len(chunk) < 2:
                continue
            mean = np.mean(chunk)
            deviate = chunk - mean
            cumsum = np.cumsum(deviate)
            r = np.max(cumsum) - np.min(cumsum)
            s = np.std(chunk)
            if s > 0:
                rs_values.append(r / s)
        
        if rs_values:
            tau.append((lag, np.mean(rs_values)))
    
    if len(tau) < 4:
        return 0.5
    
    # Log-log regression: log(R/S) = H * log(lag) + c
    log_lags = np.log([t[0] for t in tau])
    log_rs = np.log([t[1] for t in tau])
    
    H, _ = np.polyfit(log_lags, log_rs, 1)
    return max(0.0, min(1.0, H))  # Clamp to [0, 1]

def hurst_regime(H: float) -> str:
    if H > 0.55:
        return "persistent"
    elif H < 0.45:
        return "mean_reverting"
    return "random"

# ── Signal Extraction ────────────────────────────────────────────────

def compute_signals(ticker: str, period: str = "1y") -> dict:
    """
    Extract individual signal time series for a ticker.
    Returns a dict of {signal_name: {values: [...], H: float, regime: str}}
    """
    data = yf.download(ticker, period=period, progress=False)
    if data.empty:
        return {}
    
    close = data["Close"].values.flatten()
    returns = np.diff(np.log(close))
    returns = returns[~np.isnan(returns)]
    
    # Price momentum signal (20-day rate of change)
    roc = np.zeros(len(close))
    roc[20:] = (close[20:] / close[:-20] - 1)
    roc = roc[~np.isnan(roc)]
    
    # RSI approximation (14-period, simplified)
    delta = np.diff(close)
    delta = delta[~np.isnan(delta)]
    gains = np.where(delta > 0, delta, 0)
    losses = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gains).rolling(14).mean().values
    avg_loss = pd.Series(losses).rolling(14).mean().values
    rsi = np.zeros(len(avg_gain))
    mask = avg_loss > 0
    rsi[mask] = 100 - (100 / (1 + avg_gain[mask] / avg_loss[mask]))
    rsi = rsi[~np.isnan(rsi)]
    
    # Volume ratio (20-day avg volume / 50-day avg volume)
    volumes = data["Volume"].values.flatten()
    vol_20 = pd.Series(volumes).rolling(20).mean().values
    vol_50 = pd.Series(volumes).rolling(50).mean().values
    vol_ratio = np.zeros(len(vol_20))
    mask2 = vol_50 > 0
    vol_ratio[mask2] = vol_20[mask2] / vol_50[mask2]
    vol_ratio = vol_ratio[~np.isnan(vol_ratio)]
    
    # MACD histogram (12/26/9)
    ema12 = pd.Series(close).ewm(span=12).mean().values
    ema26 = pd.Series(close).ewm(span=26).mean().values
    macd_line = ema12 - ema26
    macd_signal = pd.Series(macd_line).ewm(span=9).mean().values
    macd_hist = macd_line - macd_signal
    macd_hist = macd_hist[~np.isnan(macd_hist)]
    
    # Bollinger position (close vs bands)
    bb_mid = pd.Series(close).rolling(20).mean().values
    bb_std = pd.Series(close).rolling(20).std().values
    bb_pos = np.zeros(len(close))
    bb_mask = bb_std > 0
    bb_pos[bb_mask] = (close[bb_mask] - bb_mid[bb_mask]) / (2 * bb_std[bb_mask])
    bb_pos = bb_pos[~np.isnan(bb_pos)]
    
    signals = {}
    signal_data = [
        ("returns", returns, "Returns (log daily)"),
        ("momentum", roc, "20-day Rate of Change"),
        ("rsi", rsi, "RSI (14)"),
        ("volume_ratio", vol_ratio, "Volume Ratio (20/50)"),
        ("macd_hist", macd_hist, "MACD Histogram (12/26/9)"),
        ("bb_position", bb_pos, "Bollinger Band Position"),
    ]
    
    for name, values, description in signal_data:
        if len(values) >= 100:
            H = hurst_exponent(values)
            signals[name] = {
                "description": description,
                "length": len(values),
                "H": round(H, 3),
                "regime": hurst_regime(H),
                "mean": round(float(np.mean(values)), 6),
                "std": round(float(np.std(values)), 6),
                "current": round(float(values[-1]), 6),
                "z_score": round(float((values[-1] - np.mean(values)) / np.std(values)), 3) if np.std(values) > 0 else 0,
            }
    
    return signals

# ── Signal Combination ───────────────────────────────────────────────

def combine_signals(signals: dict, ticker: str) -> dict:
    """
    Medallion-inspired signal combination:
    1. Group signals by Hurst regime
    2. Within each regime, average the z-scores (same memory structure = compoundable)
    3. Weight regimes by: persistent > random > mean_reverting (trend-following bias)
    4. Cross-regime penalty: signals from different regimes get reduced weight
    """
    regimes = {"persistent": [], "random": [], "mean_reverting": []}
    
    for name, sig in signals.items():
        regimes[sig["regime"]].append(sig)
    
    # Regime weights (Medallion-style: persistent signals are stronger in trending markets)
    regime_weights = {
        "persistent": 1.0,
        "random": 0.6,
        "mean_reverting": 0.4,
    }
    
    # Calculate regime-level composite scores
    regime_scores = {}
    for regime_name, sig_list in regimes.items():
        if not sig_list:
            continue
        # Weighted average of z-scores within the regime
        # Sign matters: positive z = bullish, negative z = bearish
        z_scores = [s["z_score"] for s in sig_list]
        H_values = [s["H"] for s in sig_list]
        
        # Signals with similar H compound (Medallion: uncorrelated but same regime = combo power)
        if len(z_scores) >= 2:
            # Check H dispersion: if all signals have similar H, they compound
            h_dispersion = np.std(H_values) if len(H_values) > 1 else 0
            compound_bonus = max(1.0, 1.5 - h_dispersion * 2)  # Higher bonus when H values are close
        else:
            compound_bonus = 1.0
        
        avg_z = np.mean(z_scores)
        regime_scores[regime_name] = {
            "signals": [s["description"] for s in sig_list],
            "count": len(sig_list),
            "avg_z": round(float(avg_z), 3),
            "avg_H": round(float(np.mean(H_values)), 3),
            "H_dispersion": round(float(np.std(H_values)), 3) if len(H_values) > 1 else 0,
            "compound_bonus": round(compound_bonus, 2),
            "regime_weight": regime_weights[regime_name],
        }
    
    # Cross-regime combination
    total_score = 0.0
    total_weight = 0.0
    
    for regime_name, score in regime_scores.items():
        weight = score["regime_weight"] * score["compound_bonus"]
        total_score += score["avg_z"] * weight
        total_weight += weight
    
    final_z = total_score / max(total_weight, 1e-6)
    
    # Map z-score to confidence and direction
    if abs(final_z) < 0.3:
        direction = "neutral"
        confidence = "LOW"
    elif final_z > 0:
        direction = "bullish"
        confidence = "HIGH" if abs(final_z) > 1.5 else ("MEDIUM" if abs(final_z) > 0.7 else "LOW")
    else:
        direction = "bearish"
        confidence = "HIGH" if abs(final_z) > 1.5 else ("MEDIUM" if abs(final_z) > 0.7 else "LOW")
    
    # Entropy-based risk score (higher dispersion = higher entropy = reduce position)
    all_z = []
    for score in regime_scores.values():
        all_z.append(score["avg_z"])
    if len(all_z) >= 2:
        consensus = 1.0 - (np.std(all_z) / max(abs(np.mean(all_z)), 1e-6))  # Lower std = higher consensus
        consensus = max(0.0, min(1.0, consensus))
    else:
        consensus = 0.5
    
    return {
        "ticker": ticker,
        "timestamp": datetime.now().isoformat(),
        "composite": {
            "z_score": round(float(final_z), 3),
            "direction": direction,
            "confidence": confidence,
            "consensus": round(float(consensus), 3),
        },
        "regimes": regime_scores,
        "signals": {name: {"H": s["H"], "regime": s["regime"], "z": s["z_score"]} for name, s in signals.items()},
    }


# ── CLI ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Hurst Signal Combiner")
    parser.add_argument("--ticker", default="AAPL", help="Ticker to analyze")
    parser.add_argument("--watchlist", action="store_true", help="Analyze full watchlist")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    if args.watchlist:
        watchlist_path = Path.home() / "trading-tools" / "watchlist.txt"
        if watchlist_path.exists():
            tickers = [l.strip() for l in watchlist_path.read_text().splitlines() if l.strip()]
        else:
            tickers = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL", "NFLX", "SPY", "QQQ"]
    else:
        tickers = [args.ticker]
    
    results = []
    for ticker in tickers:
        signals = compute_signals(ticker)
        if not signals:
            continue
        result = combine_signals(signals, ticker)
        results.append(result)
        
        if not args.json:
            # Pretty print
            c = result["composite"]
            print(f"\n{'='*60}")
            print(f"  {ticker:6s}  |  {c['direction']:8s}  |  {c['confidence']:6s}  |  z={c['z_score']:+.3f}  |  consensus={c['consensus']:.2f}")
            print(f"{'='*60}")
            print(f"{'Signal':<20} {'H':>6} {'Regime':<16} {'Z-Score':>8}")
            print(f"{'-'*52}")
            for name, s in result["signals"].items():
                print(f"{name:<20} {s['H']:>6.3f} {s['regime']:<16} {s['z']:>+8.3f}")
            print(f"\n  Regime breakdown:")
            for rname, rs in result["regimes"].items():
                print(f"    {rname:<16} ({rs['count']} signals, H≈{rs['avg_H']:.3f}, z={rs['avg_z']:+.3f})")
    
    if args.json:
        print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()

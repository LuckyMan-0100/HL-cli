"""
Edge decay and trade‑frequency optimisation tools (v2).

Key update: **find_optimal_threshold() now chooses the threshold that
maximises *trade count* while still meeting minimum edge & Sharpe**, so the
recommended operating point **never reduces trade frequency**.

Typical usage for 90-day walk-forward:
-------------
>>> ea = EdgeAnalyzer(base_cost=0.00025,
                     min_edge_bp=4.0,      # 4 bp initial target
                     min_sharpe=0.7)       # Lower initial Sharpe target
>>> sweep = ea.analyze_threshold_sweep(val_probs, returns)
>>> τ_opt, m_opt = ea.find_optimal_threshold(sweep)  # now bias toward more trades
>>> ea.plot_edge_decay(sweep)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple, Any

import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class EdgeMetrics:
    """Container for per‑threshold performance figures."""

    tau: float          # probability threshold
    n_trades: int       # number of trades triggered
    mean_bp: float      # mean net return per trade (basis points)
    std_bp: float       # std‑dev per trade (bp)
    sharpe: float       # annualised Sharpe ratio


# ---------------------------------------------------------------------------
# Core analyser
# ---------------------------------------------------------------------------

class EdgeAnalyzer:
    """Analyzes edge and threshold trade-offs for trading signals."""
    
    def __init__(
        self,
        base_cost: float = 0.00025,  # 2.5bp base cost
        min_edge_bp: float = 4.0,    # 4bp edge for initial validation
        min_sharpe: float = 0.7,     # Lower Sharpe requirement for 4-day window
        min_trades: int = 50,        # Minimum trades for statistical significance
        prob_thresholds: np.ndarray = np.linspace(0.5, 0.95, 46)  # More granular threshold sweep
    ):
        """Initialize EdgeAnalyzer with configurable parameters.
        
        Args:
            base_cost: Base trading cost in decimal (e.g., 0.00025 for 2.5bp)
            min_edge_bp: Minimum required edge in basis points (4bp for initial)
            min_sharpe: Minimum required Sharpe ratio (0.7 for 4-day window)
            min_trades: Minimum number of trades required
            prob_thresholds: Array of probability thresholds to analyze
        """
        self.base_cost = base_cost
        self.min_edge_bp = min_edge_bp
        self.min_sharpe = min_sharpe
        self.min_trades = min_trades
        self.prob_thresholds = prob_thresholds

    # ---------------------------------------------------------------------
    # 1. Threshold sweep
    # ---------------------------------------------------------------------

    def analyze_threshold_sweep(
        self,
        val_probs: np.ndarray,   # shape (n, 2) – [p(long), p(short)]
        returns: np.ndarray,     # realised returns aligned with rows
        taus: np.ndarray | None = None,
        days_in_period: int = 90  # Default to 90-day walk-forward
    ) -> List[EdgeMetrics]:
        """Compute *EdgeMetrics* for a grid of τ values.
        
        Args:
            val_probs: Probability predictions [p(long), p(short)]
            returns: Realized returns aligned with predictions
            taus: Optional custom threshold values to test
            days_in_period: Number of trading days in walk-forward period
        """
        if taus is None:
            taus = np.arange(0.015, 0.060, 0.005)

        out: List[EdgeMetrics] = []
        LONG, SHORT = 0, 1
        n_obs = len(returns)
        
        # Scale factor for annualization based on period length
        annual_scale = np.sqrt(252 / days_in_period)  # Scale Sharpe to annual basis

        for tau in taus:
            sig_long = val_probs[:, LONG] > tau
            sig_short = val_probs[:, SHORT] > tau
            trades = sig_long | sig_short
            if not trades.any():
                continue

            pnl = returns[trades] - self.base_cost
            n_tr = trades.sum()
            mean_bp = pnl.mean() * 1e4
            std_bp = pnl.std(ddof=0) * 1e4
            
            # Scale Sharpe ratio based on period length
            sharpe = (mean_bp / std_bp) * np.sqrt(n_tr * days_in_period / n_obs) * annual_scale

            out.append(EdgeMetrics(tau, n_tr, mean_bp, std_bp, sharpe))
        return out

    # ---------------------------------------------------------------------
    # 2. Visualisation helpers
    # ---------------------------------------------------------------------

    @staticmethod
    def _bar_xticks(ax):
        plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    def plot_edge_decay(self, metrics: List[EdgeMetrics]) -> None:
        """Plot mean bp and Sharpe versus τ."""
        τs = [m.tau for m in metrics]
        μs = [m.mean_bp for m in metrics]
        Ss = [m.sharpe for m in metrics]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)

        ax1.plot(τs, μs, marker="o")
        ax1.axhline(self.min_edge_bp, ls="--", c="r", label="min edge")
        ax1.set_ylabel("Mean return (bp)")
        ax1.grid(True)
        ax1.legend()

        ax2.plot(τs, Ss, marker="o", color="tab:green")
        ax2.axhline(self.min_sharpe, ls="--", c="r", label="min Sharpe")
        ax2.set_xlabel("Probability threshold τ")
        ax2.set_ylabel("Annualised Sharpe")
        ax2.grid(True)
        ax2.legend()

        plt.tight_layout()
        plt.show()

    # ---------------------------------------------------------------------
    # 3. Optimal τ – now *max trade count* subject to constraints
    # ---------------------------------------------------------------------

    def find_optimal_threshold(
        self, metrics: List[EdgeMetrics]
    ) -> Tuple[float, EdgeMetrics]:
        """Return τ that meets targets **and maximises trade count**."""
        feasible = [m for m in metrics if m.mean_bp >= self.min_edge_bp and m.sharpe >= self.min_sharpe]
        if not feasible:
            raise ValueError("No τ meets edge ≥ %.1f bp and Sharpe ≥ %.2f" % (self.min_edge_bp, self.min_sharpe))
        best = max(feasible, key=lambda m: m.n_trades)  # <-- prefer more trades
        return best.tau, best

    # ---------------------------------------------------------------------
    # 4. Enhancement what‑ifs (unchanged)
    # ---------------------------------------------------------------------

    def analyze_enhancement_impact(
        self,
        base: EdgeMetrics,
        maker_ratio: float = 0.60,
        size_scale: float = 0.70,
        hold_time_ratio: float = 0.40,
        symbol_count: int = 3,
        model_count: int = 2,
    ) -> Dict[str, EdgeMetrics]:
        """Return projected metrics for various enhancement levers."""
        enh: Dict[str, EdgeMetrics] = {"base": base}

        # maker / taker blend
        maker_cost = 0.00010
        avg_cost = maker_ratio * maker_cost + (1 - maker_ratio) * self.base_cost
        gain = (self.base_cost - avg_cost) / self.base_cost
        enh["maker_orders"] = EdgeMetrics(base.tau, base.n_trades, base.mean_bp * (1 + gain), base.std_bp, base.sharpe * (1 + gain))

        # size scaling
        enh["size_scaling"] = EdgeMetrics(base.tau, base.n_trades, base.mean_bp * size_scale, base.std_bp * np.sqrt(size_scale), base.sharpe * np.sqrt(size_scale))

        # shorter holding
        enh["shorter_holding"] = EdgeMetrics(base.tau, int(base.n_trades / hold_time_ratio), base.mean_bp * hold_time_ratio, base.std_bp * np.sqrt(hold_time_ratio), base.sharpe * np.sqrt(1 / hold_time_ratio))

        # multi‑symbol diversification (ρ = 0.7)
        ρ = 0.7
        enh["multi_symbol"] = EdgeMetrics(base.tau, base.n_trades * symbol_count, base.mean_bp, base.std_bp * np.sqrt((1 + (symbol_count - 1) * ρ) / symbol_count), base.sharpe * np.sqrt(symbol_count / (1 + (symbol_count - 1) * ρ)))

        # ensemble models (ρ = 0.4)
        ρm = 0.4
        enh["model_ensemble"] = EdgeMetrics(base.tau, base.n_trades * model_count, base.mean_bp, base.std_bp * np.sqrt((1 + (model_count - 1) * ρm) / model_count), base.sharpe * np.sqrt(model_count / (1 + (model_count - 1) * ρm)))

        return enh

    def plot_enhancement_comparison(self, enh: Dict[str, EdgeMetrics]) -> None:
        """Bar chart of Sharpe & trade count across enhancements."""
        names = list(enh)
        sharpes = [m.sharpe for m in enh.values()]
        trades = [m.n_trades for m in enh.values()]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(9, 7), sharex=True)

        ax1.bar(names, sharpes)
        ax1.set_ylabel("Sharpe ratio")
        ax1.set_title("Sharpe by enhancement")

        ax2.bar(names, trades, color="tab:orange")
        ax2.set_ylabel("Trades/day")
        ax2.set_title("Trade frequency by enhancement")
        self._bar_xticks(ax1)

        plt.tight_layout()
        plt.show()

    def analyze_edge(self, probs: np.ndarray, returns: np.ndarray) -> Dict[str, Any]:
        """Analyze edge characteristics across probability thresholds.
        
        Args:
            probs: Predicted probabilities
            returns: Actual returns
            
        Returns:
            Dict containing analysis results including optimal thresholds and metrics
        """
        results = []
        
        for threshold in self.prob_thresholds:
            # Get trades above threshold
            mask = probs >= threshold
            n_trades = np.sum(mask)
            
            if n_trades < self.min_trades:
                continue
                
            trade_returns = returns[mask]
            
            # Calculate key metrics
            mean_return = np.mean(trade_returns) 
            std_return = np.std(trade_returns)
            edge_bp = (mean_return - self.base_cost) * 10000  # Convert to bp
            
            if std_return > 0:
                sharpe = np.sqrt(252) * (mean_return - self.base_cost) / std_return
            else:
                sharpe = 0
                
            win_rate = np.mean(trade_returns > self.base_cost)
            
            results.append({
                'threshold': threshold,
                'n_trades': n_trades,
                'edge_bp': edge_bp,
                'sharpe': sharpe,
                'win_rate': win_rate,
                'mean_return': mean_return,
                'std_return': std_return
            })
            
        if not results:
            return {
                'optimal_threshold': None,
                'max_edge': 0,
                'max_sharpe': 0,
                'metrics': None
            }
            
        # Convert to DataFrame for analysis
        df = pd.DataFrame(results)
        
        # Find optimal threshold meeting minimum criteria
        valid_trades = df[
            (df.edge_bp >= self.min_edge_bp) & 
            (df.sharpe >= self.min_sharpe) &
            (df.n_trades >= self.min_trades)
        ]
        
        if len(valid_trades) == 0:
            return {
                'optimal_threshold': None,
                'max_edge': df.edge_bp.max(),
                'max_sharpe': df.sharpe.max(),
                'metrics': df.to_dict('records')
            }
            
        # Select threshold that maximizes Sharpe among valid trades
        optimal = valid_trades.loc[valid_trades.sharpe.idxmax()]
        
        return {
            'optimal_threshold': optimal.threshold,
            'max_edge': optimal.edge_bp,
            'max_sharpe': optimal.sharpe,
            'metrics': df.to_dict('records')
        }

    def plot_edge_analysis(self, metrics: List[Dict]) -> None:
        """Plot edge analysis results.
        
        Args:
            metrics: List of dictionaries containing analysis metrics
        """
        df = pd.DataFrame(metrics)
        
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(12, 8))
        
        # Edge vs Threshold
        ax1.plot(df.threshold, df.edge_bp, 'b-')
        ax1.axhline(y=self.min_edge_bp, color='r', linestyle='--', alpha=0.5)
        ax1.set_xlabel('Probability Threshold')
        ax1.set_ylabel('Edge (bp)')
        ax1.set_title('Edge vs Threshold')
        ax1.grid(True)
        
        # Sharpe vs Threshold
        ax2.plot(df.threshold, df.sharpe, 'g-')
        ax2.axhline(y=self.min_sharpe, color='r', linestyle='--', alpha=0.5)
        ax2.set_xlabel('Probability Threshold')
        ax2.set_ylabel('Sharpe Ratio')
        ax2.set_title('Sharpe vs Threshold')
        ax2.grid(True)
        
        # Number of Trades vs Threshold
        ax3.plot(df.threshold, df.n_trades, 'm-')
        ax3.axhline(y=self.min_trades, color='r', linestyle='--', alpha=0.5)
        ax3.set_xlabel('Probability Threshold')
        ax3.set_ylabel('Number of Trades')
        ax3.set_title('Trade Count vs Threshold')
        ax3.grid(True)
        
        # Win Rate vs Threshold
        ax4.plot(df.threshold, df.win_rate * 100, 'c-')
        ax4.set_xlabel('Probability Threshold')
        ax4.set_ylabel('Win Rate (%)')
        ax4.set_title('Win Rate vs Threshold')
        ax4.grid(True)
        
        plt.tight_layout()
        plt.show()

    def track_sharpe_evolution(
        self,
        val_probs: np.ndarray,   # shape (n, 2) – [p(long), p(short)]
        returns: np.ndarray,     # realised returns aligned with rows
        tau: float,             # fixed threshold to track
        window_sizes: List[float] = None  # trading days to evaluate (can be fractional)
    ) -> pd.DataFrame:
        """Track Sharpe ratio evolution as we accumulate more data.
        
        Args:
            val_probs: Probability predictions [p(long), p(short)]
            returns: Realized returns aligned with predictions
            tau: Fixed probability threshold to evaluate
            window_sizes: List of trading day windows to evaluate (can be fractional for hours)
            
        Returns:
            DataFrame with Sharpe evolution metrics
        """
        if window_sizes is None:
            # Default to 4h, 8h, 12h, 24h, 48h, 96h windows
            window_sizes = [4/24, 8/24, 12/24, 1, 2, 4]
            
        results = []
        LONG, SHORT = 0, 1
        
        # Get trades at fixed threshold
        sig_long = val_probs[:, LONG] > tau
        sig_short = val_probs[:, SHORT] > tau
        trades = sig_long | sig_short
        
        if not trades.any():
            return pd.DataFrame()
            
        pnl = returns[trades] - self.base_cost
        n_tr = trades.sum()
        
        for days in window_sizes:
            # Scale metrics for this window
            annual_scale = np.sqrt(252 / days)  # Scale to annual
            
            mean_bp = pnl.mean() * 1e4
            std_bp = pnl.std(ddof=0) * 1e4
            sharpe = (mean_bp / std_bp) * np.sqrt(n_tr * days / len(returns)) * annual_scale
            
            results.append({
                'window_days': days,
                'window_hours': days * 24,  # Add hours for reference
                'n_trades': n_tr,
                'mean_bp': mean_bp,
                'std_bp': std_bp, 
                'sharpe': sharpe
            })
            
        df = pd.DataFrame(results)
        # Add hour-based labels
        df['window_label'] = df['window_hours'].astype(int).astype(str) + 'h'
        return df

    def plot_sharpe_evolution(self, evolution_df: pd.DataFrame) -> None:
        """Plot Sharpe ratio evolution over different time windows.
        
        Args:
            evolution_df: DataFrame from track_sharpe_evolution
        """
        if evolution_df.empty:
            return
            
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        
        # Use hour labels if available, otherwise use days
        x_values = evolution_df.get('window_label', evolution_df['window_days'].astype(str) + 'd')
        
        # Sharpe evolution
        ax1.plot(x_values, evolution_df.sharpe, 
                marker='o', color='tab:blue')
        ax1.set_xlabel('Window Size')
        ax1.set_ylabel('Annualized Sharpe')
        ax1.set_title('Sharpe Ratio Evolution')
        ax1.grid(True)
        plt.setp(ax1.get_xticklabels(), rotation=45, ha='right')
        
        # Edge stability
        ax2.errorbar(x_values, evolution_df.mean_bp,
                    yerr=evolution_df.std_bp, fmt='o', capsize=5,
                    color='tab:green')
        ax2.set_xlabel('Window Size')
        ax2.set_ylabel('Edge (bp)')
        ax2.set_title('Edge Stability (Mean ± Std)')
        ax2.grid(True)
        plt.setp(ax2.get_xticklabels(), rotation=45, ha='right')
        
        plt.tight_layout()
        plt.show()

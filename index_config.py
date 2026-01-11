"""
Index Configuration Registry - Single source of truth for index-specific parameters

This module provides index-agnostic configuration for the gamma GEX scalper.
All index-specific values (spreads, multipliers, symbols) are centralized here.

Created: 2026-01-10 (Generalized scalper refactor)
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class IndexConfig:
    """Immutable configuration for a tradeable index."""

    # ============== Identity ==============
    code: str              # 'SPX' or 'NDX'
    name: str              # 'S&P 500' or 'Nasdaq-100'

    # ============== Symbols ==============
    index_symbol: str      # 'SPX' or 'NDX' (for Tradier quotes)
    etf_symbol: str        # 'SPY' or 'QQQ' (fallback proxy)
    option_root: str       # 'SPXW' or 'NDXW' (OCC root symbol)
    vix_symbol: str        # 'VIX' for both (same VIX)

    # ============== Price Conversion ==============
    etf_multiplier: float  # SPY×10=SPX, QQQ×42.5=NDX

    # ============== Strike Configuration ==============
    strike_increment: int  # 5 for SPX, 25 for NDX
    base_spread_width: int # 5 for SPX, 25 for NDX

    # ============== GEX Distance Thresholds ==============
    # (scaled by strike_increment)
    near_pin_max: int      # 6 for SPX (~1 strike), 30 for NDX (~1 strike)
    moderate_max: int      # 15 for SPX, 75 for NDX
    far_max: int           # 50 for SPX, 250 for NDX

    # ============== Buffer Distances ==============
    ic_wing_buffer: int    # 20 for SPX, 100 for NDX
    moderate_buffer: int   # 15 for SPX, 75 for NDX
    far_buffer: int        # 25 for SPX, 125 for NDX

    # ============== Contract Specifications ==============
    contract_multiplier: int = 100  # $100 per point (same for both)

    # ============== Position Limits ==============
    max_daily_positions: int = 3
    max_contracts_per_trade: int = 3

    # ============== Spread Quality ==============
    max_spread_pct: float = 0.25  # Max bid-ask spread (25% for SPX, may adjust for NDX)

    def round_strike(self, price: float) -> int:
        """Round price to nearest strike increment."""
        return round(price / self.strike_increment) * self.strike_increment

    def get_spread_width(self, vix: float) -> int:
        """
        Get VIX-adjusted spread width.

        Higher VIX → wider spreads to reduce risk.

        Args:
            vix: Current VIX level

        Returns:
            Spread width in points (5/10/15/20 for SPX, 25/50/75/100 for NDX)
        """
        if vix < 15:
            return self.base_spread_width
        elif vix < 20:
            return self.base_spread_width * 2
        elif vix < 25:
            return self.base_spread_width * 3
        else:
            return self.base_spread_width * 4

    def format_option_symbol(self, expiry: str, opt_type: str, strike: float) -> str:
        """
        Format OCC option symbol.

        Args:
            expiry: '250110' format (YYMMDD)
            opt_type: 'C' or 'P'
            strike: Strike price (will be multiplied by 1000)

        Returns:
            OCC symbol like 'SPXW250110C06000000' or 'NDXW250110C21500000'
        """
        strike_formatted = int(float(strike) * 1000)
        return f"{self.option_root}{expiry}{opt_type}{strike_formatted:08d}"

    def get_min_credit(self, hour_et: int) -> float:
        """
        Get minimum credit threshold scaled for index.

        NDX spreads are 5× wider than SPX (25pt vs 5pt), so credits
        should be ~5× larger to maintain similar risk/reward.

        Args:
            hour_et: Hour in ET timezone (0-23)

        Returns:
            Minimum credit in dollars
        """
        # Base thresholds (SPX with 5pt spreads - REALISTIC 0DTE PRICING)
        # Updated 2026-01-11: Changed from weekly pricing (1.25/1.50/2.00) to 0DTE
        base_credits = {
            (0, 11): 0.40,   # Before 11 AM - morning premium higher
            (11, 13): 0.50,  # 11 AM - 1 PM - baseline 0DTE
            (13, 24): 0.65,  # After 1 PM - afternoon theta decay
        }

        # Scale factor: NDX 25pt spread should require ~5x credit
        scale = self.base_spread_width / 5

        for (start, end), credit in base_credits.items():
            if start <= hour_et < end:
                return credit * scale

        return 2.00 * scale

    def validate_strike_sanity(self, strike: float, current_price: float) -> bool:
        """
        Validate strike is reasonable relative to current price.

        Args:
            strike: Strike price to validate
            current_price: Current underlying price

        Returns:
            True if strike is valid, False otherwise
        """
        distance = abs(strike - current_price)
        max_distance = current_price * 0.10  # 10% max distance

        if distance > max_distance:
            return False

        if strike % self.strike_increment != 0:
            return False

        return True


# ============================================================================
#                           INDEX REGISTRY
# ============================================================================

SPX_CONFIG = IndexConfig(
    code='SPX',
    name='S&P 500',
    index_symbol='SPX',
    etf_symbol='SPY',
    option_root='SPXW',
    vix_symbol='VIX',
    etf_multiplier=10.0,
    strike_increment=5,
    base_spread_width=5,
    near_pin_max=6,
    moderate_max=15,
    far_max=50,
    ic_wing_buffer=20,
    moderate_buffer=15,
    far_buffer=25,
    max_daily_positions=3,
    max_contracts_per_trade=3,
    max_spread_pct=0.25,
)

NDX_CONFIG = IndexConfig(
    code='NDX',
    name='Nasdaq-100',
    index_symbol='NDX',
    etf_symbol='QQQ',
    option_root='NDXW',
    vix_symbol='VIX',
    etf_multiplier=42.5,
    strike_increment=25,
    base_spread_width=25,
    near_pin_max=30,       # ~1 strike in NDX terms
    moderate_max=75,       # ~3 strikes
    far_max=250,           # ~10 strikes
    ic_wing_buffer=100,    # ~4 strikes
    moderate_buffer=75,    # ~3 strikes
    far_buffer=125,        # ~5 strikes
    max_daily_positions=3,
    max_contracts_per_trade=3,
    max_spread_pct=0.30,   # NDX has wider bid-ask spreads
)

# Registry for easy lookup
INDEX_REGISTRY: Dict[str, IndexConfig] = {
    'SPX': SPX_CONFIG,
    'NDX': NDX_CONFIG,
}


def get_index_config(index_code: str) -> IndexConfig:
    """
    Get configuration for an index.

    Args:
        index_code: 'SPX' or 'NDX'

    Returns:
        IndexConfig for the specified index

    Raises:
        ValueError: If index_code is not supported
    """
    index_code = index_code.upper()
    if index_code not in INDEX_REGISTRY:
        supported = ', '.join(INDEX_REGISTRY.keys())
        raise ValueError(f"Unsupported index: {index_code}. Supported: {supported}")
    return INDEX_REGISTRY[index_code]


def get_supported_indices() -> list:
    """Return list of supported index codes."""
    return list(INDEX_REGISTRY.keys())

#!/usr/bin/env python3
"""
Dual Strategy Configuration

Enables running both GEX and OTM strategies simultaneously with proper
conflict detection and capital allocation.

IMPORTANT: Set DUAL_STRATEGY_ENABLED = True to activate dual mode.
Default is False for safety (GEX primary, OTM fallback only).
"""

# =============================================================================
# DUAL STRATEGY MODE
# =============================================================================

# Enable both GEX and OTM strategies simultaneously
# False = GEX primary, OTM fallback (current safe behavior)
# True = Both strategies run in parallel (with conflict detection)
DUAL_STRATEGY_ENABLED = False  # Start with False, enable after testing

# =============================================================================
# POSITION LIMITS
# =============================================================================

# Maximum total positions across all strategies
MAX_POSITIONS_TOTAL = 3  # Tradier sandbox limit

# Maximum positions per strategy (prevents one strategy from dominating)
MAX_POSITIONS_PER_STRATEGY = 2  # 2 GEX max, 2 OTM max

# =============================================================================
# CAPITAL ALLOCATION
# =============================================================================

# How to split capital between strategies
# Options: 'equal', 'proportional', 'priority'
CAPITAL_ALLOCATION_MODE = 'priority'

# Priority mode: GEX gets more capital (it's more profitable)
GEX_CAPITAL_FRACTION = 0.70  # 70% to GEX
OTM_CAPITAL_FRACTION = 0.30  # 30% to OTM

# Equal mode: Split evenly
# GEX_CAPITAL_FRACTION = 0.50
# OTM_CAPITAL_FRACTION = 0.50

# =============================================================================
# CONFLICT DETECTION
# =============================================================================

# Minimum distance between positions (in points)
MIN_DISTANCE_SAME_STRATEGY = 20  # GEX-to-GEX or OTM-to-OTM (4 strikes for SPX)
MIN_DISTANCE_DIFF_STRATEGY = 15  # GEX-to-OTM (3 strikes for SPX)

# For NDX (strikes are 5x wider), multiply by 5
# Will be auto-adjusted based on INDEX_CONFIG.code

# Allow same-side positions?
ALLOW_SAME_SIDE_DUAL = True  # True = allow PUT+PUT or CALL+CALL if far enough apart
                              # False = only allow opposite sides (PUT+CALL)

# =============================================================================
# STRATEGY PRIORITY
# =============================================================================

# Which strategy gets priority in conflicts?
# 'GEX' = Always enter GEX first, skip OTM if conflict
# 'OTM' = Always enter OTM first, skip GEX if conflict (not recommended!)
# 'first' = Whichever checks first wins
CONFLICT_PRIORITY = 'GEX'  # GEX is more profitable, so it gets priority

# =============================================================================
# AUTOSCALING
# =============================================================================

# How to calculate contracts for each strategy
# Options: 'combined', 'separate'
AUTOSCALING_MODE = 'separate'

# Combined mode: One Kelly calculation using all trades
# - Simpler
# - Faster scaling after wins
# - But doesn't account for strategy-specific performance

# Separate mode: Kelly calculation per strategy
# - More accurate
# - Each strategy scales based on its own performance
# - But more complex bookkeeping

# =============================================================================
# MONITORING & LOGGING
# =============================================================================

# Log all conflict detections?
LOG_CONFLICTS = True

# Log capital allocation decisions?
LOG_CAPITAL_ALLOCATION = True

# Discord alerts for dual strategy events?
DISCORD_ALERT_DUAL_ENTRY = True  # Alert when both strategies enter simultaneously
DISCORD_ALERT_CONFLICTS = True   # Alert when conflict prevents entry

# =============================================================================
# SAFETY LIMITS
# =============================================================================

# Maximum correlated exposure
# If both strategies on same side (PUT or CALL), limit total contracts
MAX_SAME_SIDE_CONTRACTS = 5  # Don't have more than 5 contracts total on same side

# Emergency halt if too many conflicts
MAX_CONFLICTS_PER_HOUR = 10  # If >10 conflicts in 1 hour, something is wrong
                              # Disable dual mode and alert

# =============================================================================
# TESTING / DEBUG
# =============================================================================

# Dry-run mode: Check for conflicts but don't actually enter OTM trades
# Useful for testing dual mode without risking capital
DRY_RUN_OTM = False  # Set True to log OTM setups without entering

# Verbose logging for debugging
VERBOSE_CONFLICT_LOGGING = False  # Set True for detailed conflict logs

# =============================================================================
# VALIDATION
# =============================================================================

def validate_config():
    """Validate configuration settings."""

    errors = []

    # Check capital allocation sums to 1.0
    if abs((GEX_CAPITAL_FRACTION + OTM_CAPITAL_FRACTION) - 1.0) > 0.01:
        errors.append(
            f"Capital allocation doesn't sum to 1.0: "
            f"GEX {GEX_CAPITAL_FRACTION} + OTM {OTM_CAPITAL_FRACTION} = "
            f"{GEX_CAPITAL_FRACTION + OTM_CAPITAL_FRACTION}"
        )

    # Check position limits make sense
    if MAX_POSITIONS_PER_STRATEGY * 2 > MAX_POSITIONS_TOTAL:
        errors.append(
            f"MAX_POSITIONS_PER_STRATEGY ({MAX_POSITIONS_PER_STRATEGY}) * 2 "
            f"exceeds MAX_POSITIONS_TOTAL ({MAX_POSITIONS_TOTAL})"
        )

    # Check conflict priority is valid
    if CONFLICT_PRIORITY not in ['GEX', 'OTM', 'first']:
        errors.append(
            f"Invalid CONFLICT_PRIORITY: {CONFLICT_PRIORITY} "
            f"(must be 'GEX', 'OTM', or 'first')"
        )

    # Check modes are valid
    if CAPITAL_ALLOCATION_MODE not in ['equal', 'proportional', 'priority']:
        errors.append(
            f"Invalid CAPITAL_ALLOCATION_MODE: {CAPITAL_ALLOCATION_MODE}"
        )

    if AUTOSCALING_MODE not in ['combined', 'separate']:
        errors.append(
            f"Invalid AUTOSCALING_MODE: {AUTOSCALING_MODE}"
        )

    if errors:
        print("="*80)
        print("DUAL STRATEGY CONFIG VALIDATION ERRORS:")
        print("="*80)
        for error in errors:
            print(f"  ❌ {error}")
        print("="*80)
        return False

    return True


if __name__ == '__main__':
    """Validate configuration when run directly."""

    print("="*80)
    print("DUAL STRATEGY CONFIGURATION")
    print("="*80)
    print()
    print(f"Dual Mode Enabled: {DUAL_STRATEGY_ENABLED}")
    print(f"Position Limits: {MAX_POSITIONS_TOTAL} total, {MAX_POSITIONS_PER_STRATEGY} per strategy")
    print(f"Capital Allocation: GEX {GEX_CAPITAL_FRACTION:.0%}, OTM {OTM_CAPITAL_FRACTION:.0%}")
    print(f"Conflict Priority: {CONFLICT_PRIORITY}")
    print(f"Autoscaling Mode: {AUTOSCALING_MODE}")
    print(f"Min Distance (same strategy): {MIN_DISTANCE_SAME_STRATEGY} points")
    print(f"Min Distance (diff strategy): {MIN_DISTANCE_DIFF_STRATEGY} points")
    print()

    if validate_config():
        print("✅ Configuration is valid!")
    else:
        print("❌ Configuration has errors - fix before enabling dual mode")
        exit(1)

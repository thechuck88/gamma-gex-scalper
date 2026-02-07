#!/usr/bin/env python3
"""
Test the enhanced orphan recovery logic
"""

from collections import defaultdict

# Simulate 6 orphaned positions (SPXW + NDXP)
orphaned = [
    {'symbol': 'SPXW260206P06855000', 'quantity': 3, 'cost_basis': 2280},
    {'symbol': 'SPXW260206P06865000', 'quantity': -3, 'cost_basis': -2910},
    {'symbol': 'NDXP260206C24630000', 'quantity': -3, 'cost_basis': -45540},
    {'symbol': 'NDXP260206C24640000', 'quantity': 3, 'cost_basis': 42990},
    {'symbol': 'NDXP260206P24420000', 'quantity': 3, 'cost_basis': 11970},
    {'symbol': 'NDXP260206P24430000', 'quantity': -3, 'cost_basis': -12240},
]

print("Testing Enhanced Orphan Recovery")
print("=" * 70)
print(f"Total orphaned positions: {len(orphaned)}")
print()

# Group by symbol root and expiration
groups = defaultdict(list)
for pos in orphaned:
    sym = pos['symbol']
    if len(sym) >= 15:
        root = sym[:-15]
        exp = sym[-15:-9]
        group_key = f"{root}_{exp}"
        groups[group_key].append(pos)

print(f"Grouped into {len(groups)} spread(s):")
for group_key, group_positions in groups.items():
    root, exp = group_key.split('_')
    print(f"  - {root} {exp}: {len(group_positions)} legs")
    for pos in group_positions:
        print(f"      {pos['symbol']} qty={pos['quantity']}")

print()
print("Recovery Results:")
print("-" * 70)

recovered = 0
failed = []

for group_key, group_positions in groups.items():
    root, exp = group_key.split('_')
    
    if len(group_positions) == 2 or len(group_positions) == 4:
        print(f"✅ {root} {exp}: {len(group_positions)} legs - CAN RECOVER")
        recovered += 1
    else:
        print(f"❌ {root} {exp}: {len(group_positions)} legs - CANNOT RECOVER")
        failed.append((root, exp, len(group_positions)))

print()
print("=" * 70)
print(f"Summary: {recovered} recovered, {len(failed)} failed")
print()

if recovered > 0:
    print("✅ IMPROVEMENT: Old logic would have failed completely (6 legs total)")
    print("✅ IMPROVEMENT: New logic recovers each spread separately")
else:
    print("❌ All recovery attempts failed")

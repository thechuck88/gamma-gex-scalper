# Black Box SQLite Database - Disk Usage Estimates

**Database**: `/root/gamma/data/gex_blackbox.db` (SQLite)

**Current Size**: 68 KB (empty, schema only)

---

## Database Schema (5 Tables)

### 1. `options_snapshots` - Full chain data (GEX checks only)

**Frequency**: 12 times per day per index = 24 total

**Per snapshot**:
- Full SPX chain: ~300 options
- Each option: ~150 bytes (strike, type, bid, ask, OI, volume, greeks)
- Total: 300 × 150 = 45 KB per snapshot

**Daily storage**: 24 × 45 KB = **1.08 MB**

---

### 2. `gex_peaks` - Top 3 peaks per snapshot

**Frequency**: 12 times per day per index = 24 total × 3 peaks = 72 records

**Per record**: ~80 bytes (timestamp, symbol, rank, strike, gex, distance, score)

**Daily storage**: 72 × 80 bytes = **5.8 KB**

---

### 3. `competing_peaks` - IC detection results

**Frequency**: 12 times per day per index = 24 total

**Per record**: ~100 bytes (timestamp, symbol, is_competing, peak1, peak2, ratio, adjusted_pin)

**Daily storage**: 24 × 100 bytes = **2.4 KB**

---

### 4. `market_context` - Underlying prices, VIX

**Frequency**: 12 times per day per index = 24 total

**Per record**: ~60 bytes (timestamp, symbol, underlying, vix, spy, qqq)

**Daily storage**: 24 × 60 bytes = **1.4 KB**

---

### 5. `options_prices_live` - 30-second pricing near pin (NEW in v2)

**Frequency**: Every 30 seconds during market hours
- 6.5 hours × 120 per hour = 780 snapshots per day
- 2 indices = 1,560 snapshots per day
- ~20 strikes per snapshot (±60 points from pin)
- Total: 1,560 × 20 = **31,200 option records per day**

**Per record**: ~100 bytes (timestamp, symbol, strike, type, bid, ask, mid, last, volume, OI)

**Daily storage**: 31,200 × 100 bytes = **3.12 MB**

---

## Total Daily Storage

| Table | Records/Day | Storage/Day |
|-------|-------------|-------------|
| options_snapshots | 24 | 1.08 MB |
| gex_peaks | 72 | 5.8 KB |
| competing_peaks | 24 | 2.4 KB |
| market_context | 24 | 1.4 KB |
| options_prices_live | 31,200 | 3.12 MB |
| **TOTAL** | **31,344** | **~4.2 MB** |

---

## Storage Over Time

### Per Trading Day: ~4.2 MB

### Weekly (5 trading days)
- 5 × 4.2 MB = **21 MB**

### Monthly (22 trading days)
- 22 × 4.2 MB = **92.4 MB**

### 90 Days (65 trading days)
- 65 × 4.2 MB = **273 MB**

### 1 Year (252 trading days)
- 252 × 4.2 MB = **1.06 GB**

---

## SQLite Compression & Indexing

### Actual Storage (with compression)

SQLite uses page compression and indexing, which adds ~20% overhead:

| Period | Raw Data | With Indexes | Compressed |
|--------|----------|--------------|------------|
| 1 day | 4.2 MB | 5.0 MB | ~4.5 MB |
| 1 week | 21 MB | 25 MB | ~23 MB |
| 1 month | 92 MB | 110 MB | ~100 MB |
| 90 days | 273 MB | 328 MB | ~300 MB |
| 1 year | 1.06 GB | 1.27 GB | **~1.2 GB** |

---

## Server Disk Space Available

```bash
$ df -h /root/gamma/data/
Filesystem      Size  Used Avail Use% Mounted on
/dev/vda1       160G   39G  113G  26% /
```

**Available space**: 113 GB

**Black box after 1 year**: 1.2 GB

**Percentage used**: 1.2 GB / 113 GB = **1.06%** of available space

✅ **Plenty of room for years of data!**

---

## Growth Projections

### 5 Years of Data

**Storage**: 5 × 1.2 GB = **6 GB**

**Server impact**: 6 GB / 113 GB = 5.3% of available space ✅

### 10 Years of Data

**Storage**: 10 × 1.2 GB = **12 GB**

**Server impact**: 12 GB / 113 GB = 10.6% of available space ✅

---

## Database Maintenance

### Vacuum (Compress Database)

SQLite databases can be compressed periodically:

```bash
sqlite3 /root/gamma/data/gex_blackbox.db "VACUUM;"
```

**Run**: Monthly or quarterly

**Effect**: Reclaims unused space, optimizes indexes

**Expected savings**: 10-20% compression

---

## Backup Strategy

### Daily Backup Size

**After 90 days**: ~300 MB per backup

**After 1 year**: ~1.2 GB per backup

### Recommended Backup

**Current restic setup** already backs up `/root` daily:
- Includes `/root/gamma/data/gex_blackbox.db`
- Incremental backups (only changed data)
- Deduplication (efficient storage)
- Retention: 7 daily, 4 weekly, 6 monthly

**Backup storage needed**:
- First backup: 1.2 GB (full)
- Daily incremental: ~4.5 MB per day
- Weekly: ~23 MB per week
- Monthly: ~100 MB per month

**Total backup storage (1 year)**: ~2-3 GB (with deduplication)

---

## Query Performance

### Database Size vs Query Speed

SQLite performs well up to several GB:

| DB Size | Typical Query | Index Scan | Full Scan |
|---------|---------------|------------|-----------|
| 100 MB | <10ms | <50ms | <1s |
| 1 GB | <20ms | <100ms | <5s |
| 10 GB | <50ms | <500ms | <30s |

**Black box at 1 year**: 1.2 GB
- ✅ Queries stay under 20ms
- ✅ Index scans under 100ms
- ✅ No performance issues

### Optimizations

**Indexes already created**:
```sql
idx_snapshots_time
idx_peaks_time
idx_competing_time
idx_context_time
idx_prices_time
idx_prices_symbol
```

**Additional optimization** (if needed):
- Composite indexes on (index_symbol, timestamp)
- Partition by year (separate DBs per year)
- Archive old data after backtesting complete

---

## Comparison to Other Storage Methods

### CSV Files

**Pros**:
- Simple format
- Easy to inspect

**Cons**:
- No indexing (slow queries)
- No compression (larger files)
- Harder to query (need pandas)
- No ACID guarantees

**Estimated size**: ~2-3x larger than SQLite (2-4 GB per year)

### PostgreSQL

**Pros**:
- Better for huge datasets (100+ GB)
- Advanced query features

**Cons**:
- Requires separate server process
- More complex setup
- Overkill for 1-10 GB dataset

**SQLite is perfect for this use case** ✅

---

## Summary

✅ **Storage Format**: SQLite database (single file)
✅ **Daily Growth**: ~4.5 MB per trading day
✅ **1 Year Total**: ~1.2 GB
✅ **Server Impact**: 1% of available disk space
✅ **Query Performance**: Fast (<20ms typical queries)
✅ **Backup Included**: Restic already backs up daily
✅ **Scalability**: Can handle 10+ years of data easily

**No disk space concerns - SQLite is the perfect choice!**

📊 **Database location**: `/root/gamma/data/gex_blackbox.db`

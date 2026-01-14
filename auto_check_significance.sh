#!/bin/bash
# Auto-check statistical significance every 5 minutes during trading hours

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

LAST_SIGNIFICANT=0

while true; do
    # Run during trading hours (9:30 AM - 4:00 PM ET)
    HOUR=$(date +%H)
    MIN=$(date +%M)
    DOW=$(date +%u)

    # Only run Mon-Fri (1-5), 9:30-16:00
    if [[ $DOW -lt 6 ]] && [[ $HOUR -ge 9 && ($HOUR -lt 16 || ($HOUR -eq 16 && $MIN -lt 1)) ]]; then

        # Run the monitor and capture output
        OUTPUT=$(cd /root/gamma && python3 monitor_statistical_significance.py 2>/dev/null)
        SIGNIFICANT=$(echo "$OUTPUT" | grep -c "STATISTICALLY SIGNIFICANT")
        TRADES=$(echo "$OUTPUT" | grep "Trades analyzed:" | awk '{print $3}')

        # Check if we just crossed the threshold
        if [[ $SIGNIFICANT -eq 1 && $LAST_SIGNIFICANT -eq 0 ]]; then
            echo -e "\n${GREEN}🎉 ALERT: STATISTICAL SIGNIFICANCE REACHED!${NC}"
            echo "$OUTPUT"

            # Send Discord notification if available
            if [[ -n "$DISCORD_WEBHOOK" ]]; then
                curl -X POST "$DISCORD_WEBHOOK" \
                    -H "Content-Type: application/json" \
                    -d "{\"content\": \"🎉 GEX Scalper has achieved 95% statistical confidence! $(echo "$OUTPUT" | grep "Confidence level" | xargs)\"}}"
            fi

            LAST_SIGNIFICANT=1

        elif [[ $SIGNIFICANT -eq 1 ]]; then
            # Already significant, just show brief update
            echo -e "${GREEN}✅ Still significant - Trades: $TRADES${NC}"
            LAST_SIGNIFICANT=1

        else
            # Not yet significant, show progress
            PROGRESS=$(echo "$OUTPUT" | grep "Progress:" | awk '{print $3}')
            echo -e "${YELLOW}⏳ Still testing - $TRADES trades, $PROGRESS to 95% confidence${NC}"
            LAST_SIGNIFICANT=0
        fi
    fi

    # Check every 5 minutes
    sleep 300
done

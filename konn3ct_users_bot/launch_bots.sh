#!/bin/bash

# Configuration
URL="https://konnectsandbox.convergenceondemand.com/conferencing/join/Ode0S146a"
BOTS=10
DELAY=5

echo "🚀 Launching $BOTS bots one by one (delay: ${DELAY}s)..."

# Trap Ctrl+C to kill all background bots
trap 'echo "🛑 Stopping all bots..."; kill $(jobs -p); exit' SIGINT SIGTERM

for ((i=1; i<=BOTS; i++)); do
    echo "[$i/$BOTS] Starting bot..."
    
    # Run the single bot script in the background (&)
    python py_guest_single.py --url "$URL" &
    
    # Wait before starting the next bot
    if [ $i -lt $BOTS ]; then
        sleep $DELAY
    fi
done

echo "✅ All $BOTS bots launched!"
echo "Press Ctrl+C to stop all bots."

# Wait for all background processes to finish
wait

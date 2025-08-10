#!/bin/bash
# Find the directory where the script is located
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Start the Python server
python3 "$DIR/proxy_server.py" &

# Optional: Open browser tabs (works on most Linux desktops and macOS)
echo "Server started. Opening LMArena and Monitor pages..."
sleep 2
(xdg-open "https://lmarena.ai" 2>/dev/null || open "https://lmarena.ai") &
(xdg-open "http://localhost:9080/monitor" 2>/dev/null || open "http://localhost:9080/monitor") &

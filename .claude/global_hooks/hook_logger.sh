#!/bin/bash
# Log hook activity for statusline display
# Usage: source from hook commands or call directly
# hook_logger.sh <hook_name>
echo "$(date +%s) $1" > /tmp/aipass-hook-last

#!/bin/zsh

/usr/bin/osascript <<'APPLESCRIPT'
display notification "Prepare the main-branch report for the last 5-3 commits in devHeyData/heydata." with title "Report reminder"
APPLESCRIPT

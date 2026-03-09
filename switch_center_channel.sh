#!/usr/bin/env bash
# Switch the center PiP Chrome window to the given channel and put it back in full screen.
# Usage: switch_center_channel.sh aljazeera|dw|bloomberg|france24
#   aljazeera → Al Jazeera English live
#   dw        → Deutsche Welle Live
#   bloomberg → Bloomberg Live
#   france24  → France 24 English live
set -e
case "${1:-}" in
  aljazeera|aj)
    NEW_URL="https://www.youtube.com/@aljazeeraenglish/live"
    MATCH_FOR="dw"
    ;;
  dw|deutschewelle)
    NEW_URL="https://www.youtube.com/user/deutschewelleenglish/live"
    MATCH_FOR="aljazeera"
    ;;
  bloomberg)
    NEW_URL="https://www.youtube.com/watch?v=DxmDPrfinXY"
    MATCH_FOR="dw"
    ;;
  france24)
    NEW_URL="https://www.youtube.com/c/FRANCE24English/live"
    MATCH_FOR="dw"
    ;;
  *)
    echo "Usage: $0 aljazeera|dw|bloomberg|france24" >&2
    exit 1
    ;;
esac
osascript << APPLESCRIPT
tell application "Google Chrome" to activate
delay 0.3
tell application "Google Chrome"
  set newURL to "$NEW_URL"
  set matchFor to "$MATCH_FOR"
  repeat with w in every window
    try
      set tabURL to URL of active tab of w
      set tabTitle to title of active tab of w
      set doMatch to false
      if matchFor is "dw" then
        set doMatch to (tabURL contains "deutschewelleenglish" or tabURL contains "dwnews")
      else if matchFor is "aljazeera" then
        set doMatch to (tabURL contains "aljazeera" or tabTitle contains "Inside Story" or tabTitle contains "Al Jazeera")
      end if
      if doMatch then
        set URL of active tab of w to newURL
        set index of w to 1
        exit repeat
      end if
    end try
  end repeat
end tell
tell application "Google Chrome" to activate
delay 1.2
tell application "System Events"
  tell process "Google Chrome"
    if (count of windows) > 0 then
      perform action "AXRaise" of window 1
      delay 0.4
    end if
  end tell
  keystroke "f"
end tell
APPLESCRIPT
echo "switched center to $1"
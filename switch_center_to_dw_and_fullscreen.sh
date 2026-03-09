#!/usr/bin/env bash
# Switch the Chrome window that shows the center PiP (e.g. Al Jazeera/Inside Story) to Deutsche Welle Live and put it back in full screen.
set -e
osascript << 'APPLESCRIPT'
tell application "Google Chrome" to activate
delay 0.3
tell application "Google Chrome"
  set dwURL to "https://www.youtube.com/user/deutschewelleenglish/live"
  repeat with w in every window
    try
      set tabURL to URL of active tab of w
      set tabTitle to title of active tab of w
      if tabURL contains "7DFc83VE19E" or tabTitle contains "Inside Story" or tabURL contains "aljazeera" or tabTitle contains "Al Jazeera" then
        set URL of active tab of w to dwURL
        set index of w to 1
        exit repeat
      end if
    end try
  end repeat
end tell
tell application "Google Chrome" to activate
delay 0.8
tell application "System Events" to keystroke "f"
APPLESCRIPT

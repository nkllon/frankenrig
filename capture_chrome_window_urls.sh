#!/usr/bin/env bash
# List Google Chrome windows: index, URL, and title of the active tab in each.
# Run from terminal; output can be saved to evidence/obs_pip_source_urls.txt
# Usage: capture_chrome_window_urls.sh [output_file]

set -e
out="${1:--}"

list_chrome_tabs() {
  osascript 2>/dev/null << 'APPLESCRIPT'
tell application "Google Chrome"
  set out to ""
  set winList to every window
  repeat with w from 1 to count of winList
    set win to item w of winList
    set tabURL to ""
    set tabTitle to ""
    try
      set tabURL to URL of active tab of win
      set tabTitle to title of active tab of win
    end try
    set out to out & "window=" & w & " url=" & tabURL & " title=" & tabTitle & "\n"
  end repeat
  return out
end tell
APPLESCRIPT
}

if [[ "$out" == "-" ]]; then
  list_chrome_tabs
else
  list_chrome_tabs > "$out"
  echo "Written to $out"
fi

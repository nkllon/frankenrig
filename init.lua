pcall(require, "hs.ipc")

local mods = {"ctrl", "alt", "cmd"}
local pipKey = "p"
local obsKey = "o"
local obsAppName = "OBS"
local obsProjectorApiCmd = "/Users/lou/.hammerspoon/.venv_obsws/bin/python /Users/lou/.hammerspoon/obs_open_projector.py"
local obsMods = {"alt", "cmd"}
local obsFallbackMods = {"ctrl", "alt", "cmd"}

local function notify(title, text)
  hs.notify.new({ title = title, informativeText = text }):send()
end

local function pulse(text)
  hs.alert.closeAll()
  hs.alert.show(text, 0.8)
end

local function toggleChromePiP()
  local chrome = hs.application.get("Google Chrome")
  if not chrome then
    hs.application.launchOrFocus("Google Chrome")
    notify("YouTube PiP", "Opened Chrome. Start a YouTube video, then press the hotkey again.")
    return
  end

  local script = [[
    tell application "Google Chrome"
      if (count of windows) = 0 then return "NO_WINDOW"
      set t to active tab of front window
      set r to execute t javascript "(function(){const v=document.querySelector('video');if(!v)return 'NO_VIDEO';if(document.pictureInPictureElement){document.exitPictureInPicture();return 'PIP_OFF';}if(v.requestPictureInPicture){v.requestPictureInPicture();return 'PIP_ON';}return 'NO_API';})();"
      return r
    end tell
  ]]

  local ok, result = hs.osascript.applescript(script)
  if not ok then
    notify("YouTube PiP", "Permission/script error. Allow Hammerspoon to control Chrome in Privacy & Security > Automation.")
    return
  end

  if result == "PIP_ON" then
    notify("YouTube PiP", "PiP enabled")
  elseif result == "PIP_OFF" then
    notify("YouTube PiP", "PiP disabled")
  elseif result == "NO_VIDEO" then
    notify("YouTube PiP", "No video found on active tab.")
  elseif result == "NO_WINDOW" then
    notify("YouTube PiP", "No Chrome window open.")
  elseif result == "NO_API" then
    notify("YouTube PiP", "This page/video does not expose Picture-in-Picture API.")
  else
    notify("YouTube PiP", "Result: " .. tostring(result))
  end
end

local function ensureOBS()
  local app = hs.application.get(obsAppName)
  if app then
    return app
  end

  hs.application.launchOrFocus(obsAppName)
  for _ = 1, 10 do
    hs.timer.usleep(300000)
    app = hs.application.get(obsAppName)
    if app then
      return app
    end
  end
  return nil
end

local function findProjectorWindows()
  local app = hs.application.get(obsAppName)
  if not app then
    return {}
  end

  local matches = {}
  for _, win in ipairs(app:allWindows()) do
    local title = (win:title() or ""):lower()
    if title:find("projector") then
      table.insert(matches, win)
    end
  end

  return matches
end

local function findProjectorWindow()
  local wins = findProjectorWindows()
  return wins[1]
end

local function enforceSingleProjector()
  local wins = findProjectorWindows()
  if #wins <= 1 then
    return wins[1]
  end

  -- Keep the first projector window and close any extras.
  for i = 2, #wins do
    pcall(function() wins[i]:close() end)
  end
  hs.timer.usleep(250000)
  local refreshed = findProjectorWindows()
  return refreshed[1]
end

local function tryOpenProjectorWindow(app)
  -- Primary path: OBS WebSocket API (deterministic, not UI/menu fragile).
  for _ = 1, 12 do
    local out = hs.execute(obsProjectorApiCmd)
    if out and out:find("ok") then
      hs.timer.usleep(500000)
      local projector = findProjectorWindow()
      if projector then
        return projector
      end
    end
    hs.timer.usleep(250000)
  end

  -- Legacy fallback: menu probing for older/odd OBS states.
  local menuCandidates = {
    {"View", "Docks", "Windowed Projector (Preview)"},
    {"View", "Windowed Projector (Preview)"},
    {"View", "Projectors", "Windowed Projector (Preview)"},
    {"View", "Docks", "Windowed Projector (Scene)"},
    {"View", "Windowed Projector (Scene)"},
    {"View", "Projectors", "Windowed Projector (Scene)"},
    {"View", "Docks", "Windowed Projector (Source)"},
    {"View", "Windowed Projector (Source)"},
    {"View", "Projectors", "Windowed Projector (Source)"},
  }

  for _, path in ipairs(menuCandidates) do
    local ok = app:selectMenuItem(path)
    if ok then
      hs.timer.usleep(450000)
      local projector = findProjectorWindow()
      if projector then
        return projector
      end
    end
  end

  return nil
end

local function snapProjector(win)
  local screenFrame = hs.screen.mainScreen():frame()
  local width = math.floor(screenFrame.w * 0.24)
  local height = math.floor(width * 9 / 16)
  local x = screenFrame.x + screenFrame.w - width - 16
  local y = screenFrame.y + 16

  win:setFrame({ x = x, y = y, w = width, h = height }, 0)
  win:raise()
  win:focus()
end

local function toggleOBSFloatingWindow()
  pulse("OBS float hotkey")
  local app = ensureOBS()
  if not app then
    print("[OBS Float] Could not launch OBS")
    pulse("OBS launch failed")
    notify("OBS Float", "Could not launch OBS.")
    return
  end

  local projector = enforceSingleProjector()
  if not projector then
    print("[OBS Float] No existing projector found. Trying menu open...")
    projector = tryOpenProjectorWindow(app)
    if not projector then
      print("[OBS Float] Menu open failed. Manual step required.")
      pulse("Need one-time projector")
      notify("OBS Float", "Open one projector once: right-click Preview -> Windowed Projector (Preview).")
      return
    end
    projector = enforceSingleProjector() or projector
  end

  if projector:isMinimized() then
    projector:unminimize()
    snapProjector(projector)
    print("[OBS Float] Projector restored")
    pulse("OBS projector shown")
    notify("OBS Float", "Projector restored")
  else
    projector:minimize()
    print("[OBS Float] Projector minimized")
    pulse("OBS projector hidden")
    notify("OBS Float", "Projector minimized")
  end
end

-- Window-under-cursor test: hotkey then click a window to see its identity (e.g. for OBS capture binding).
local identifyClickTap = nil

local function windowAtPoint(x, y)
  local pt = hs.geometry.new({ x = x, y = y })
  for _, w in ipairs(hs.window.orderedWindows()) do
    if w:isVisible() then
      local f = w:frame()
      if f and pt:inside(f) then
        return w
      end
    end
  end
  return nil
end

local function describeWindow(win)
  if not win then return "No window at this point."
  end
  local app = win:application()
  local appName = app and app:name() or "?"
  local title = win:title() or "(no title)"
  local wid = win:id()
  local role = win:role() or "?"
  local subrole = win:subrole() or "?"
  local f = win:frame()
  local frameStr = f and string.format("%d,%d %dx%d", f.x, f.y, f.w, f.h) or "?"
  return string.format(
    "App: %s\nTitle: %s\nWindow ID: %s\nRole: %s\nSubrole: %s\nFrame: %s",
    appName, title, tostring(wid), role, subrole, frameStr
  )
end

local function startIdentifyWindowMode()
  if identifyClickTap then
    identifyClickTap:stop()
    identifyClickTap = nil
  end
  pulse("Click a window to identify it…")
  identifyClickTap = hs.eventtap.new({ hs.eventtap.event.types.leftMouseDown }, function(e)
    local loc = e:location()
    local win = windowAtPoint(loc.x, loc.y)
    local msg = describeWindow(win)
    identifyClickTap:stop()
    identifyClickTap = nil
    hs.alert.show(msg, 6)
    notify("Window under cursor", (win and win:title() or "No window") .. " — ID: " .. tostring(win and win:id() or "n/a"))
    return false
  end)
  identifyClickTap:start()
end

hs.hotkey.bind(mods, "w", startIdentifyWindowMode)

hs.hotkey.bind(mods, pipKey, toggleChromePiP)
hs.hotkey.bind(obsMods, obsKey, toggleOBSFloatingWindow)
hs.hotkey.bind(obsFallbackMods, obsKey, toggleOBSFloatingWindow)
notify("Hammerspoon", "Loaded: alt+cmd+o OBS toggle, ctrl+alt+cmd+o OBS fallback, ctrl+alt+cmd+p Chrome PiP, ctrl+alt+cmd+w identify window")

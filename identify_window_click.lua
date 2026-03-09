-- One-shot: block until user clicks a window or 15s timeout. Print window info.
-- Run: hs -c "dofile('/Users/lou/.hammerspoon/identify_window_click.lua')"

local done = false
local result = nil

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

local tap = hs.eventtap.new({ hs.eventtap.event.types.leftMouseDown }, function(e)
  local loc = e:location()
  local win = windowAtPoint(loc.x, loc.y)
  tap:stop()
  if win then
    local app = win:application()
    result = string.format(
      "id=%s  title=%s  app=%s  role=%s  subrole=%s",
      tostring(win:id()),
      win:title() or "",
      app and app:name() or "?",
      win:role() or "?",
      win:subrole() or "?"
    )
  else
    result = "no_window_at_click"
  end
  done = true
  return false
end)

tap:start()
hs.timer.doAfter(15, function()
  if not done then
    tap:stop()
    result = "timeout_15s"
    done = true
  end
end)

while not done do
  hs.timer.usleep(200000)
end

print(result)

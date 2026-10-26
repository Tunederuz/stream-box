-- Text formatting shared by the drawings
local I18N = require "streambox.i18n"

local M = {}

function M.clock(t)   -- 75 → "1:15", 3725 → "1:02:05"
    t = math.max(0, math.floor(t or 0))
    local h, m, sec = math.floor(t / 3600), math.floor(t / 60) % 60, t % 60
    return h > 0 and ("%d:%02d:%02d"):format(h, m, sec) or ("%d:%02d"):format(m, sec)
end

function M.shorten(s, n)   -- cuts at n bytes without breaking a UTF-8 character
    if #s <= n then return s end
    local cut = n
    while cut > 0 and (s:byte(cut + 1) or 0) >= 0x80 and (s:byte(cut + 1) or 0) < 0xC0 do cut = cut - 1 end
    return s:sub(1, cut) .. "…"
end

function M.amount(v)   -- 16617298 → "16,6 M"
    v = tonumber(v) or 0
    local s = v >= 1e6 and ("%.1f M"):format(v / 1e6) or v >= 1e3 and ("%.1f k"):format(v / 1e3) or tostring(v)
    return I18N.dec(s)
end

return M

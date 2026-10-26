-- ASS drawing helpers for the OSD overlays (mpv alone: menu, bar, home screen, polls)
local M = {}

function M.ass_escape(s)
    -- Same escaping as mpv's built-in scripts
    return (s:gsub("\\", "\\\239\187\191"):gsub("{", "\\{"))
end

function M.rect(x, y, w, h, color, alpha)
    w, h = math.floor(w), math.floor(h)
    return ("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\1a&H%s&\\p1}m 0 0 l %d 0 %d %d 0 %d{\\p0}")
        :format(math.floor(x), math.floor(y), color, alpha, w, w, h, h)
end

function M.text(x, y, size, color, s, suffix)   -- suffix: raw ASS added after the escaped text
    return ("{\\an5\\pos(%d,%d)\\fs%d\\bord1.5\\shad0\\3c&H000000&\\1c&H%s&}%s%s")
        :format(math.floor(x), math.floor(y), math.floor(size), color, M.ass_escape(s), suffix or "")
end

-- Disc of radius r centered at (cx, cy): four quarter circles as Bézier curves (k ≈ 0.5523 r)
function M.disc(cx, cy, r, color)
    local k, d = r * 0.5523, 2 * r
    return ("{\\an5\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\1a&H00&\\p1}"
        .. "m %d 0 b %d 0 %d %d %d %d b %d %d %d %d %d %d b %d %d %d %d 0 %d b 0 %d %d 0 %d 0{\\p0}")
        :format(math.floor(cx), math.floor(cy), color,
                r, r + k, d, r - k, d, r,  d, r + k, r + k, d, r, d,  r - k, d, 0, r + k, r,  r - k, r - k, r)
end

-- Companion app QR code, for guests: light square (gray, easier on the screen than white) and
-- dark modules in a single path, one strip per run of modules. Returns the drawing and its side, or nil.
function M.qr_code(x, y, size, rows)
    rows = rows or {}
    local n = #rows
    local m = n > 0 and math.floor(size / (n + 4)) or 0   -- margin of 2 modules all around
    if m < 2 then return nil end
    local paths = {}
    for r, row in ipairs(rows) do
        local c = 1
        while c <= n do
            if row:sub(c, c) == "1" then
                local s = c
                while c <= n and row:sub(c, c) == "1" do c = c + 1 end
                local x0, x1, y0, y1 = (s + 1) * m, (c + 1) * m, (r + 1) * m, (r + 2) * m
                paths[#paths + 1] = ("m %d %d l %d %d %d %d %d %d"):format(x0, y0, x1, y0, x1, y1, x0, y1)
            else
                c = c + 1
            end
        end
    end
    local side = (n + 4) * m
    return M.rect(x, y, side, side, "C8C8C8", "00") .. "\n" ..
        ("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H101010&\\1a&H00&\\p1}%s{\\p0}")
            :format(math.floor(x), math.floor(y), table.concat(paths, " ")), side
end

return M

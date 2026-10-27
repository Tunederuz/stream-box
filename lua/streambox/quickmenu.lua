-- Quick menu of the simplified version (mpv alone): panel on the left, title, list of text that scrolls with the
-- selection, error under it. The lists come from quickmenu.py (user-data/streambox/quickmenu); this only draws them.
local ass = require "streambox.ass"
local M = {}

local PURPLE = "FF4691"   -- Twitch purple (BGR)
local CHAR = 0.46         -- average width of a character, in font sizes

local function starts(s)   -- byte positions where a character starts (UTF-8 continuation bytes are 0x80-0xBF)
    local out = {}
    for i = 1, #s do
        local b = s:byte(i)
        if b < 0x80 or b >= 0xC0 then out[#out + 1] = i end
    end
    return out
end

local function length(s)   -- characters, not bytes
    return #starts(s)
end

local function cut(s, n)   -- at most n characters, "…" when cut
    local at = starts(s)
    if #at <= n then return s end
    return s:sub(1, at[n] - 1) .. "…"
end

local function line(align, x, y, size, color, s)   -- align: 4 left, 6 right (vertically centered on y)
    return ("{\\an%d\\pos(%d,%d)\\fs%d\\bord1.5\\shad0\\3c&H000000&\\1c&H%s&}%s")
        :format(align, math.floor(x), math.floor(y), math.floor(size), color, ass.ass_escape(s))
end

-- data: { title, items = { { label, info, on, dim } }, sel (from 0), note }; hint: help line at the bottom
function M.draw(w, h, data, hint)
    local items = data.items or {}
    local fs = h / 27
    local pw, pad, row_h = math.floor(w * 0.42), fs, math.floor(fs * 1.6)
    local top, bottom = fs * 3.2, h - fs * 2.6 - (data.note ~= "" and data.note and fs * 1.4 or 0)
    local rows = math.max(1, math.floor((bottom - top) / row_h))
    local sel = (data.sel or 0) + 1
    local first = math.max(1, math.min(sel - math.floor(rows / 2), #items - rows + 1))
    local room = pw - 2 * pad

    local out = { ass.rect(0, 0, pw, h, "101010", "30"),
                  line(4, pad, fs * 1.7, fs * 1.15, "FFFFFF", cut(data.title or "", math.floor(room / (fs * 1.15 * CHAR)))) }
    for i = first, math.min(#items, first + rows - 1) do
        local it, y = items[i], top + (i - first) * row_h
        local info = cut(it.info or "", 28)
        local info_w = info ~= "" and (length(info) * CHAR * 0.8 + 1.5) * fs or 0
        if i == sel then out[#out + 1] = ass.rect(pad * 0.5, y, pw - pad, row_h - fs * 0.15, PURPLE, "00") end
        local color = i == sel and "FFFFFF" or (it.dim and "909090" or "E8E8E8")
        local label = (it.on and "▶ " or "") .. (it.label or "")
        out[#out + 1] = line(4, pad, y + row_h / 2, fs, color, cut(label, math.max(8, math.floor((room - info_w) / (fs * CHAR)))))
        if info ~= "" then
            out[#out + 1] = line(6, pw - pad, y + row_h / 2, fs * 0.8, i == sel and "FFFFFF" or "A0A0A0", info)
        end
    end
    if first > 1 then out[#out + 1] = line(6, pw - pad, top - fs * 0.5, fs * 0.7, "A0A0A0", "▲") end
    if first + rows - 1 < #items then out[#out + 1] = line(6, pw - pad, bottom + fs * 0.3, fs * 0.7, "A0A0A0", "▼") end
    if data.note and data.note ~= "" then
        out[#out + 1] = line(4, pad, bottom + fs * 0.9, fs * 0.75, "8080FF", cut(data.note, math.floor(room / (fs * 0.75 * CHAR))))
    end
    out[#out + 1] = line(4, pad, h - fs * 1.3, fs * 0.7, "A0A0A0", hint or "")
    return table.concat(out, "\n")
end

return M

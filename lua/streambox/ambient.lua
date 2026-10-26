-- Home screen drawn with mpv alone (the Qt app has qml/AmbientScreen.qml): clock, date, weather, upcoming streams,
-- status message, setup mode and companion app QR code over an "aurora" background. The content moves a little
-- every minute, so as not to burn in the TV screen.
local ass = require "streambox.ass"
local I18N = require "streambox.i18n"
local ass_escape, text, tr = ass.ass_escape, ass.text, I18N.tr

local M = {}

local WEEKDAYS = { "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday" }   -- os.date: 1 = Sunday
local MONTHS = { "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                 "November", "December" }

-- "Aurora" background: three large, very blurry blobs drifting slowly over an almost black background.
-- { BGR color, ASS opacity (00 = opaque), speed, phase }
local AURORA = { { "FF4691", "B0", 0.011, 0.0 },    -- Twitch purple
                 { "6A2A12", "A0", 0.008, 2.1 },    -- midnight blue
                 { "7A2A5E", "B8", 0.006, 4.2 } }   -- plum

local function aurora(w, h)
    local t, r = os.time(), math.floor(h * 0.42)
    local out = { ("{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H0D0808&\\p1}m 0 0 l %d 0 %d %d 0 %d{\\p0}"):format(w, w, h, h) }
    for _, a in ipairs(AURORA) do
        local x = w / 2 + math.sin(t * a[3] + a[4]) * w * 0.32
        local y = h / 2 + math.cos(t * a[3] * 1.3 + a[4]) * h * 0.25
        local k, d = r * 0.5523, 2 * r
        out[#out + 1] = ("{\\an5\\pos(%d,%d)\\bord0\\shad0\\blur%d\\1c&H%s&\\1a&H%s&\\p1}"
            .. "m %d 0 b %d 0 %d %d %d %d b %d %d %d %d %d %d b %d %d %d %d 0 %d b 0 %d %d 0 %d 0{\\p0}")
            :format(x, y, math.floor(h * 0.12), a[1], a[2],
                    r, r + k, d, r - k, d, r, d, r + k, r + k, d, r, d, r - k, d, 0, r + k, r, r - k, r - k, r)
    end
    return table.concat(out, "\n")
end

-- data: user-data/streambox/ambient (weather, schedule, setup); status: status message; qr(x, y, size) → drawing,
-- side (nil when hidden); qr_host: address shown under it
function M.draw(w, h, data, status, qr, qr_host)
    local t = os.date("*t")
    local minute = math.floor(os.time() / 60)
    local cx = w / 2 + math.sin(minute * 0.7) * w * 0.04
    local cy = h * 0.40 + math.cos(minute * 0.5) * h * 0.04
    local fs = math.floor(h / 26)
    local function line(y, size, color, raw)
        return ("{\\an8\\pos(%d,%d)\\fs%d\\bord0\\shad0\\1c&H%s&}%s"):format(cx, y, size, color, raw)
    end
    local out = {
        aurora(w, h),
        line(cy - h * 0.30, math.floor(h * 0.22), "FFFFFF", ("%02d:%02d"):format(t.hour, t.min)),
        line(cy - h * 0.06, math.floor(fs * 1.2), "B0B0B0",
             ass_escape(tr("{weekday}, {month} {day}",
                           { weekday = tr(WEEKDAYS[t.wday]), day = t.day, month = tr(MONTHS[t.month]) }))),
    }
    local wx = data.weather
    if wx then
        local parts = { wx.city, ("%d°"):format(wx.temp), wx.text, ("%d° / %d°"):format(wx.min, wx.max) }
        if (tonumber(wx.rain) or 0) >= 30 then parts[#parts + 1] = tr("rain {n}%", { n = ("%d"):format(wx.rain) }) end
        local kept = {}
        for _, part in ipairs(parts) do if part and part ~= "" then kept[#kept + 1] = part end end
        out[#out + 1] = line(cy + h * 0.01, fs, "D0D0D0", ass_escape(table.concat(kept, "  ·  ")))
    end
    local schedule = data.schedule or {}
    if #schedule > 0 then
        local y = cy + h * 0.10
        out[#out + 1] = line(y, math.floor(fs * 0.75), "808080", ass_escape(tr("UPCOMING STREAMS")))
        for _, item in ipairs(schedule) do
            y = y + fs * 1.35
            local title = item.title or ""
            if #title > 40 then title = title:sub(1, 37) .. "…" end
            out[#out + 1] = line(y, math.floor(fs * 0.85), "FFFFFF",
                "{\\b1}" .. ass_escape(item.login) .. "{\\b0\\1c&HB0B0B0&}  ·  " .. ass_escape(item.when)
                .. (title ~= "" and ("  ·  " .. ass_escape(title)) or ""))
        end
    end
    if status ~= "" then
        out[#out + 1] = line(h * 0.93, math.floor(fs * 0.7), "707070", ass_escape(status))
    end
    -- Setup mode (mpv alone; the Qt app has its own screen): QR code of the box's Wi-Fi at the bottom right
    local setup = data.setup
    if setup and setup.ssid then
        out[#out + 1] = line(h * 0.72, math.floor(fs * 0.9), "FFFFFF", "{\\b1}" .. ass_escape(tr("Setup")))
        out[#out + 1] = line(h * 0.77, math.floor(fs * 0.75), "D0D0D0",
            ass_escape(tr("1. Wi-Fi \"{ssid}\", password {password}", { ssid = setup.ssid, password = setup.password })))
        out[#out + 1] = line(h * 0.81, math.floor(fs * 0.75), "D0D0D0",
            ass_escape(tr("2. Open {url} and choose your home Wi-Fi",
                          { url = (setup.url or ""):gsub("^http://", ""):gsub("/$", "") })))
    elseif setup and setup.connecting then
        out[#out + 1] = line(h * 0.77, math.floor(fs * 0.8), "FFFFFF",
            ass_escape(tr("Connecting to Wi-Fi \"{ssid}\"…", { ssid = setup.connecting })))
    end
    -- Companion app QR code at the bottom right, which drifts a little too
    local size = math.floor(h * 0.17)
    local qx = w - size - w * 0.04 + math.sin(minute * 0.9) * w * 0.012
    local qy = h - size - h * 0.11 + math.cos(minute * 0.6) * h * 0.015
    local drawing, side = qr(qx, qy, size)
    if drawing then
        out[#out + 1] = drawing
        out[#out + 1] = text(qx + side / 2, qy - fs * 0.7, fs * 0.8, "A0A0A0", tr("Companion app"))
        out[#out + 1] = text(qx + side / 2, qy + side + fs * 0.7, fs * 0.65, "909090", qr_host)
    end
    return table.concat(out, "\n")
end

return M

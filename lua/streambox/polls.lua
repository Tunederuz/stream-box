-- Polls and predictions of the watched channel, drawn with mpv alone (the Qt app has qml/PollsOverlay.qml): box
-- at the top center, away from the corners where the chat goes, with the time left and the share of each choice
local ass = require "streambox.ass"
local fmt = require "streambox.fmt"
local I18N = require "streambox.i18n"
local ass_escape, rect, tr = ass.ass_escape, ass.rect, I18N.tr
local shorten, amount, clock = fmt.shorten, fmt.amount, fmt.clock

local M = {}

local OUTCOME_COLORS = { BLUE = "FF7A38", PINK = "9B00F5" }   -- Twitch prediction colors, in BGR

-- data: user-data/streambox/polls ({ poll, prediction }); returns the ASS drawing
function M.draw(w, h, data)
    local poll, pred = data.poll, data.prediction
    local fs = math.floor(h / 40)
    local bw = math.floor(w * 0.3)
    local x, y = math.floor((w - bw) / 2), math.floor(h * 0.03)
    local pad, row_h = fs * 0.7, fs * 1.5
    local out = {}
    -- rows: { label, share from 0 to 1, detail on the right, BGR color, winner }
    local function block(kind, title, right, rows)
        local bh = pad * 2 + fs * 2.5 + #rows * row_h
        out[#out + 1] = rect(x, y, bw, bh, "000000", "40")
        out[#out + 1] = ("{\\an7\\pos(%d,%d)\\fs%d\\bord0\\shad0\\1c&HFF4691&\\b1}%s")
            :format(x + pad, y + pad, math.floor(fs * 0.7), kind)
        out[#out + 1] = ("{\\an9\\pos(%d,%d)\\fs%d\\bord0\\shad0\\1c&HC0C0C0&}%s")
            :format(x + bw - pad, y + pad, math.floor(fs * 0.7), ass_escape(right))
        out[#out + 1] = ("{\\an7\\pos(%d,%d)\\fs%d\\bord0\\shad0\\1c&HFFFFFF&\\b1}%s")
            :format(x + pad, y + pad + fs * 0.95, fs, ass_escape(shorten(title, 70)))
        local ry = y + pad + fs * 2.5
        for _, r in ipairs(rows) do
            local inner = bw - pad * 2
            out[#out + 1] = rect(x + pad, ry, inner, row_h - fs * 0.25, "FFFFFF", "E0")
            if r[2] > 0 then
                out[#out + 1] = rect(x + pad, ry, inner * math.min(1, r[2]), row_h - fs * 0.25, r[4], r[5] and "20" or "70")
            end
            local label = (r[5] and "▶ " or "") .. shorten(r[1], 40)
            out[#out + 1] = ("{\\an4\\pos(%d,%d)\\fs%d\\bord1\\shad0\\3c&H000000&\\1c&HFFFFFF&}%s")
                :format(x + pad * 1.6, ry + (row_h - fs * 0.25) / 2, math.floor(fs * 0.8), ass_escape(label))
            out[#out + 1] = ("{\\an6\\pos(%d,%d)\\fs%d\\bord1\\shad0\\3c&H000000&\\1c&HFFFFFF&}%s")
                :format(x + bw - pad * 1.6, ry + (row_h - fs * 0.25) / 2, math.floor(fs * 0.7), ass_escape(r[3]))
            ry = ry + row_h
        end
        y = y + bh + fs * 0.5
    end
    local now = os.time()
    if poll then
        local total, best = 0, 0
        for _, c in ipairs(poll.choices or {}) do
            total = total + c.votes
            best = math.max(best, c.votes)
        end
        local rows = {}
        for i, c in ipairs(poll.choices or {}) do
            if i > 5 then break end
            local share = total > 0 and c.votes / total or 0
            rows[#rows + 1] = { c.title, share, tr("{pct}%  ·  {votes}", { pct = math.floor(share * 100 + 0.5),
                                votes = amount(c.votes) }), "FF4691", poll.ended and best > 0 and c.votes == best }
        end
        local left = (poll.ends_at or 0) - now
        block(ass_escape(tr("POLL")), poll.title,
              poll.ended and tr("Results") or left > 0 and clock(left) or tr("Counting…"), rows)
    end
    if pred then
        local total = 0
        for _, o in ipairs(pred.outcomes or {}) do total = total + o.points end
        local rows = {}
        for i, o in ipairs(pred.outcomes or {}) do
            if i > 5 then break end
            local share = total > 0 and o.points / total or 0
            rows[#rows + 1] = { o.title, share, tr("{pct}%  ·  {points} points  ·  {users}", {
                                    pct = math.floor(share * 100 + 0.5), points = amount(o.points), users = amount(o.users) }),
                                OUTCOME_COLORS[o.color] or "FF4691", o.winner }
        end
        local left = (pred.ends_at or 0) - now
        local right = pred.status == "RESOLVED" and tr("Result") or pred.status == "CANCELED" and tr("Canceled")
            or pred.status == "ACTIVE" and left > 0 and tr("Bets: {time}", { time = clock(left) }) or tr("Bets closed")
        block(ass_escape(tr("PREDICTION")), pred.title, right, rows)
    end
    return table.concat(out, "\n")
end

return M

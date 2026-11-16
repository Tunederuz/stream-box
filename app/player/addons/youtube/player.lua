-- Inlet, YouTube add-on: its part of the player (loaded by lua/stream-box.lua, see "Add-ons' player parts" there).
-- The videos it acts on are those started for this add-on (api.mine()): automatic subtitles made readable, the yt-dlp
-- client changed when YouTube refuses the stream, and its own message when YouTube asks to prove you are not a robot.
local mp = require "mp"
local I18N = require "streambox.i18n"

return function(api)
    local M = {}

    -- Automatic subtitles (kind=asr): their lines overlap, two always stay on screen. Reloaded through remote.py,
    -- which cuts each line at the start of the next one. As EDL "delay_open", like ytdl_hook: a track is only
    -- downloaded if it is chosen (YouTube quickly answers "429" to bursts).
    mp.register_event("file-loaded", function()
        if not api.mine() then return end
        for _, t in ipairs(mp.get_property_native("track-list") or {}) do
            local edl = t.type == "sub" and t["external-filename"] or ""
            local len, rest = edl:match("%%(%d+)%%(.*)$")   -- ytdl_hook adds them as EDL: %length%url
            local url = len and rest:sub(1, tonumber(len)) or ""
            if url:match("^https://www%.youtube%.com/api/timedtext") and url:match("[?&]kind=asr") then
                mp.commandv("sub-remove", tostring(t.id))
                local fixed = "http://127.0.0.1:8080/subs?u=" .. url:gsub("[^%w%-_%.~]", function(c) return ("%%%02X"):format(c:byte()) end)
                mp.commandv("sub-add", ("edl://!no_clip;!delay_open,media_type=sub;%%%d%%%s"):format(#fixed, fixed),
                            t.selected and "select" or "auto", t.title or "", t.lang or "")
            end
        end
    end)

    -- Why a video could not play: YouTube asking to prove it is not a bot (ytdl_hook's error, same for every client;
    -- only an account's cookies get past it), or the stream refused (ffmpeg's "HTTP error 403", a warning)
    local why = nil
    mp.enable_messages("warn")
    mp.register_event("log-message", function(m)
        if m.prefix == "ytdl_hook" and m.text:find("not a bot", 1, true) then why = "bot"
        elseif m.text:find("HTTP error 403", 1, true) then why = why or "403" end
    end)

    -- yt-dlp's client (player_client): which one's streams YouTube serves changes from one day to the next (mweb
    -- refused with HTTP 403 on 2026-10-29 while tv_simply played to the end; the other way round the day before). A
    -- video refused with a 403 is reloaded at the same second with the next client; the one that plays stays for the
    -- following videos.
    local clients = { "mweb,tv_simply", "tv_simply", "mweb", "web_safari" }
    local ci, tries, path, pos = 1, 0, nil, 0
    -- Before ytdl_hook (priority 10): this video's yt-dlp options with the chosen client, the others unchanged
    mp.add_hook("on_load", 9, function()
        local p = mp.get_property("path") or ""
        if p ~= path then path, tries = p, 0 end
        if ci == 1 or not api.mine() then return end
        local raw = mp.get_property_native("ytdl-raw-options") or {}
        raw["extractor-args"] = (raw["extractor-args"] or "youtube:fetch_pot=always")
            :gsub("player_client=[^;]*", "player_client=" .. clients[ci])
        mp.set_property_native("file-local-options/ytdl-raw-options", raw)
    end)
    mp.observe_property("time-pos", "number", function(_, v) if v and v > 0 then pos = v end end)
    -- A new video starts where it is asked to (start=…, resume from the history), a reload where the refused one was
    mp.register_event("start-file", function()
        why = nil
        pos = tonumber((mp.get_property("file-local-options/start") or ""):match("^%+?([%d.]+)$")) or 0
    end)

    -- The video ended with an error (lua/stream-box.lua asks): "retry" when it is reloaded with the next client (at
    -- most once each for this video), or the message to show
    function M.failed()
        if not api.mine(path) then return nil end
        if why == "403" and tries < #clients - 1 then
            tries = tries + 1
            ci = ci % #clients + 1
            mp.msg.info(("YouTube refused the stream (403): retrying with player_client=%s"):format(clients[ci]))
            mp.commandv("loadfile", path, "replace", "-1", ("start=%d"):format(math.floor(pos or 0)))
            return "retry"
        end
        if why == "bot" then
            return I18N.tr("YouTube is refusing this video for now (it asks to prove you are not a robot): try again later"), 8
        end
    end

    return M
end

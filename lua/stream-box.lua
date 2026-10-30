-- Inlet: small menu of the simplified version (streamer choice, chat corner, opened by the remote),
-- and management of streamlink, which serves the chosen channel's stream over local HTTP to this mpv.
-- The channel, corner and chat visibility are published in user-data/streambox/* for chat_overlay.py.
-- Two modes: "twitch" (stream of the chosen channel) and "media" (video sent from the companion app or
-- Jellyfin). Any file that is not the streamlink stream switches to "media"; when it ends and
-- mpv stays empty, we go back to the stream.
local mp = require "mp"

-- This script is in the repository's lua/ (mp.get_script_file is too recent), its modules next to it in
-- lua/streambox/*.lua (require "streambox.…"); DIR: the repository (locales/)
local LUA_DIR = debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$") or "."
local DIR = LUA_DIR .. "/.."
package.path = LUA_DIR .. "/?.lua;" .. package.path
local I18N = require "streambox.i18n"   -- interface language (see i18n.py), reloaded on streambox-language
local ass = require "streambox.ass"
local fmt = require "streambox.fmt"
local keys = require "streambox.keys"
local quick = require "streambox.quickmenu"
local tr, ass_escape, rect, text, clock = I18N.tr, ass.ass_escape, ass.rect, ass.text, fmt.clock
I18N.load(DIR)

-- In the settings (twitch.py moves an older list from the code folder there); the old place until it has
local STREAMERS_FILE = os.getenv("HOME") .. "/.config/stream-box/streamers.txt"
local OLD_STREAMERS_FILE = DIR .. "/streamers.txt"
local STATE_DIR = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")) .. "/stream-box"

local CORNERS = { "tl", "tr", "br", "bl" }   -- toggle order (clockwise)
local CORNER_LABELS = { tl = "↖ top left", tr = "↗ top right", br = "↘ bottom right", bl = "↙ bottom left" }
local MENU_TIMEOUT = 120  -- seconds without a key before closing the quick menu
local RETRY = 15          -- seconds between two attempts when the channel is not live
local BACK_TO_MENU = 3    -- seconds idle after a video before going back to the menu (lets Jellyfin chain the next one)
local AUTO_SWITCH = 60    -- seconds offline (after a channel change) before switching to a live streamer
local FROZEN = 20         -- seconds of frozen picture, not paused, before restarting the live stream
local LIVE_BACK = "400MiB" -- live stream kept in memory to go back in time (≈ 7-8 min in 1080p60)
local LIVE_EDGE = 4       -- delay in seconds below which we count as "live"
local BASE_PORT = 34500

local streamers, channel, corner, chat_visible
local server, port_n = nil, os.time() % 50
local attempts, retry_timer = 0, nil
local mode, back_timer = "twitch", nil
local live, offline, channel_since = {}, false, 0   -- live: report from remote.py (user-data/streambox/live)
local ambient_visible, status_text = false, ""    -- ambient screen shown; last status message
local auto_switch_on = true   -- automatic switch to a live streamer (companion app setting)
local qr_data = nil           -- companion app QR code, published by remote.py with the ambient screen
local ambient_data = {}       -- user-data/streambox/ambient (weather, schedules, QR code, setup mode)
local QR_MODES = { always = true, timed = true, never = true }   -- always, QR_SECONDS seconds, never
local QR_SECONDS = 30
local qr_mode, qr_until = "always", 0   -- in "timed" mode, shown until qr_until (mp.get_time)
local status = mp.create_osd_overlay("ass-events")


-- Qt app (ui.py): banner, playback bar, notifications, polls box and home screen are drawn in
-- QML; this script keeps the logic (when, how long, keys) and publishes the state in user-data/streambox/*
local function qt_ui()
    return mp.get_property_native("user-data/streambox/chat_ui") == "qml"
end
-- Big TV menu: the QML one of the Qt app (vo libmpv), unless it failed to load (ui.py then writes "small").
-- With mpv alone, the Menu button opens the small menu below (streamers, home screen, chat, back to the Qt app)
local function big_menu()
    return mp.get_property("vo", ""):find("libmpv", 1, true) ~= nil
        and mp.get_property_native("user-data/streambox/menu") ~= "small"
end

local function read_streamers()
    local list = {}
    local f = io.open(STREAMERS_FILE) or io.open(OLD_STREAMERS_FILE)
    if f then
        for line in f:lines() do
            local name = line:gsub("#.*", ""):match("^%s*(.-)%s*$"):lower()
            name = name:gsub("^https?://", ""):gsub("^www%.", ""):gsub("^twitch%.tv/", "")
            if name ~= "" then list[#list + 1] = name end
        end
        f:close()
    end
    return list
end

-- Settings (channel, chat) kept from one start to the next, one file per setting in STATE_DIR
local function read_state(name)
    local f = io.open(STATE_DIR .. "/" .. name)
    local v = f and f:read("*l")
    if f then f:close() end
    return v
end

local function write_state(name, value)
    local f = io.open(STATE_DIR .. "/" .. name, "w")
    if f then
        f:write(value, "\n")
        f:close()
    end
end

local function set_status(text)
    status_text = text
    mp.set_property_native("user-data/streambox/status", text)   -- for the QML home screen (Qt app)
    if text == "" or ambient_visible then   -- the ambient screen shows this message itself, small
        status:remove()
        return
    end
    status.res_x, status.res_y = 1920, 1080
    status.data = "{\\an5\\pos(960,540)\\fs40\\bord2\\shad0\\3c&H000000&\\1c&HC0C0C0&}" .. ass_escape(text)
    status:update()
end

-- Loading screen between two videos or two channels (otherwise the picture stays frozen and looks like a hang):
-- user-data/streambox/loading { title, thumb } until the first frame (playback-restart), an error or 45 s at most;
-- drawn by qml/LoadingOverlay.qml, or the centered status message with mpv alone
local loading_timer, loading_osd = nil, false
local function set_loading(title, thumb, kind)   -- kind: twitch, youtube, jellyfin, plex or video (animation color)
    if loading_timer then loading_timer:kill() loading_timer = nil end
    if title then
        mp.set_property_native("user-data/streambox/loading", { title = title, thumb = thumb or "", kind = kind or "video" })
        -- Qt app (vo=libmpv, known from startup, unlike chat_ui): the QML screen is enough
        -- mpv alone: the centered status message (a single one: the Twitch loading sets the same text)
        loading_osd = mp.get_property("vo") ~= "libmpv" and tr("Loading {title}…", { title = title })
        if loading_osd then set_status(loading_osd) end
        loading_timer = mp.add_timeout(45, function() set_loading(nil) end)
    else
        mp.set_property_native("user-data/streambox/loading", {})
        if loading_osd and status_text == loading_osd then set_status("") end   -- unless replaced since ("not live"…)
        loading_osd = false
    end
end
mp.register_event("playback-restart", function() set_loading(nil) end)
mp.register_event("end-file", function(e) if e.reason == "error" then set_loading(nil) end end)


-- Playback: streamlink runs as a local HTTP server, mpv plays http://127.0.0.1:<port>/

local function stream_url()
    return ("http://127.0.0.1:%d/"):format(BASE_PORT + port_n)
end

local function load_stream()
    retry_timer = nil
    attempts = attempts + 1
    -- Pause survives a file change in mpv: a video left paused would freeze the live stream
    mp.set_property_native("pause", false)
    mp.commandv("loadfile", stream_url())
end

local function start_server(name)
    port_n = port_n % 50 + 1   -- new port: the old one can stay busy for a few seconds
    local handle
    handle = mp.command_native_async({
        name = "subprocess", playback_only = false,
        args = { "streamlink", "--twitch-low-latency", "--retry-streams", "30",
                 "--player-external-http", "--player-external-http-interface", "127.0.0.1",
                 "--player-external-http-port", tostring(BASE_PORT + port_n),
                 "twitch.tv/" .. name, "best" },
    }, function(_, res)
        if server == handle and not (res and res.killed_by_us) then
            -- streamlink stopped on its own: restart it
            mp.add_timeout(5, function() if server == handle then start_server(name) end end)
        end
    end)
    server = handle
end

local function set_mode(m)
    mode = m
    mp.set_property_native("user-data/streambox/mode", m)
    if back_timer then
        back_timer:kill()
        back_timer = nil
    end
end

local function stop_twitch()
    if server then mp.abort_async_command(server) end
    server = nil
    if retry_timer then retry_timer:kill() end
    retry_timer = nil
    set_status("")
end

local function start_channel(name)
    if not name then return end
    channel = name
    write_state("channel", name)
    mp.set_property_native("user-data/streambox/channel", name)
    set_mode("twitch")   -- before the "stop" below, so its end of file is read as a channel change
    set_loading(name, nil, "twitch")
    mp.set_property_bool("pause", false)   -- mpv keeps pause from one file to the next
    offline, channel_since = false, mp.get_time()
    stop_twitch()
    start_server(name)
    mp.commandv("stop")
    attempts = 0
    set_status(tr("Loading {title}…", { title = name }))
    retry_timer = mp.add_timeout(2, load_stream)
end

-- start: resume position in seconds (remote.py history), given to mpv as a file option so no jump is
-- seen after loading
-- title: title to display (Jellyfin: the stream link does not give one), passed as a file option (%n%: length
-- in bytes, so commas and equal signs in the title go through as is)
-- thumb, label: loading screen picture and title (label: known title, without forcing it on mpv)
local function play_media(url, start, title, thumb, label)
    -- Started from elsewhere (phone, Cast, Home Assistant…) while the menu is open: it closes over the video
    mp.commandv("script-message", "streambox-tvmenu-close")
    stop_twitch()
    set_mode("media")
    local kind = (url:find("youtube%.com/") or url:find("youtu%.be/")) and "youtube"
        or url:find("/Videos/%x+/stream") and "jellyfin" or url:find("/library/parts/%d+/") and "plex"
        or url:find("twitch%.tv/") and "twitch" or "video"
    set_loading((label and label ~= "" and label) or (title and title ~= "" and title) or tr("the video"), thumb, kind)
    mp.set_property_bool("pause", false)   -- mpv keeps pause from one file to the next
    local at = tonumber(start) or 0
    local opts = title and title ~= "" and ("force-media-title=%%%d%%%s"):format(#title, title) or nil
    if at > 0 or opts then
        local all = {}
        if at > 0 then all[#all + 1] = ("start=%d"):format(at) end
        if opts then all[#all + 1] = opts end
        mp.commandv("loadfile", url, "replace", "-1", table.concat(all, ","))
        local h, m, sec = math.floor(at / 3600), math.floor(at / 60) % 60, at % 60
        if at > 0 then
            mp.osd_message(tr("Resuming at {time}", { time = h > 0 and ("%d:%02d:%02d"):format(h, m, sec)
                or ("%d:%02d"):format(m, sec) }), 4)
        end
    else
        mp.commandv("loadfile", url)
    end
end

-- Right before each file opens, including those loaded by Jellyfin: small buffer for the live stream
-- (latency), normal buffer for videos. And decoding on the iGPU, which the Jellyfin shim may have disabled.
mp.add_hook("on_load", 50, function()
    local is_live = mp.get_property("stream-open-filename") == stream_url()
    mp.set_property("demuxer-max-bytes", is_live and "750KiB" or "150MiB")
    -- Live: keep the last minutes and allow seeking in them (the stream itself is not "seekable")
    mp.set_property("demuxer-max-back-bytes", is_live and LIVE_BACK or "50MiB")
    mp.set_property("demuxer-seekable-cache", is_live and "yes" or "auto")
    mp.set_property("hwdec", "auto-safe")
end)

-- Home screen on demand: no more stream nor automatic switch, until a streamer or a video is chosen
local function show_home()
    stop_twitch()
    set_mode("home")
    mp.commandv("stop")
end

-- The big menu is the main page: at startup, at the end of a video and on Back, nothing playing anymore and the
-- menu over the home screen (animated background)
-- First setup not done yet from the phone (remote.py: setup-done, or a box that has already been used):
-- the TV stays on the home screen, big QR code, and the menu does not open
local function setup_pending()
    local home = os.getenv("HOME") or ""
    for _, path in ipairs({ home .. "/.config/stream-box/setup-done", STATE_DIR .. "/history.json" }) do
        local f = io.open(path)
        if f then f:close() return false end
    end
    return true
end

local open_tvmenu   -- (further down)
local function home_menu()
    if mode ~= "home" then show_home() end
    if not setup_pending() then open_tvmenu() end
end

mp.register_event("start-file", function()
    if mp.get_property("path") == stream_url() then return end
    if mode == "twitch" or mode == "home" then
        -- File loaded by someone else (Jellyfin): make way for it, menu closed
        mp.commandv("script-message", "streambox-tvmenu-close")
        stop_twitch()
        set_mode("media")
    elseif back_timer then
        back_timer:kill()   -- next video: stay in media mode
        back_timer = nil
    end
end)

-- YouTube automatic subtitles (kind=asr): their lines overlap, two always stay on screen.
-- We reload them through remote.py, which cuts each line at the start of the next one. As EDL "delay_open", like
-- ytdl_hook: a track is only downloaded if it is chosen (YouTube quickly answers "429" to bursts).
local function fix_auto_subs()
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
end

-- Subtitles remembered per video: the choice made in the Subtitles / audio panel (language, or "no" for off)
-- is kept for this video (~/.local/state/stream-box/sub_prefs.json, key: YouTube or Jellyfin id, otherwise
-- the link; 300 videos at most) and restored when it is resumed. A video without a choice keeps mpv's
-- choice
local SUB_PREFS = STATE_DIR .. "/sub_prefs.json"
local json = require "mp.utils"
local function video_key()
    local path = mp.get_property("path") or ""
    return path:match("[?&]v=([%w_-]+)") or path:match("youtu%.be/([%w_-]+)") or path:match("/[Vv]ideos/(%x+)/")
        or (path ~= "" and path or nil)
end
local function read_sub_prefs()
    local f = io.open(SUB_PREFS)
    if not f then return {} end
    local data = json.parse_json(f:read("*a") or "") or {}
    f:close()
    return type(data) == "table" and data or {}
end
local function save_sub_pref(lang)
    local key = video_key()
    if not key then return end
    local prefs = read_sub_prefs()
    prefs[key] = { lang = lang, t = os.time() }
    local keys = {}
    for k in pairs(prefs) do keys[#keys + 1] = k end
    if #keys > 300 then   -- the oldest ones go
        table.sort(keys, function(a, b) return (prefs[a].t or 0) < (prefs[b].t or 0) end)
        for n = 1, #keys - 300 do prefs[keys[n]] = nil end
    end
    local f = io.open(SUB_PREFS, "w")
    if f then f:write(json.format_json(prefs)) f:close() end
end
local function apply_sub_pref()
    local key = video_key()
    local pref = key and (read_sub_prefs()[key] or {}).lang
    if not pref or pref == "" then return end
    local current = mp.get_property("sid")
    local function same_lang(a, b)
        a, b = (a or ""):lower(), (b or ""):lower()
        return a ~= "" and b ~= "" and (a == b or a:sub(1, 2) == b:sub(1, 2))
    end
    if pref == "no" then
        if current ~= "no" then mp.set_property("sid", "no") end
        return
    end
    local best
    for _, t in ipairs(mp.get_property_native("track-list") or {}) do
        if t.type == "sub" and same_lang(t.lang, pref) and (not best or (best.forced and not t.forced)) then best = t end
    end
    if best and current ~= tostring(best.id) then mp.set_property("sid", tostring(best.id)) end
end
-- Tracks added after opening (Jellyfin external subtitles: remote.py jf_add_subtitles, up to 15 s
-- later; YouTube auto subtitles): the remembered choice is reapplied during the first seconds of the video
local sub_pref_until = 0
mp.observe_property("track-list", "native", function()
    if mode == "media" and mp.get_time() < sub_pref_until then apply_sub_pref() end
end)

mp.register_event("file-loaded", function()
    attempts = 0
    offline = false
    set_status("")
    if mode == "media" then
        fix_auto_subs()
        sub_pref_until = mp.get_time() + 20
        apply_sub_pref()
    end
end)

-- Channel offline for more than AUTO_SWITCH seconds: switch to the first live streamer, in the order of
-- streamers.txt. The delay leaves time to deliberately pick an offline channel (time to check).
local function auto_switch()
    if not auto_switch_on or mode ~= "twitch" or not offline or mp.get_time() - channel_since < AUTO_SWITCH then return end
    for _, name in ipairs(read_streamers()) do
        if name ~= channel and live[name] then
            mp.osd_message(tr("{channel} is not live: switching to {name}", { channel = channel, name = name }), 6)
            start_channel(name)
            return
        end
    end
end

-- Why a video could not play: YouTube asking to prove it is not a bot (ytdl_hook's error, same for every client;
-- only an account's cookies get past it) gets its own message
local ytdl_error = nil
mp.enable_messages("warn")   -- (ffmpeg's "HTTP error 403" is a warning)
mp.register_event("log-message", function(m)
    if m.prefix == "ytdl_hook" and m.text:find("not a bot", 1, true) then ytdl_error = "bot"
    elseif m.text:find("HTTP error 403", 1, true) then ytdl_error = ytdl_error or "403" end
end)
mp.register_event("start-file", function() ytdl_error = nil end)

-- YouTube client (player_client of yt-dlp): which one's streams YouTube serves changes from one day to the next (mweb
-- refused with HTTP 403 on 2026-10-29 while tv_simply played to the end; the other way round the day before). A
-- video refused with a 403 is reloaded at the same second with the next client; the one that plays stays for the
-- following videos. One table (the script's 200 locals limit): clients, current one, tries for this video
local ytc = { list = { "mweb,tv_simply", "tv_simply", "mweb", "web_safari" }, i = 1, tries = 0, path = nil, pos = 0 }
-- Before ytdl_hook (priority 10): this video's yt-dlp options with the chosen client, the others unchanged
mp.add_hook("on_load", 9, function()
    local path = mp.get_property("path") or ""
    if path ~= ytc.path then ytc.path, ytc.tries = path, 0 end
    if ytc.i == 1 or not path:find("youtu", 1, true) then return end
    local raw = mp.get_property_native("ytdl-raw-options") or {}
    raw["extractor-args"] = (raw["extractor-args"] or "youtube:fetch_pot=always")
        :gsub("player_client=[^;]*", "player_client=" .. ytc.list[ytc.i])
    mp.set_property_native("file-local-options/ytdl-raw-options", raw)
end)
mp.observe_property("time-pos", "number", function(_, v) if v and v > 0 then ytc.pos = v end end)
-- A new video starts where it is asked to (start=…, resume from the history), a reload where the refused one was
mp.register_event("start-file", function()
    ytc.pos = tonumber((mp.get_property("file-local-options/start") or ""):match("^%+?([%d.]+)$")) or 0
end)
-- Refused (403): the next client, at most once each for this video; true when it is reloaded
function ytc.retry(e)
    local path = ytc.path or ""
    if e.reason ~= "error" or ytdl_error ~= "403" or not path:find("youtu", 1, true) or ytc.tries >= #ytc.list - 1 then
        return false
    end
    ytc.tries = ytc.tries + 1
    ytc.i = ytc.i % #ytc.list + 1
    mp.msg.info(("YouTube refused the stream (403): retrying with player_client=%s"):format(ytc.list[ytc.i]))
    mp.commandv("loadfile", path, "replace", "-1", ("start=%d"):format(math.floor(ytc.pos or 0)))
    return true
end

mp.register_event("end-file", function(e)
    if mode == "home" then return end
    if mode == "media" then
        if ytc.retry(e) then return end   -- YouTube refused the stream: the next client
        if e.reason == "error" then
            mp.osd_message(ytdl_error == "bot" and tr("YouTube is refusing this video for now (it asks to prove you are not a robot): try again later")
                           or tr("Can't play this video"), ytdl_error == "bot" and 8 or 5)
        end
        if back_timer then back_timer:kill() end
        back_timer = mp.add_timeout(BACK_TO_MENU, function()
            back_timer = nil
            if mode == "media" and mp.get_property_native("idle-active") then home_menu() end
        end)
        return
    end
    if e.reason ~= "eof" and e.reason ~= "error" then return end   -- "stop": channel change
    if retry_timer then retry_timer:kill() end
    if attempts < 5 then
        -- streamlink is still starting, or just lost the stream: retry quickly
        retry_timer = mp.add_timeout(2, load_stream)
    else
        offline = true
        set_status(tr("{channel} is not live, retrying in {seconds} s", { channel = channel, seconds = RETRY }))
        retry_timer = mp.add_timeout(RETRY, load_stream)
        auto_switch()
    end
end)


-- Menu

local function toggle_corner(target)   -- the next corner clockwise, or the corner given (tl, tr, br, bl)
    for i, c in ipairs(CORNERS) do
        if target and c == target then
            corner = target
            break
        elseif not target and c == corner then
            corner = CORNERS[i % #CORNERS + 1]
            break
        end
    end
    write_state("chat_corner", corner)
    mp.set_property_native("user-data/streambox/corner", corner)
end

local function toggle_chat()
    chat_visible = not chat_visible
    write_state("chat_visible", chat_visible and "yes" or "no")
    mp.set_property_native("user-data/streambox/chat_visible", chat_visible)
end

-- Companion app QR code (or the box's Wi-Fi one in setup mode), unless hidden by the setting. Returns the drawing
-- and its side, or nil.
local function qr_code(x, y, size)
    local setup = (ambient_data or {}).setup
    if not (setup and setup.ssid) and (qr_mode == "never" or (qr_mode == "timed" and mp.get_time() > qr_until)) then return nil end
    return ass.qr_code(x, y, size, qr_data and qr_data.rows)
end

local function qr_host()
    return ((qr_data and qr_data.url or ""):gsub("^https?://", ""):gsub("/$", ""))
end

-- Bluetooth remote (tested with the Xiaomi TV Stick one): cage forwards its keys to mpv like those of a
-- keyboard. OK and Menu have no standard name: their codes are those of this remote.

local function zap(step)
    local list = read_streamers()
    if #list == 0 then return end
    local idx = 1
    for i, name in ipairs(list) do
        if name == channel then idx = i end
    end
    local name = list[(idx - 1 + step) % #list + 1]
    local info = live[name]
    mp.osd_message(("▶ %s%s"):format(name, info and ("   ● " .. info.viewers) or ("   (" .. tr("offline") .. ")")), 3)
    start_channel(name)
end

-- Video playback bar, YouTube style: shown for a few seconds by Up, ←/→ or OK, removed by Up or
-- Down, and always shown while paused
local BAR_SECONDS = 2.5
local bar = mp.create_osd_overlay("ass-events")
local bar_visible, bar_until = false, 0

-- Live: part kept in memory (start, end = the live edge) and playback position
local function live_window()
    local st = mp.get_property_native("demuxer-cache-state") or {}
    local r = (st["seekable-ranges"] or {})[1]
    local pos = mp.get_property_number("time-pos")
    if not r or not pos then return nil end
    return r.start, r["end"], pos
end

-- When behind (or paused), the small forward buffer of the live stream would block reading the stream: memory would
-- stop filling up and the delay would melt away. We enlarge it as long as we are not at the live edge.
local function set_live_buffer(behind)
    mp.set_property("demuxer-max-bytes", behind and "150MiB" or "750KiB")
end

local scrub = nil   -- video: { from, target, paused } while scrubbing with ← → (see media_seek)
local function draw_bar()
    if qt_ui() then   -- drawn by qml/InfoBar.qml, from user-data/streambox/bar
        bar:remove()
        return
    end
    local w, h = mp.get_osd_size()
    if not w or w == 0 then return end
    local pos = scrub and scrub.target or mp.get_property_number("time-pos") or 0
    local dur = mp.get_property_number("duration")
    local cached = mp.get_property_number("demuxer-cache-time")
    local title = mp.get_property("media-title") or ""
    local left, right   -- texts under the bar (default: elapsed time, duration)
    if mode == "twitch" then
        -- Live: the bar represents what is kept in memory, its right end is the live edge
        local s, e = live_window()
        dur, cached, left = s and (e - s) or nil, nil, ""
        if s then
            local delay = e - pos
            pos = pos - s
            right = delay < LIVE_EDGE and ("{\\1c&H4848FF&}" .. tr("● LIVE")) or ("−" .. clock(delay))
        end
        title = channel .. (live[channel] and ("  ·  " .. live[channel].title) or "")
    end
    local paused = mp.get_property_native("pause")
    local fs = math.floor(h / 30)
    local x0, x1 = math.floor(w * 0.05), math.floor(w * 0.95)
    local by, bh = math.floor(h * 0.9), math.max(4, math.floor(h * 0.008))
    local out = { rect(0, math.floor(h * 0.78), w, h - math.floor(h * 0.78), "000000", "60") }
    -- Title, preceded by a drawn pause symbol (two bars) when the video is paused
    local tx = x0
    if paused then
        out[#out + 1] = rect(x0, by - fs * 2.4, fs * 0.28, fs * 0.9, "FFFFFF", "00")
        out[#out + 1] = rect(x0 + fs * 0.5, by - fs * 2.4, fs * 0.28, fs * 0.9, "FFFFFF", "00")
        tx = x0 + fs * 1.3
    end
    out[#out + 1] = ("{\\an4\\pos(%d,%d)\\fs%d\\bord1.5\\shad0\\3c&H000000&\\1c&HFFFFFF&}%s")
        :format(tx, by - fs * 1.95, fs, ass_escape(title))
    -- Bar: background, part already loaded, part played (Twitch purple), cursor
    out[#out + 1] = rect(x0, by, x1 - x0, bh, "FFFFFF", "A0")
    if dur and dur > 0 then
        local function px(t) return x0 + (x1 - x0) * math.max(0, math.min(1, t / dur)) end
        if cached and cached > pos then out[#out + 1] = rect(px(pos), by, px(cached) - px(pos), bh, "FFFFFF", "60") end
        out[#out + 1] = rect(x0, by, px(pos) - x0, bh, "FF4691", "00")
        out[#out + 1] = ass.disc(px(pos), by + bh / 2, math.floor(bh * 1.8), "FFFFFF")
    end
    out[#out + 1] = ("{\\an7\\pos(%d,%d)\\fs%d\\bord1.5\\shad0\\3c&H000000&\\1c&HFFFFFF&}%s")
        :format(x0, by + bh * 3, math.floor(fs * 0.8), left or clock(pos))
    if right or (dur and dur > 0) then
        out[#out + 1] = ("{\\an9\\pos(%d,%d)\\fs%d\\bord1.5\\shad0\\3c&H000000&\\1c&HFFFFFF&}%s")
            :format(x1, by + bh * 3, math.floor(fs * 0.8), right or clock(dur))
    end
    bar.res_x, bar.res_y = w, h
    bar.data = table.concat(out, "\n")
    bar:update()
end

local ctrl_focus = nil   -- row of buttons under the bar (video, Qt app): chosen button, nil outside the row
-- Focus in a video (Qt app), top to bottom: the title (OK: Info panel), the bar itself (← → scrub; focused whenever
-- the bar shows and neither of the others is), the row of buttons
local title_focus = false   -- video title chosen (↑ from the bar): OK opens the Info panel
local publish_controls   -- (below)
local function hide_bar()
    if ctrl_focus or title_focus then   -- the focus leaves the button row and the title; the row stays published
        ctrl_focus, title_focus = nil, false   -- (emptied, it stayed invisible when the bar came back with ◀ ▶)
        publish_controls()
    end
    bar_visible = false
    bar:remove()
    mp.set_property_native("user-data/streambox/bar", false)
end

local function show_bar(seconds)
    bar_visible, bar_until = true, mp.get_time() + (seconds or BAR_SECONDS)
    mp.set_property_native("user-data/streambox/bar", true)
    draw_bar()
end

mp.register_event("start-file", function() if bar_visible then hide_bar() end end)   -- not over the next video's loading

mp.add_periodic_timer(0.5, function()
    if not bar_visible then return end
    -- not while the title is chosen: the bar stays until it is left
    if mp.get_property_native("idle-active")
            or (not mp.get_property_native("pause") and not title_focus and mp.get_time() > bar_until) then
        hide_bar()
    else
        draw_bar()
    end
end)

mp.observe_property("pause", "bool", function(_, paused)
    if mp.get_property_native("idle-active") then return end
    if paused and mode == "twitch" then set_live_buffer(true) end
    if paused then
        show_bar()
    elseif bar_visible then
        show_bar(1)   -- on resume, the bar stays a little longer
    end
end)

-- "X just went live" notification (sent by remote.py), top right; OK to go there
local TOAST_SECONDS = 12
local toast = mp.create_osd_overlay("ass-events")
local toast_channel, toast_timer = nil, nil

local function hide_toast()
    toast_channel = nil
    if toast_timer then toast_timer:kill() end
    toast:remove()
    mp.set_property_native("user-data/streambox/toast", {})
end

mp.register_script_message("streambox-went-live", function(name)
    if name == channel and mode == "twitch" then return end   -- already watching it
    local info = live[name] or {}
    if qt_ui() then   -- drawn by qml/Toast.qml; OK and Back are still handled here (toast_channel)
        mp.set_property_native("user-data/streambox/toast", { name = name, title = info.title or "",
            game = info.game or "", viewers = info.viewers or 0, seconds = TOAST_SECONDS })
        toast_channel = name
        if toast_timer then toast_timer:kill() end
        toast_timer = mp.add_timeout(TOAST_SECONDS, hide_toast)
        return
    end
    local w, h = mp.get_osd_size()
    if not w or w == 0 then return end
    local fs = math.floor(h / 32)
    local title = info.title or ""
    if #title > 60 then title = title:sub(1, 57) .. "…" end
    local lines = {
        "{\\1c&H4848FF&}● {\\1c&HFFFFFF&}" .. tr("{name} is live", { name = "{\\b1}" .. ass_escape(name) .. "{\\b0}" }),
        "{\\fs" .. math.floor(fs * 0.8) .. "\\1c&HC0C0C0&}" .. ass_escape(title .. (info.game and ("  ·  " .. info.game) or "")),
        "{\\fs" .. math.floor(fs * 0.8) .. "\\1c&HFF4691&}" .. ass_escape(tr("OK to watch")),
    }
    local bw, bh = math.floor(w * 0.34), math.floor(fs * 4.6)
    local x, y = w - bw - math.floor(w * 0.02), math.floor(h * 0.04)
    toast.res_x, toast.res_y = w, h
    toast.data = rect(x, y, bw, bh, "000000", "30") .. "\n" ..
        ("{\\an7\\pos(%d,%d)\\fs%d\\bord1.5\\shad0\\3c&H000000&}"):format(x + fs * 0.8, y + fs * 0.6, fs)
        .. table.concat(lines, "\\N")
    toast:update()
    toast_channel = name
    if toast_timer then toast_timer:kill() end
    toast_timer = mp.add_timeout(TOAST_SECONDS, hide_toast)
end)

-- Move within the live stream kept in memory; "live" goes back to the live edge
local function live_seek(delta)
    local s, e, pos = live_window()
    if not s then return end
    local target = delta == "live" and e or math.max(s, math.min(e, pos + delta))
    set_live_buffer(e - target >= LIVE_EDGE)
    mp.commandv("seek", tostring(target), "absolute")
    show_bar()
end
mp.register_script_message("streambox-live-seek", function(arg)
    if mode == "twitch" then live_seek(arg == "live" and "live" or tonumber(arg) or 0) end
end)

-- Subtitles and audio track during a video (≡ key, Qt app): list built here from track-list, published
-- in user-data/streambox/tracks and drawn by qml/TracksPanel.qml; while it is open, ↑ ↓ choose,
-- OK applies, Back or ≡ close. With mpv alone, ≡ simply switches to the next subtitles.
local LANGS = { fr = "French", fre = "French", fra = "French", en = "English", eng = "English", es = "Spanish",
                spa = "Spanish", de = "German", ger = "German", deu = "German", it = "Italian", ita = "Italian",
                ja = "Japanese", jpn = "Japanese", pt = "Portuguese", por = "Portuguese", nl = "Dutch",
                dut = "Dutch", ko = "Korean", kor = "Korean", zh = "Chinese", chi = "Chinese" }
local tracks_open, tracks_items, tracks_sel = false, {}, 1

local function track_label(t)
    local lang = t.lang and (LANGS[t.lang:lower()] or LANGS[t.lang:lower():sub(1, 2)] or t.lang) or nil
    lang = lang and tr(lang)
    local label = lang or t.title or tr("Track {id}", { id = t.id })
    if lang and t.title and t.title ~= "" and t.title:lower() ~= lang:lower() then label = label .. " · " .. t.title end
    if t.forced then label = tr("{label} (forced)", { label = label }) end
    if t["default"] and t.type == "audio" then label = tr("{label} (original)", { label = label }) end
    return label
end

-- Quality of a YouTube video (Subtitles / audio panel): the heights offered by YouTube, read from the
-- yt-dlp response kept by ytdl_hook (user-data/mpv/ytdl/json-subprocess-result, no new request). A choice reloads
-- the video at the same second with a capped ytdl-format; it applies to this video, the next one starts on Auto
local quality = { default = mp.get_property("ytdl-format"), max = nil, path = nil }   -- a single local (200 limit)
function quality.list()
    local path = mp.get_property("path")
    if quality.cache and quality.cache_path == path then return quality.cache end   -- read once per video
    local res = mp.get_property_native("user-data/mpv/ytdl/json-subprocess-result")
    local info = res and res.stdout and require("mp.utils").parse_json(res.stdout)
    local heights, list = {}, {}
    for _, f in ipairs(info and info.formats or {}) do
        local v = f.vcodec or ""
        if v ~= "" and v ~= "none" and not v:match("^av01") and tonumber(f.height) then
            local h = math.floor(tonumber(f.height))
            heights[h] = math.max(heights[h] or 0, tonumber(f.fps) or 0)
        end
    end
    for h, fps in pairs(heights) do list[#list + 1] = { h = h, fps = fps } end
    table.sort(list, function(a, b) return a.h > b.h end)
    if info then quality.cache, quality.cache_path = list, path end
    return list
end
function quality.set(h)
    quality.max, quality.path = h, mp.get_property("path")
    mp.set_property("ytdl-format", h and ("bestvideo[height<=?%d][vcodec!^=av01]+bestaudio/best"):format(h) or quality.default)
    local pos = mp.get_property_number("time-pos") or 0
    mp.commandv("loadfile", quality.path, "replace", "-1", ("start=%d"):format(math.floor(pos)))
end
mp.register_event("start-file", function()   -- another video: back to automatic quality
    if quality.max and mp.get_property("path") ~= quality.path then
        quality.max, quality.path = nil, nil
        mp.set_property("ytdl-format", quality.default)
    end
end)

local tracks_mode = "subs"   -- panel opened by the Subtitles button (subtitles, audio), Quality or Chapters
local function build_tracks()
    if tracks_mode == "chapters" then   -- start time and title of each chapter, the current one chosen
        local items, cur = { { header = tr("Chapters") } }, mp.get_property_number("chapter", -1)
        for i, c in ipairs(mp.get_property_native("chapter-list") or {}) do
            items[#items + 1] = { kind = "chapter", id = i - 1, selected = cur == i - 1,
                                  label = fmt.clock(c.time or 0) .. "  ·  " .. ((c.title or "") ~= "" and c.title or tr("Chapter {n}", { n = i })) }
        end
        tracks_items = items
        return
    end
    if tracks_mode == "quality" then
        local items, cur = { { header = tr("Quality") } }, (mp.get_property_native("video-params") or {}).h
        items[#items + 1] = { kind = "quality", id = false, selected = not quality.max,
                              label = tr("Auto (best)") .. (cur and not quality.max and ("  ·  " .. cur .. "p") or "") }
        for _, it in ipairs(quality.list()) do
            items[#items + 1] = { kind = "quality", id = it.h, selected = quality.max == it.h,
                                  label = it.h .. "p" .. (it.fps > 30 and math.floor(it.fps + 0.5) or "") }
        end
        tracks_items = items
        return
    end
    local subs, audio, sub_on = {}, {}, false
    for _, t in ipairs(mp.get_property_native("track-list") or {}) do
        if t.type == "sub" then
            subs[#subs + 1] = { kind = "sub", id = t.id, label = track_label(t), selected = t.selected == true, lang = t.lang }
            sub_on = sub_on or t.selected == true
        elseif t.type == "audio" then
            audio[#audio + 1] = { kind = "audio", id = t.id, label = track_label(t), selected = t.selected == true }
        end
    end
    local items = { { header = tr("Subtitles") }, { kind = "sub", id = false, label = tr("Off"), selected = not sub_on } }
    for _, it in ipairs(subs) do items[#items + 1] = it end
    if #audio > 1 then   -- a single audio track: nothing to choose
        items[#items + 1] = { header = tr("Audio") }
        for _, it in ipairs(audio) do items[#items + 1] = it end
    end
    tracks_items = items
end

local function publish_tracks()
    if not tracks_open then
        mp.set_property_native("user-data/streambox/tracks", {})
        return
    end
    mp.set_property_native("user-data/streambox/tracks", { open = true, items = tracks_items, sel = tracks_sel - 1 })
end

local function open_tracks(mode)
    tracks_mode = mode or "subs"
    build_tracks()
    tracks_open = true
    tracks_sel = 2
    for i, it in ipairs(tracks_items) do   -- focus on the current choice
        if (it.kind == "sub" or it.kind == "quality" or it.kind == "chapter") and it.selected then tracks_sel = i break end
    end
    publish_tracks()
end

local function close_tracks()
    if not tracks_open then return end
    tracks_open = false
    publish_tracks()
end

local function tracks_key(key)
    if key == "up" or key == "down" then
        local i = tracks_sel
        repeat i = i + (key == "down" and 1 or -1) until not tracks_items[i] or not tracks_items[i].header
        if tracks_items[i] then tracks_sel = i end
        publish_tracks()
    elseif key == "ok" then
        local it = tracks_items[tracks_sel]
        if it and it.kind == "chapter" then mp.set_property_number("chapter", it.id)
        elseif it and it.kind == "quality" then
            if (it.id or nil) ~= quality.max then quality.set(it.id or nil) end
        elseif it then mp.set_property(it.kind == "sub" and "sid" or "aid", it.id and tostring(it.id) or "no") end
        -- Choice remembered for this video (apply_sub_pref on resume): the language, or off
        if it and it.kind == "sub" then
            if not it.id then save_sub_pref("no") elseif it.lang and it.lang ~= "" then save_sub_pref(it.lang) end
        end
        close_tracks()
    else   -- Back, ≡, Home…
        close_tracks()
    end
end
mp.observe_property("track-list", "native", function()
    if tracks_open then build_tracks() publish_tracks() end
end)
mp.register_event("end-file", close_tracks)

-- Info panel (Qt app, qml/InfoPanel.qml): title, channel or series, full description (user-data/streambox/meta
-- from remote.py). Opened by the Info button of the row or ↑ while paused; ↑ ↓ scroll, Back / OK / ≡ close
local info_open, info_scroll = false, 0
local function publish_info()
    mp.set_property_native("user-data/streambox/info", info_open and { open = true, scroll = info_scroll } or {})
end
local function open_info()
    info_open, info_scroll = true, 0
    hide_bar()
    publish_info()
end
local function close_info()
    if not info_open then return end
    info_open = false
    publish_info()
end
local function info_key(key)
    if key == "down" then info_scroll = info_scroll + 1
    elseif key == "up" then info_scroll = math.max(0, info_scroll - 1)
    else return close_info() end
    publish_info()
end
mp.register_event("end-file", close_info)

-- Video playback: accelerating fast forward, row of buttons under the bar (Qt app), next episode
-- (Jellyfin). States published for InfoBar.qml and NextUp.qml: seekfx, controls, next_card; remote.py publishes next_up.

-- Fast forward: a press jumps 10 s, however fast the presses come; only a held key speeds up, the longer it is held
-- (10 s for the first second, then 30 s, then 1 min). A held key is told from presses by its pace: input.py repeats it
-- every 0.08 s (8 jumps per second kept here), presses never come that close.
-- ← → on the bar scrub: the video pauses and a target moves (cursor and preview there, offset displayed); OK goes there
-- and plays, Back gives up (back where it was, playing or paused as before). The ⏪ ⏩ buttons of the row jump at once.
local seek_last, seek_held, seek_total, seek_dir, seek_n = 0, nil, 0, 0, 0   -- seek_held: time the key began repeating
local function fmt_seek(t)
    t = math.abs(t)
    if t < 60 then return ("%d s"):format(t) end
    local m, sec = math.floor(t / 60), t % 60
    return sec > 0 and ("%d min %02d"):format(m, sec) or ("%d min"):format(m)
end
local function media_seek(dir, at_once)
    local now = mp.get_time()
    if now - seek_last < 0.12 then return end   -- repeat of a held key: no more than 8 jumps per second
    local gap = now - seek_last
    if gap < 0.2 and dir == seek_dir then seek_held = seek_held or now else seek_held = nil end
    if gap >= 0.8 or dir ~= seek_dir then seek_total = 0 end
    seek_last, seek_dir = now, dir
    local held = seek_held and now - seek_held or 0
    local step = held >= 2 and 60 or held >= 1 and 30 or 10
    seek_n = seek_n + 1
    if at_once then
        seek_total = seek_total + step
        mp.commandv("seek", tostring(step * dir))
        mp.set_property_native("user-data/streambox/seekfx", { text = (dir > 0 and "+" or "−") .. fmt_seek(seek_total), n = seek_n })
        return
    end
    if not scrub then
        local pos = mp.get_property_number("time-pos")
        if not pos then return end
        scrub = { from = pos, target = pos, paused = mp.get_property_native("pause") }
        mp.set_property_native("pause", true)
    end
    local dur = mp.get_property_number("duration") or 0   -- unknown (0): no end to stop at
    scrub.target = math.max(0, scrub.target + step * dir)
    if dur > 1 then scrub.target = math.min(dur - 1, scrub.target) end
    local offset = scrub.target - scrub.from
    mp.set_property_native("user-data/streambox/seekfx", { text = (offset < 0 and "−" or "+") .. fmt_seek(math.floor(offset + 0.5)),
                                                           n = seek_n, target = scrub.target })
end
local function scrub_end(go)
    if not scrub then return end
    if go then mp.commandv("seek", tostring(scrub.target), "absolute") end
    mp.set_property_native("pause", not go and scrub.paused)
    scrub = nil
    mp.set_property_native("user-data/streambox/seekfx", { n = seek_n })
end
mp.register_event("end-file", function() scrub = nil end)

-- Next episode (Jellyfin, Plex): remote.py publishes user-data/streambox/next_up { id, title, episode, thumb, service, path }; in the
-- last 20 seconds, a "Next episode in N s" card (OK: right away, Back: no); at the end, it starts
local NEXT_BEFORE = 20
local next_dismissed, next_shown = false, false
-- only during the episode it follows (of): not for a video started afterwards by the Jellyfin shim
local function next_up()
    local n = mp.get_property_native("user-data/streambox/next_up")
    if not (n and n.id and n.of) then return nil end
    local path = mp.get_property("path") or ""
    -- Plex gives the link of the episode (its file has no item id), Jellyfin's link holds the id
    local current = n.path and path == n.path or not n.path and path:find("/Videos/" .. n.of .. "/", 1, true)
    return current and n or nil
end
local next_cache = nil   -- last valid next_up: at the end of the file, path can no longer be read
local function play_next()
    local n = next_up() or next_cache
    if not n then return end
    next_shown = false
    mp.set_property_native("user-data/streambox/next_card", {})
    mp.command_native_async({ name = "subprocess", playback_only = false, capture_stdout = true,
        args = { "curl", "-s", "-m", "10", "-X", "POST", "-H", "Content-Type: application/json",
                 "-d", ('{"id":"%s","from_start":true}'):format(n.id),
                 ("http://127.0.0.1:8080/api/%s_play"):format(n.service or "jellyfin") } }, function() end)
end
local function hide_next(dismiss)
    if dismiss then next_dismissed = true end
    if next_shown then
        next_shown = false
        mp.set_property_native("user-data/streambox/next_card", {})
        if not qt_ui() then mp.osd_message("", 0) end
    end
end
mp.register_event("file-loaded", function() next_dismissed = false hide_next() end)
mp.add_periodic_timer(1, function()
    next_cache = mode == "media" and next_up() or nil
    if mode ~= "media" or next_dismissed or not next_cache then return hide_next() end
    local left = mp.get_property_native("time-remaining")
    if not left or left > NEXT_BEFORE or (mp.get_property_native("duration") or 0) < 120 then return hide_next() end
    next_shown = true
    local n = next_up()
    mp.set_property_native("user-data/streambox/next_card", { seconds = math.max(0, math.ceil(left)), title = n.title,
                                                               episode = n.episode or "", thumb = n.thumb or "" })
    if not qt_ui() then
        mp.osd_message(tr("Next episode in {seconds} s: {title} — OK to start it, Back to stay",
            { seconds = math.ceil(left), title = n.episode or n.title }), 2)
    end
end)
mp.register_event("end-file", function(e)
    if e.reason == "eof" and mode == "media" and not next_dismissed and next_cache then play_next() end
end)

-- Row of buttons under the bar (Qt app): ↓ goes down into it, ← → choose, OK, ↑ or Back go back up
local function controls_list()
    local paused = mp.get_property_native("pause")
    -- −10 s, Play / Pause, +10 s first (InfoBar.qml puts them in the middle of the screen), then the others (on the
    -- right): subtitles, quality, chapters, next episode
    local list = { { id = "back", label = "−10 s" }, { id = "play", label = paused and tr("Play") or tr("Pause") },
                   { id = "fwd", label = "+10 s" }, { id = "tracks", label = tr("Subtitles") } }
    -- Quality: YouTube only, when several resolutions are offered (Jellyfin: original file)
    if #quality.list() > 1 then list[#list + 1] = { id = "quality", label = tr("Quality") } end
    if #(mp.get_property_native("chapter-list") or {}) > 1 then list[#list + 1] = { id = "chapters", label = tr("Chapters") } end
    if next_up() then list[#list + 1] = { id = "next", label = tr("Next episode") } end
    return list
end
function publish_controls()   -- (declared above hide_bar)
    local list = controls_list()
    if ctrl_focus then ctrl_focus = math.max(1, math.min(#list, ctrl_focus)) end
    mp.set_property_native("user-data/streambox/controls", { items = list, focus = ctrl_focus and ctrl_focus - 1 or -1,
                                                             title = title_focus })
end
mp.observe_property("pause", "bool", function() if mode == "media" then publish_controls() end end)
mp.register_event("file-loaded", function() ctrl_focus = nil publish_controls() end)
local function controls_key(key)
    local list = controls_list()
    if key == "left" then ctrl_focus = math.max(1, ctrl_focus - 1)
    elseif key == "right" then ctrl_focus = math.min(#list, ctrl_focus + 1)
    elseif key == "up" then ctrl_focus = nil   -- ↑: back up to the bar
    elseif key == "back" then ctrl_focus = nil
    elseif key == "ok" then
        local id = (list[ctrl_focus] or {}).id
        if id == "back" or id == "fwd" then media_seek(id == "fwd" and 1 or -1, true)
        elseif id == "play" then mp.commandv("cycle", "pause")
        elseif id == "tracks" then open_tracks()
        elseif id == "quality" then open_tracks("quality")
        elseif id == "chapters" then open_tracks("chapters")
        elseif id == "next" then play_next() end
    end
    show_bar()
    publish_controls()
end

-- Quick menu of the simplified version (mpv alone): lists built by quickmenu.py (remote.py), which gets the keys
-- (script-message streambox-qm open | close | key <name>) and publishes what to show in user-data/streambox/quickmenu
local qm_overlay = mp.create_osd_overlay("ass-events")
local qm_data, qm_open, qm_idle, qm_wait = {}, false, nil, nil
local function qm_draw()
    local w, h = mp.get_osd_size()
    if not qm_open or not w or w == 0 then return qm_overlay:remove() end
    qm_overlay.res_x, qm_overlay.res_y = w, h
    qm_overlay.data = quick.draw(w, h, qm_data, tr("↑↓ choose · OK open · ← back · Menu close"))
    qm_overlay:update()
end
local function qm_send(...)
    mp.commandv("script-message", "streambox-qm", ...)
    if qm_idle then qm_idle:kill() end
    qm_idle = mp.add_timeout(MENU_TIMEOUT, function() mp.commandv("script-message", "streambox-qm", "close") end)
end
local function qm_toggle()
    if qm_open then return qm_send("close") end
    streamers = read_streamers()   -- reread on each opening: the file is edited live
    qm_send("open")
    if qm_wait then qm_wait:kill() end
    qm_wait = mp.add_timeout(3, function()   -- remote.py stopped or restarting
        mp.osd_message(tr("Menu unavailable: the box's service is not answering"), 4)
    end)
end
mp.observe_property("user-data/streambox/quickmenu", "native", function(_, v)
    qm_data = v or {}
    qm_open = qm_data.items ~= nil
    if qm_wait then qm_wait:kill() qm_wait = nil end
    qm_draw()
end)
mp.observe_property("osd-dimensions", "native", function() if qm_open then qm_draw() end end)

-- Big Android TV style menu (qml/TvMenu.qml): opened by the Menu button (Home key); while it is open,
-- all keys are forwarded to it. With mpv alone, the same button opens and closes the quick menu above
local tvmenu_open = false
mp.observe_property("user-data/streambox/tvmenu", "native", function(_, v) tvmenu_open = v == true end)
open_tvmenu = function()
    if setup_pending() then
        return mp.osd_message(tr("Continue the setup on your phone: scan the QR code"), 4)
    end
    hide_bar()
    if not big_menu() then return qm_toggle() end
    mp.commandv("script-message", "streambox-tvmenu-open")
end


-- Power button (Bluetooth remote, box button): same action as the off button of the page and of Home
-- Assistant ("Off button" setting: sleep or full shutdown). logind no longer acts by itself: remote.py holds a
-- "handle-power-key" inhibitor lock. Ignored right after startup or a wake-up (the key that wakes also arrives).
local power_quiet_until = mp.get_time() + 15
local function power_key()
    if mp.get_time() < power_quiet_until then return end
    power_quiet_until = mp.get_time() + 15
    mp.command_native_async({ name = "subprocess", playback_only = false, capture_stdout = true,
        args = { "curl", "-s", "-m", "10", "-X", "POST", "-H", "Content-Type: application/json", "-d", "{}",
                 "http://127.0.0.1:8080/api/poweroff" } }, function() end)
end

local function on_key(key)
    if key == "power" then return power_key() end
    if key == "power_menu" then   -- power held: "sleep, restart, shut down" window (QML menu)
        if not big_menu() then return power_key() end   -- mpv alone: the power button's usual action
        hide_bar()
        return mp.commandv("script-message", "streambox-power-menu")
    end
    if key == "volume_up" or key == "volume_down" then
        mp.commandv("add", "volume", key == "volume_up" and "5" or "-5")
        mp.osd_message(tr("Volume {n}%", { n = ("%d"):format(mp.get_property_number("volume", 0)) }), 1.5)
        return
    elseif key == "mute" then
        mp.commandv("cycle", "mute")
        mp.osd_message(mp.get_property_native("mute") and tr("Sound muted") or tr("Sound on"), 1.5)
        return
    end
    if tvmenu_open then
        mp.commandv("script-message", "streambox-tvmenu-key", key)
        return
    end
    if qm_open then
        qm_send("key", key)
        return
    end
    if tracks_open then
        tracks_key(key)
        return
    end
    if info_open then
        info_key(key)
        return
    end
    if scrub and mode == "media" and key ~= "left" and key ~= "right" then   -- scrubbing: OK goes there, the rest gives up
        scrub_end(key == "ok")
        show_bar()
        if key == "ok" or key == "back" then return end
    end
    if next_shown and mode == "media" and (key == "ok" or key == "back") then   -- "Next episode" card
        if key == "ok" then play_next() else hide_next(true) end
        return
    end
    if ctrl_focus and mode == "media" and key ~= "home" and key ~= "menu" then
        controls_key(key)
        return
    end
    if title_focus and mode == "media" and key ~= "home" and key ~= "menu" then
        -- Title chosen: OK opens the Info panel, ↓ goes back down to the bar, ↑ closes the bar, Back leaves the
        -- title (without stopping the video)
        title_focus = false
        if key == "ok" then publish_controls() return open_info() end
        if key == "up" then publish_controls() return hide_bar() end
        show_bar()
        publish_controls()
        return
    end
    if key == "homescreen" then   -- home screen, from any mode (keys learned when the wizard still offered it)
        if mode ~= "home" then show_home() end
        return
    elseif key == "corner" then   -- next corner for the chat
        toggle_corner()
        mp.osd_message(tr("Chat: {corner}", { corner = tr(CORNER_LABELS[corner]) }), 2)
        return
    end
    if toast_channel and (key == "ok" or key == "back") then
        local name = toast_channel
        hide_toast()
        if key == "ok" then start_channel(name) end
        return
    end
    if mode == "home" then   -- home screen: any key opens the menu, the main page
        open_tvmenu()
    elseif mode == "twitch" then
        if key == "up" or key == "down" then
            zap(key == "down" and 1 or -1)
        elseif key == "ok" then
            -- Info banner: streamer, live title, "LIVE" or delay; the menu opens with Home
            if bar_visible then hide_bar() else show_bar() end
        elseif key == "home" then
            open_tvmenu()
        elseif key == "left" or key == "right" then
            live_seek(key == "right" and 10 or -10)
        elseif key == "back" then   -- stop the stream, back to the menu
            show_home()
            open_tvmenu()
        elseif key == "menu" then
            toggle_chat()
            mp.osd_message(chat_visible and tr("Chat shown") or tr("Chat hidden"), 2)
        end
    else   -- video (link, Jellyfin)
        if key == "ok" then
            mp.commandv("cycle", "pause")
            show_bar()
        elseif key == "left" or key == "right" then
            media_seek(key == "right" and 1 or -1)
            show_bar()
        elseif key == "up" then
            if bar_visible and qt_ui() then   -- bar shown: ↑ chooses the title (OK: Info panel)
                title_focus = true
                show_bar()
                publish_controls()
            elseif bar_visible then hide_bar() else show_bar() end
        elseif key == "down" then
            if qt_ui() then   -- bar hidden: shows it (focus on the bar); bar focused: the button row, on Pause / Play
                if bar_visible then ctrl_focus = 2 end   -- (controls_list: Play / Pause is second)
                show_bar()
                publish_controls()
            elseif not mp.get_property_native("pause") then
                hide_bar()
            end
        elseif key == "home" then
            open_tvmenu()
        elseif key == "menu" then
            if qt_ui() then open_tracks() show_bar() else mp.commandv("cycle", "sub") end
        elseif key == "back" then   -- stop the video (position kept by the history), back to the menu
            show_home()
            open_tvmenu()
        end
    end
end

-- Keys (fallback names, learned keys, "Set up keys" wizard, actions from input.py): lua/streambox/keys.lua
keys.setup(on_key, qt_ui)

-- Companion app (remote.py): same actions as the menu
-- Channel chosen from the phone or Home Assistant: menu closed (not for automatic restarts of the live stream)
mp.register_script_message("streambox-channel", function(name)
    mp.commandv("script-message", "streambox-tvmenu-close")
    start_channel(name)
end)
mp.register_script_message("streambox-toggle-chat", toggle_chat)
mp.register_script_message("streambox-cycle-corner", function(target) toggle_corner(target) end)
mp.register_script_message("streambox-play", play_media)
mp.register_script_message("streambox-home", show_home)
mp.register_script_message("streambox-setup-done", home_menu)
-- Small banner at the top (remote connected…, sent by input.py): qml/Notice.qml, or a message with mpv alone
mp.register_script_message("streambox-notice", function(text)
    if qt_ui() then
        mp.set_property_native("user-data/streambox/notice", { text = text, id = mp.get_time() })
    else
        mp.osd_message(text, 4)
    end
end)   -- "Finish" on the phone page
mp.register_script_message("streambox-twitch", function() start_channel(channel) end)
-- Wake-up after sleep (remote.py, resume_loop): streams cut, restart what was playing
mp.register_script_message("streambox-resume", function()
    power_quiet_until = mp.get_time() + 15
    if mode == "twitch" and channel then
        start_channel(channel)
    elseif mode == "media" then
        local path, pos = mp.get_property("path"), mp.get_property_number("time-pos")
        if path then
            local opts = pos and pos > 5 and ("start=%d"):format(math.floor(pos)) or ""
            mp.commandv("loadfile", path, "replace", "-1", opts)
        end
    end
end)

-- Numeric settings of the chat and subtitles, editable from the companion app: default, minimum, maximum
local NUMBERS = { chat_bg = { 60, 0, 100 },     -- background opacity, in %
                  chat_size = { 32, 20, 60 },   -- text size, in 1920x1080 pixels
                  sub_size = { 100, 50, 200 },  -- subtitle size, in % of mpv's
                  sub_bg = { 0, 0, 100 } }      -- subtitle background: opacity of a black box, in % (0: outline)

-- Subtitles: size (sub-scale) and background (black box behind the text, otherwise the usual outline and shadow)
local function apply_sub_style()
    local size = mp.get_property_native("user-data/streambox/sub_size") or 100
    local bg = mp.get_property_native("user-data/streambox/sub_bg") or 0
    mp.set_property_number("sub-scale", size / 100)
    if bg > 0 then
        mp.set_property("sub-border-style", "background-box")
        mp.set_property("sub-back-color", ("#%02X000000"):format(math.floor(bg * 2.55 + 0.5)))
    else
        mp.set_property("sub-border-style", "outline-and-shadow")
    end
end

local function set_number(key, value)
    local spec, n = NUMBERS[key], tonumber(value)
    if not spec or not n then return end
    n = math.max(spec[2], math.min(spec[3], math.floor(n + 0.5)))
    write_state(key, tostring(n))
    mp.set_property_native("user-data/streambox/" .. key, n)
    if key:sub(1, 4) == "sub_" then apply_sub_style() end
end
mp.register_script_message("streambox-set", set_number)

local function set_auto_switch(value)
    auto_switch_on = value ~= "no" and value ~= false
    write_state("auto_switch", auto_switch_on and "yes" or "no")
    mp.set_property_native("user-data/streambox/auto_switch", auto_switch_on)
    auto_switch()   -- re-enabled while the channel is offline: switch right away
end
mp.register_script_message("streambox-auto-switch", set_auto_switch)

-- Ambient screen: when nothing plays (channel offline, empty list), clock, date, weather and upcoming streams
-- (data from remote.py in user-data/streambox/ambient), drawn by lua/streambox/ambient.lua with mpv alone
local ambient = mp.create_osd_overlay("ass-events")
local ambient_screen = require "streambox.ambient"
ambient.z = -10   -- below the menu and the notifications
local ambient_drawn = nil

local function ambient_wanted()
    return (mode == "home" or (mode == "twitch" and (offline or #streamers == 0)))
        and not mp.get_property_native("video-params")
end

local function draw_ambient()
    -- Qt app: the home screen is drawn in QML (qml/AmbientScreen.qml), from ambient_on and status
    if mp.get_property_native("user-data/streambox/chat_ui") == "qml" then
        ambient:remove()
        return
    end
    local w, h = mp.get_osd_size()
    if not w or w == 0 then return end
    ambient.res_x, ambient.res_y = w, h
    ambient.data = ambient_screen.draw(w, h, ambient_data, status_text, qr_code, qr_host())
    ambient:update()
end

local function update_ambient(force)
    if ambient_wanted() then
        local key = os.time() .. status_text   -- redrawn every 2 s: the background moves continuously
        if not ambient_visible then
            ambient_visible = true
            set_loading(nil)   -- channel offline, home screen: nothing left to wait for
            qr_until = mp.get_time() + QR_SECONDS
            status:remove()
            mp.set_property_native("user-data/streambox/ambient_on", true)
        end
        if force or key ~= ambient_drawn then
            ambient_drawn = key
            draw_ambient()
        end
    elseif ambient_visible then
        ambient_visible, ambient_drawn = false, nil
        ambient:remove()
        mp.set_property_native("user-data/streambox/ambient_on", false)
        set_status(status_text)   -- puts back the status message ("Loading…") if there is one
    end
end
mp.add_periodic_timer(2, function() update_ambient(false) end)
mp.observe_property("user-data/streambox/ambient", "native", function(_, value)
    ambient_data = value or {}
    local qr = ambient_data.qr
    local setup = ambient_data.setup
    if setup and setup.ssid then qr = { url = setup.url, rows = setup.wifi_rows } end   -- QR code of the box's Wi-Fi
    qr_data = qr
    if ambient_visible then update_ambient(true) end
end)

mp.observe_property("user-data/streambox/live", "native", function(_, value)
    live = value or {}
    auto_switch()
end)

-- Watchdog: live stream whose picture has not moved for FROZEN seconds while not paused
-- (stream stuck, buffer jammed) → restart the channel
local last_pos, last_move = nil, 0
mp.add_periodic_timer(5, function()
    local pos = mp.get_property_number("playback-time")
    if mode ~= "twitch" or offline or not pos or mp.get_property_native("pause") then
        last_pos, last_move = nil, mp.get_time()
    elseif pos ~= last_pos then
        last_pos, last_move = pos, mp.get_time()
    elseif mp.get_time() - last_move > FROZEN then
        mp.msg.warn(("live stream frozen for %d s: restarting %s"):format(FROZEN, channel))
        last_pos, last_move = nil, mp.get_time()
        start_channel(channel)
    end
end)

-- Polls and predictions of the watched channel (fetched by remote.py into user-data/streambox/polls): box at
-- the top center, away from the corners where the chat goes, with the time left and the share of each choice
local events = mp.create_osd_overlay("ass-events")
local polls = require "streambox.polls"
local events_data, events_on = {}, true

local function draw_events()
    local poll, pred = events_data.poll, events_data.prediction
    local w, h = mp.get_osd_size()
    -- Qt app: box drawn by qml/PollsOverlay.qml (user-data/streambox/polls and events)
    if qt_ui() or not events_on or mode ~= "twitch" or not (poll or pred) or not w or w == 0 then
        events:remove()
        return
    end
    events.res_x, events.res_y = w, h
    events.data = polls.draw(w, h, events_data)
    events:update()
end

mp.observe_property("user-data/streambox/polls", "native", function(_, value)
    events_data = value or {}
    draw_events()
end)
mp.add_periodic_timer(1, function()   -- time left
    if events_data.poll or events_data.prediction then draw_events() end
end)

-- Yes / no settings, from the companion app: { default, applied on each change and at startup }
-- Night mode: compressor that brings loud passages closer to quiet ones (explosions, screams), then limiter
local NIGHT_FILTER = "@night:lavfi=[acompressor=threshold=0.05:ratio=6:attack=10:release=300:makeup=3,"
    .. "alimiter=limit=0.9]"
local FLAGS = {
    night = { false, function(on)
        local present = false
        for _, f in ipairs(mp.get_property_native("af") or {}) do
            if f.label == "night" then present = true end
        end
        if on and not present then
            mp.commandv("af", "add", NIGHT_FILTER)
        elseif present and not on then
            mp.commandv("af", "remove", "@night")
        end
    end },
    events = { true, function(on)
        events_on = on
        draw_events()
    end },
}

local function set_flag(key, value, quiet)
    local spec = FLAGS[key]
    if not spec then return end
    local on = value == "yes"
    write_state(key, on and "yes" or "no")
    mp.set_property_native("user-data/streambox/" .. key, on)
    spec[2](on)
    if not quiet and key == "night" then mp.osd_message(on and tr("Night mode on") or tr("Night mode off"), 2) end
end
mp.register_script_message("streambox-flag", set_flag)
for key, spec in pairs(FLAGS) do
    local saved = read_state(key)
    set_flag(key, saved or (spec[1] and "yes" or "no"), true)
end

-- Display of the companion app QR code: always, timed (QR_SECONDS seconds each time the ambient screen appears),
-- never
local function set_qr_mode(value)
    if not QR_MODES[value] then return end
    qr_mode, qr_until = value, mp.get_time() + QR_SECONDS   -- in "timed", show it right away as an example
    write_state("qr", value)
    mp.set_property_native("user-data/streambox/qr", value)
    if ambient_visible then update_ambient(true) end
end
mp.register_script_message("streambox-qr", set_qr_mode)
set_qr_mode(read_state("qr") or "always")

-- Interface language changed (companion app): reload the translations and redraw what is visible
mp.register_script_message("streambox-language", function()
    I18N.load()
    if qm_open then qm_draw() end
    if ambient_visible then update_ambient(true) end
    if bar_visible then draw_bar() end
    if tracks_open then build_tracks() publish_tracks() end
    if mode == "media" then publish_controls() end
    draw_events()
end)

-- No full-screen double-click: the box must stay full screen
mp.add_forced_key_binding("MBTN_LEFT_DBL", "streambox-no-dbl", function() end)


mp.command_native({ name = "subprocess", playback_only = false, args = { "mkdir", "-p", STATE_DIR } })
streamers = read_streamers()
corner = read_state("chat_corner")
if not CORNER_LABELS[corner] then corner = "bl" end
chat_visible = read_state("chat_visible") ~= "no"
auto_switch_on = read_state("auto_switch") ~= "no"
mp.set_property_native("user-data/streambox/auto_switch", auto_switch_on)
mp.set_property_native("user-data/streambox/corner", corner)
mp.set_property_native("user-data/streambox/chat_visible", chat_visible)
for key, spec in pairs(NUMBERS) do
    set_number(key, read_state(key) or spec[1])
end
-- Start on the menu, nothing playing; the last watched streamer stays the current channel (Back to the stream,
-- Home Assistant, zapping), if it is still in the list. Short delay: the Qt app's menu is loading.
local last = read_state("channel")
for _, name in ipairs(streamers) do
    if name == last then channel = last end
end
channel = channel or streamers[1]
if channel then mp.set_property_native("user-data/streambox/channel", channel) end
set_mode("home")
mp.add_timeout(3, home_menu)

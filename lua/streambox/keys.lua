-- Remote, keyboard and gamepad keys: names → actions, learned keys and the "Set up keys" wizard. Normally input.py
-- reads the keys at the source and sends the actions (streambox-input); the mpv / Qt key names below are a fallback.
-- M.setup(on_key, qt_ui) binds the keys and the script-messages; on_key(action) plays the action.
local mp = require "mp"
local utils = require "mp.utils"
local I18N = require "streambox.i18n"
local tr = I18N.tr

local M = {}
local on_key, qt_ui

local KEYS = {
    UP = "up", DOWN = "down", LEFT = "left", RIGHT = "right",
    ENTER = "ok", KP_ENTER = "ok", ["0x21ffa0"] = "ok",
    HOMEPAGE = "home", GO_BACK = "back", ESC = "back", ["0x2111a0"] = "menu",
    WWW = "homescreen",
    PLAY = "corner", PLAYPAUSE = "corner",   -- without this binding, mpv turns them into pause, which froze the live stream
    POWER = "power", ["0x21ff2a"] = "power",  -- power button (remote, box): mpv alone, Qt app
    VOLUME_UP = "volume_up", VOLUME_DOWN = "volume_down", MUTE = "mute",
    -- Regular keyboard (same actions as input.py; here, names depend on the keyboard layout)
    SPACE = "corner", m = "home", o = "menu", h = "homescreen", ["+"] = "volume_up", ["-"] = "volume_down",
    KP_ADD = "volume_up", KP_SUBTRACT = "volume_down", NEXT = "right", PREV = "left", STOP = "back",
}
-- These names (mpv, or hacked keysyms like 0x21ffa0) are only a fallback: normally, input.py reads the keys
-- at the source with Linux names and sends the actions (streambox-input); while it runs, keys received
-- here are ignored (otherwise each one would count twice)
local input_beat = 0
-- (read as "native": as "string", mpv gives user-data values JSON-formatted, quotes included, and the beat was never seen)
mp.observe_property("user-data/streambox/input", "native", function(_, v)
    input_beat = tonumber(tostring(v or ""):match("^evdev:(%d+)")) or 0
end)
function M.input_service() return os.time() - input_beat < 15 end
local input_service = M.input_service
M.DIRECTIONS = { up = { 0, -1 }, down = { 0, 1 }, left = { -1, 0 }, right = { 1, 0 } }
local DIRECTIONS = M.DIRECTIONS

-- Learned keys ("Configure keys" wizard of the System menu): ~/.config/stream-box/keymap.json,
-- {"mpv key name": "action"}, on top of KEYS (a learned key can also replace the one of another action)
local KEYMAP_FILE = (os.getenv("HOME") or "") .. "/.config/stream-box/keymap.json"
local bound = {}   -- bound names, to be able to unbind and rebind everything
local learn_key    -- wizard running: receives the name of each key instead of on_key

local function read_keymap()
    local f = io.open(KEYMAP_FILE)
    if not f then return {} end
    local data = utils.parse_json(f:read("*a") or "") or {}
    f:close()
    return data
end

local function bind_keys()
    for name in pairs(bound) do mp.remove_key_binding("streambox-key-" .. name) end
    bound = {}
    local map = {}
    for name, key in pairs(KEYS) do map[name] = key end
    for name, key in pairs(read_keymap()) do map[name] = key end
    for name, key in pairs(map) do
        if key == "power" and not name:match("^KEY_") then
            -- Fallback: short power on release, held 1 s → window (ui.py sends keydown / keyup for these keys)
            local timer = nil
            mp.add_forced_key_binding(name, "streambox-key-" .. name, function(t)
                if input_service() then return end
                if learn_key then if t.event ~= "up" then learn_key(name) end return end
                if t.event == "down" then
                    if timer then timer:kill() end
                    timer = mp.add_timeout(1, function() timer = nil; on_key("power_menu") end)
                elseif t.event == "up" and timer then
                    timer:kill(); timer = nil
                    on_key("power")
                elseif t.event == "press" then
                    on_key("power")
                end
            end, { complex = true })
            bound[name] = true
        elseif not name:match("^KEY_") and not name:match("^BTN_") and not name:match("^HAT_") then   -- Linux names: input.py
            mp.add_forced_key_binding(name, "streambox-key-" .. name, function()
                if input_service() then return end
                if learn_key then learn_key(name) else on_key(key) end
            end, { repeatable = DIRECTIONS[key] ~= nil or key == "volume_up" or key == "volume_down" })
            bound[name] = true
        end
    end
end

-- Wizard: the actions one by one; a key within 8 s learns it, otherwise the action keeps its key. State in
-- user-data/streambox/learn (drawn by qml/KeyWizard.qml), and as an on-screen message with mpv alone
local LEARN = { { "up", "Up" }, { "down", "Down" }, { "left", "Left" }, { "right", "Right" }, { "ok", "OK" },
                { "back", "Back" }, { "home", "TV menu" }, { "menu", "Options (≡)" },
                { "homescreen", "Home screen" }, { "corner", "Play / chat corner" }, { "power", "Power" } }
local LEARN_WAIT = 8
local learn = nil   -- { step, learned = { name = action }, timer, last }

local function learn_publish(phase, key)
    local item = LEARN[learn.step]
    mp.set_property_native("user-data/streambox/learn", { phase = phase, step = learn.step, total = #LEARN,
        label = item and tr(item[2]) or "", key = key or "", seconds = LEARN_WAIT })
    if not qt_ui() then
        mp.osd_message(phase == "done" and tr("Keys saved") or phase == "cancel" and tr("Wizard canceled: keys unchanged")
            or tr(phase == "taken" and "Keys {step}/{total}: press the key for \"{action}\" (already taken)"
                or "Keys {step}/{total}: press the key for \"{action}\"",
                { step = learn.step, total = #LEARN, action = tr(item[2]) }),
            (phase == "done" or phase == "cancel") and 3 or LEARN_WAIT)
    end
end

local learn_step
local function learn_finish()
    local map = read_keymap()
    for name, action in pairs(learn.learned) do map[name] = action end
    local f = io.open(KEYMAP_FILE, "w")
    if f then f:write(utils.format_json(map)) f:close() end
    learn.step = #LEARN
    learn_publish("done")
    learn_key, learn = nil, nil
    mp.remove_key_binding("streambox-learn-unmapped")
    bind_keys()
    mp.add_timeout(3, function() if not learn then mp.set_property_native("user-data/streambox/learn", {}) end end)
end

-- Back on the page's virtual remote: quit without saving anything
local function learn_cancel()
    if learn.timer then learn.timer:kill() end
    learn_publish("cancel")
    learn_key, learn = nil, nil
    mp.remove_key_binding("streambox-learn-unmapped")
    mp.add_timeout(3, function() if not learn then mp.set_property_native("user-data/streambox/learn", {}) end end)
end

learn_step = function()
    if learn.timer then learn.timer:kill() end
    if learn.step > #LEARN then return learn_finish() end
    learn_publish("wait")
    learn.timer = mp.add_timeout(LEARN_WAIT, function() learn.step = learn.step + 1; learn_step() end)
end

local function learn_press(name)
    if not learn or not name or name:match("^MOUSE") or name:match("^MBTN") or name:match("^WHEEL") then return end
    local now = mp.get_time()
    if now - (learn.last or 0) < 0.6 then return end   -- held key, or bounce
    learn.last = now
    if learn.learned[name] then learn_publish("taken", name) return end   -- already given to a previous action
    learn.learned[name] = LEARN[learn.step][1]
    learn_publish("ok", name)
    if learn.timer then learn.timer:kill() end
    learn.timer = mp.add_timeout(0.7, function() learn.step = learn.step + 1; learn_step() end)
end

function M.setup(play, is_qt)
    on_key, qt_ui = play, is_qt
    bind_keys()
    mp.register_script_message("streambox-keymap-wizard", function()
        if learn then return end
        mp.commandv("script-message", "streambox-tvmenu-close")
        learn = { step = 1, learned = {} }
        learn_publish("wait")
        -- The OK key that started the wizard must not be taken for "Up"
        mp.add_timeout(0.8, function()
            learn_key = learn_press
            if not input_service() then   -- fallback: keys unknown to mpv (otherwise input.py sends everything)
                mp.add_forced_key_binding("UNMAPPED", "streambox-learn-unmapped", function(t)
                    if t.event == "down" or t.event == "press" then learn_press(t.key_name) end
                end, { complex = true })
            end
            learn_step()
        end)
    end)

    -- Keys read at the source by input.py: Linux name (KEY_SELECT…) and action; the wizard learns the name
    mp.register_script_message("streambox-input", function(name, action)
        if learn_key then
            -- The page's virtual remote is not learned; its Back quits the wizard
            if name ~= "VIRTUAL" then learn_key(name) elseif action == "back" then learn_cancel() end
            return
        end
        if action and action ~= "" then on_key(action) end
    end)

    mp.register_script_message("streambox-keymap-reset", function()
        os.remove(KEYMAP_FILE)
        bind_keys()
        mp.osd_message(tr("Remote keys reset to default"), 3)
    end)
end

return M

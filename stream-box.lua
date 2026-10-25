-- Stream Box : menu affiché quand la souris bouge (choix du streamer, coin du chat),
-- et gestion de streamlink, qui sert le flux de la chaîne choisie en HTTP local à ce mpv.
-- La chaîne, le coin et la visibilité du chat sont publiés dans user-data/streambox/* pour chat_overlay.py.
-- Deux modes : « twitch » (stream de la chaîne choisie) et « media » (vidéo envoyée depuis la télécommande ou
-- Jellyfin). Tout fichier qui n'est pas le flux streamlink fait passer en « media » ; quand il se termine et que
-- mpv reste vide, on revient au stream.
local mp = require "mp"

local DIR = debug.getinfo(1, "S").source:match("^@(.*)/[^/]*$")
local STREAMERS_FILE = DIR .. "/streamers.txt"
local STATE_DIR = (os.getenv("XDG_STATE_HOME") or (os.getenv("HOME") .. "/.local/state")) .. "/stream-box"

local CORNERS = { "tl", "tr", "br", "bl" }   -- ordre du toggle (sens horaire)
local CORNER_LABELS = { tl = "↖ haut gauche", tr = "↗ haut droite", br = "↘ bas droite", bl = "↙ bas gauche" }
local MENU_TIMEOUT = 4    -- secondes sans bouger la souris avant de masquer le menu
local MENU_TIMEOUT_KEYS = 10   -- idem quand on le pilote avec la télécommande
local RETRY = 15          -- secondes entre deux essais quand la chaîne n'est pas en live
local BACK_TO_TWITCH = 3  -- secondes à vide après une vidéo avant de revenir au stream (laisse Jellyfin enchaîner)
local AUTO_SWITCH = 60    -- secondes hors ligne (après un changement de chaîne) avant de passer à un streamer en live
local FROZEN = 20         -- secondes d'image figée, sans pause, avant de relancer le direct
local LIVE_BACK = "400MiB" -- direct gardé en mémoire pour revenir en arrière (≈ 7-8 min en 1080p60)
local LIVE_EDGE = 4       -- secondes de retard en dessous desquelles on considère être « en direct »
local BASE_PORT = 34500

local streamers, channel, corner, chat_visible
local server, port_n = nil, os.time() % 50
local attempts, retry_timer = 0, nil
local mode, back_timer = "twitch", nil
local live, offline, channel_since = {}, false, 0   -- live : relevé de remote.py (user-data/streambox/live)
local ambient_visible, status_text = false, ""    -- écran d'ambiance affiché ; dernier message d'état
local auto_switch_on = true   -- bascule automatique vers un streamer en live (réglage de la télécommande)
local qr_data = nil           -- QR code de la télécommande web, publié par remote.py avec l'écran d'ambiance
local ambient_data = {}       -- user-data/streambox/ambient (météo, plannings, QR code, mode configuration)
local QR_MODES = { always = true, timed = true, never = true }   -- toujours, QR_SECONDS secondes, jamais
local QR_SECONDS = 30
local qr_mode, qr_until = "always", 0   -- en mode « timed », affiché jusqu'à qr_until (mp.get_time)
local menu = mp.create_osd_overlay("ass-events")
local status = mp.create_osd_overlay("ass-events")
local menu_visible, hide_timer, items = false, nil, {}
local sel, keyboard_nav = nil, false   -- bouton sélectionné à la télécommande (index dans items)
local started = mp.get_time()


local function ass_escape(s)
    -- Même échappement que les scripts intégrés de mpv
    return (s:gsub("\\", "\\\239\187\191"):gsub("{", "\\{"))
end

-- Appli Qt (ui.py) : bandeau, barre de lecture, notifications, encart des sondages et écran d'accueil sont dessinés en
-- QML ; ce script garde la logique (quand, combien de temps, touches) et publie l'état dans user-data/streambox/*
local function qt_ui()
    return mp.get_property_native("user-data/streambox/chat_ui") == "qml"
end

local function read_streamers()
    local list = {}
    local f = io.open(STREAMERS_FILE)
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

-- Réglages (chaîne, chat) gardés d'un démarrage à l'autre, un fichier par réglage dans STATE_DIR
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

-- Écran de chargement entre deux vidéos ou deux chaînes (sinon l'image reste figée et ça ressemble à un blocage) :
-- user-data/streambox/loading { title, thumb } jusqu'à la première image (playback-restart), une erreur ou 45 s au plus ;
-- dessiné par qml/LoadingOverlay.qml, ou simple message à l'écran avec mpv seul
local loading_timer, loading_osd = nil, false
local function set_loading(title, thumb, kind)   -- kind : twitch, youtube, jellyfin ou video (couleur de l'animation)
    if loading_timer then loading_timer:kill() loading_timer = nil end
    if title then
        mp.set_property_native("user-data/streambox/loading", { title = title, thumb = thumb or "", kind = kind or "video" })
        -- appli Qt (vo=libmpv, connu dès le démarrage, contrairement à chat_ui) : l'écran QML suffit
        loading_osd = mp.get_property("vo") ~= "libmpv"
        if loading_osd then mp.osd_message("Chargement de " .. title .. "…", 45) end
        loading_timer = mp.add_timeout(45, function() set_loading(nil) end)
    else
        mp.set_property_native("user-data/streambox/loading", {})
        if loading_osd then mp.osd_message("", 0) end
        loading_osd = false
    end
end
mp.register_event("playback-restart", function() set_loading(nil) end)
mp.register_event("end-file", function(e) if e.reason == "error" then set_loading(nil) end end)

local function set_status(text)
    status_text = text
    mp.set_property_native("user-data/streambox/status", text)   -- pour l'écran d'accueil en QML (appli Qt)
    if text == "" or ambient_visible then   -- l'écran d'ambiance affiche lui-même ce message, en petit
        status:remove()
        return
    end
    status.res_x, status.res_y = 1920, 1080
    status.data = "{\\an5\\pos(960,540)\\fs40\\bord2\\shad0\\3c&H000000&\\1c&HC0C0C0&}" .. ass_escape(text)
    status:update()
end


-- Lecture : streamlink tourne en serveur HTTP local, mpv lit http://127.0.0.1:<port>/

local function stream_url()
    return ("http://127.0.0.1:%d/"):format(BASE_PORT + port_n)
end

local function load_stream()
    retry_timer = nil
    attempts = attempts + 1
    -- La pause survit au changement de fichier dans mpv : une vidéo laissée en pause figerait le direct
    mp.set_property_native("pause", false)
    mp.commandv("loadfile", stream_url())
end

local function start_server(name)
    port_n = port_n % 50 + 1   -- nouveau port : l'ancien peut rester occupé quelques secondes
    local handle
    handle = mp.command_native_async({
        name = "subprocess", playback_only = false,
        args = { "streamlink", "--twitch-low-latency", "--retry-streams", "30",
                 "--player-external-http", "--player-external-http-interface", "127.0.0.1",
                 "--player-external-http-port", tostring(BASE_PORT + port_n),
                 "twitch.tv/" .. name, "best" },
    }, function(_, res)
        if server == handle and not (res and res.killed_by_us) then
            -- streamlink s'est arrêté tout seul : on le relance
            mp.add_timeout(5, function() if server == handle then start_server(name) end end)
        end
    end)
    server = handle
end

local function set_mode(m)
    -- Fin d'un stream (ou début, voir start_channel) : heure gardée pour Retour ×2 sur l'écran d'accueil, qui reprend
    -- le plus récent du dernier stream et de la dernière vidéo (remote.py, resume_last)
    if mode == "twitch" or m == "twitch" then write_state("channel_at", tostring(os.time())) end
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
    set_mode("twitch")   -- avant le « stop » ci-dessous, pour que sa fin de fichier soit lue comme un changement de chaîne
    set_loading(name, nil, "twitch")
    mp.set_property_bool("pause", false)   -- mpv garde la pause d'un fichier à l'autre
    offline, channel_since = false, mp.get_time()
    stop_twitch()
    start_server(name)
    mp.commandv("stop")
    attempts = 0
    set_status("Chargement de " .. name .. "…")
    retry_timer = mp.add_timeout(2, load_stream)
end

-- start : position de reprise en secondes (historique de remote.py), donnée à mpv comme option du fichier pour ne pas
-- voir un saut après le chargement
-- title : titre à afficher (Jellyfin : le lien du flux n'en donne pas), passé en option du fichier (%n% : longueur
-- en octets, pour que virgules et signes égal du titre passent tels quels)
-- thumb, label : image et titre de l'écran de chargement (label : titre connu, sans l'imposer à mpv)
local function play_media(url, start, title, thumb, label)
    stop_twitch()
    set_mode("media")
    local kind = (url:find("youtube%.com/") or url:find("youtu%.be/")) and "youtube"
        or url:find("/Videos/%x+/stream") and "jellyfin" or url:find("twitch%.tv/") and "twitch" or "video"
    set_loading((label and label ~= "" and label) or (title and title ~= "" and title) or "la vidéo", thumb, kind)
    mp.set_property_bool("pause", false)   -- mpv garde la pause d'un fichier à l'autre
    local at = tonumber(start) or 0
    local opts = title and title ~= "" and ("force-media-title=%%%d%%%s"):format(#title, title) or nil
    if at > 0 or opts then
        local all = {}
        if at > 0 then all[#all + 1] = ("start=%d"):format(at) end
        if opts then all[#all + 1] = opts end
        mp.commandv("loadfile", url, "replace", "-1", table.concat(all, ","))
        local h, m, sec = math.floor(at / 3600), math.floor(at / 60) % 60, at % 60
        if at > 0 then
            mp.osd_message(h > 0 and ("Reprise à %d:%02d:%02d"):format(h, m, sec) or ("Reprise à %d:%02d"):format(m, sec), 4)
        end
    else
        mp.commandv("loadfile", url)
    end
end

-- Juste avant l'ouverture de chaque fichier, y compris ceux que charge Jellyfin : petit tampon pour le direct
-- (latence), tampon normal pour les vidéos. Et décodage par l'iGPU, que le shim Jellyfin peut avoir désactivé.
mp.add_hook("on_load", 50, function()
    local is_live = mp.get_property("stream-open-filename") == stream_url()
    mp.set_property("demuxer-max-bytes", is_live and "750KiB" or "150MiB")
    -- Direct : on garde les dernières minutes et on autorise à s'y déplacer (le flux lui-même n'est pas « seekable »)
    mp.set_property("demuxer-max-back-bytes", is_live and LIVE_BACK or "50MiB")
    mp.set_property("demuxer-seekable-cache", is_live and "yes" or "auto")
    mp.set_property("hwdec", "auto-safe")
end)

-- Écran d'accueil à la demande : plus de stream, ni de bascule automatique, jusqu'au choix d'un streamer ou d'une vidéo
local function show_home()
    stop_twitch()
    set_mode("home")
    mp.commandv("stop")
end

mp.register_event("start-file", function()
    if mp.get_property("path") == stream_url() then return end
    if mode == "twitch" or mode == "home" then
        -- Fichier chargé par quelqu'un d'autre (Jellyfin) : on lui laisse la place
        stop_twitch()
        set_mode("media")
    elseif back_timer then
        back_timer:kill()   -- vidéo suivante : on reste en mode média
        back_timer = nil
    end
end)

local function url_encode(s)
    return (s:gsub("[^%w%-_%.~]", function(c) return ("%%%02X"):format(c:byte()) end))
end

-- Sous-titres automatiques de YouTube (kind=asr) : leurs répliques se chevauchent, deux restent toujours à l'écran.
-- On les recharge via remote.py, qui coupe chaque réplique au début de la suivante. En EDL « delay_open », comme
-- ytdl_hook : une piste n'est téléchargée que si on la choisit (YouTube répond vite « 429 » aux rafales).
local function fix_auto_subs()
    for _, t in ipairs(mp.get_property_native("track-list") or {}) do
        local edl = t.type == "sub" and t["external-filename"] or ""
        local len, rest = edl:match("%%(%d+)%%(.*)$")   -- ytdl_hook les ajoute en EDL : %longueur%url
        local url = len and rest:sub(1, tonumber(len)) or ""
        if url:match("^https://www%.youtube%.com/api/timedtext") and url:match("[?&]kind=asr") then
            mp.commandv("sub-remove", tostring(t.id))
            local fixed = "http://127.0.0.1:8080/subs?u=" .. url_encode(url)
            mp.commandv("sub-add", ("edl://!no_clip;!delay_open,media_type=sub;%%%d%%%s"):format(#fixed, fixed),
                        t.selected and "select" or "auto", t.title or "", t.lang or "")
        end
    end
end

mp.register_event("file-loaded", function()
    attempts = 0
    offline = false
    set_status("")
    if mode == "media" then fix_auto_subs() end
end)

-- Chaîne hors ligne depuis plus d'AUTO_SWITCH secondes : on passe au premier streamer en live, dans l'ordre de
-- streamers.txt. Le délai laisse le temps de choisir exprès une chaîne hors ligne (le temps de vérifier).
local function auto_switch()
    if not auto_switch_on or mode ~= "twitch" or not offline or mp.get_time() - channel_since < AUTO_SWITCH then return end
    for _, name in ipairs(read_streamers()) do
        if name ~= channel and live[name] then
            mp.osd_message(channel .. " n'est pas en live : on passe sur " .. name, 6)
            start_channel(name)
            return
        end
    end
end

mp.register_event("end-file", function(e)
    if mode == "home" then return end
    if mode == "media" then
        if e.reason == "error" then mp.osd_message("Impossible de lire cette vidéo", 5) end
        if back_timer then back_timer:kill() end
        back_timer = mp.add_timeout(BACK_TO_TWITCH, function()
            back_timer = nil
            if mode == "media" and mp.get_property_native("idle-active") then start_channel(channel) end
        end)
        return
    end
    if e.reason ~= "eof" and e.reason ~= "error" then return end   -- "stop" : changement de chaîne
    if retry_timer then retry_timer:kill() end
    if attempts < 5 then
        -- streamlink démarre encore, ou vient de perdre le flux : on réessaie vite
        retry_timer = mp.add_timeout(2, load_stream)
    else
        offline = true
        set_status(channel .. " n'est pas en live, nouvel essai dans " .. RETRY .. " s")
        retry_timer = mp.add_timeout(RETRY, load_stream)
        auto_switch()
    end
end)


-- Menu

local function toggle_corner()
    for i, c in ipairs(CORNERS) do
        if c == corner then
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

local function rect(x, y, w, h, color, alpha)
    w, h = math.floor(w), math.floor(h)
    return ("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\1a&H%s&\\p1}m 0 0 l %d 0 %d %d 0 %d{\\p0}")
        :format(math.floor(x), math.floor(y), color, alpha, w, w, h, h)
end

local function text(x, y, size, color, s, suffix)   -- suffix : ASS brut ajouté après le texte échappé
    return ("{\\an5\\pos(%d,%d)\\fs%d\\bord1.5\\shad0\\3c&H000000&\\1c&H%s&}%s%s")
        :format(math.floor(x), math.floor(y), math.floor(size), color, ass_escape(s), suffix or "")
end

-- QR code de la télécommande web, pour les invités : carré clair (gris, moins marquant pour l'écran que du blanc) et
-- modules sombres en un seul tracé, une bande par suite de modules. Renvoie le dessin et son côté, ou nil.
local function qr_code(x, y, size)
    local setup = (ambient_data or {}).setup
    if not (setup and setup.ssid) and (qr_mode == "never" or (qr_mode == "timed" and mp.get_time() > qr_until)) then return nil end
    local rows = qr_data and qr_data.rows or {}
    local n = #rows
    local m = n > 0 and math.floor(size / (n + 4)) or 0   -- marge de 2 modules tout autour
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
    return rect(x, y, side, side, "C8C8C8", "00") .. "\n" ..
        ("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H101010&\\1a&H00&\\p1}%s{\\p0}")
            :format(math.floor(x), math.floor(y), table.concat(paths, " ")), side
end

local function qr_host()
    return ((qr_data and qr_data.url or ""):gsub("^https?://", ""):gsub("/$", ""))
end

local function live_badge(name)
    local info = live[name]
    if not info then return nil end
    local v = tonumber(info.viewers) or 0
    local count = v >= 1000 and (("%.1f k"):format(v / 1000):gsub("%.", ",")) or tostring(v)
    return "{\\1c&H4848FF&}  ● " .. count   -- rouge (BGR)
end

local function draw_menu()
    local w, h = mp.get_osd_size()
    if not w or w == 0 then return end
    local mouse = mp.get_property_native("mouse-pos") or {}

    -- Les streamers en grille : autant de colonnes que nécessaire, et police réduite si ça ne
    -- rentre toujours pas dans 90 % de l'écran. La ligne du chat (case + coin) prend toute la largeur en dessous.
    local n = math.max(#streamers, 1)   -- liste vide : on garde une case pour la mise en page
    local fs, bw, bh, sp, title_h, cols, rows, panel_w, panel_h
    fs = h / 24
    repeat
        bw, bh, sp, title_h = fs * 10, fs * 1.7, fs * 0.35, fs * 2
        local max_rows = math.max(1, math.floor((h * 0.9 - title_h - bh * 2 - sp * 5) / (bh + sp)))
        cols = math.ceil(n / max_rows)
        rows = math.ceil(n / cols)
        panel_w = cols * bw + (cols - 1) * sp
        panel_h = title_h + rows * (bh + sp) + sp * 4 + bh * 2
        local fits = panel_w <= w * 0.9
        if not fits then fs = fs * 0.9 end
    until fits or fs < 10
    local x0, y0 = math.floor((w - panel_w) / 2), math.floor((h - panel_h) / 2)

    local out = { rect(x0 - sp * 2, y0 - sp * 2, panel_w + sp * 4, panel_h + sp * 3, "000000", "50"),
                  text(w / 2, y0 + title_h / 2, fs, "FFFFFF", "Streamers") }
    items = {}
    local function button(x, y, bw_, label, current, action, checked, text_color, suffix)
        local hover
        if keyboard_nav then
            hover = sel == #items + 1
        else
            hover = mouse.x and mouse.x >= x and mouse.x <= x + bw_ and mouse.y >= y and mouse.y <= y + bh
        end
        local color = current and "FF4691" or (hover and "606060" or "303030")   -- violet Twitch en BGR
        if keyboard_nav and hover then
            out[#out + 1] = rect(x - fs * 0.12, y - fs * 0.12, bw_ + fs * 0.24, bh + fs * 0.24, "FFFFFF", "00")   -- cadre
        end
        out[#out + 1] = rect(x, y, bw_, bh, color, hover and "00" or "20")
        if checked ~= nil then
            -- Case à cocher dessinée, centrée (les glyphes ☐/☑ ne sont pas dans toutes les polices)
            local box = fs * 0.8
            local bx, by = x + (bw_ - box) / 2, y + (bh - box) / 2
            out[#out + 1] = rect(bx, by, box, box, "FFFFFF", "00")
            out[#out + 1] = rect(bx + fs * 0.08, by + fs * 0.08, box - fs * 0.16, box - fs * 0.16, "202020", "00")
            if checked then
                out[#out + 1] = rect(bx + fs * 0.2, by + fs * 0.2, box - fs * 0.4, box - fs * 0.4, "FF4691", "00")
            end
        end
        out[#out + 1] = text(x + bw_ / 2, y + bh / 2, fs, text_color or "FFFFFF", (current and "▶ " or "") .. label,
                             suffix)
        items[#items + 1] = { x0 = x, y0 = y, x1 = x + bw_, y1 = y + bh, action = action }
    end
    -- Écran d'accueil en haut, au-dessus de la grille. Les streamers restent les premiers boutons de items (on_key
    -- s'y fie) : la navigation à la télécommande ne dépend que des positions.
    local grid_y = y0 + title_h + bh + sp * 2
    for i, name in ipairs(streamers) do
        local col, row = math.floor((i - 1) / rows), (i - 1) % rows   -- remplissage colonne par colonne
        button(x0 + col * (bw + sp), grid_y + row * (bh + sp), bw, name, name == channel and mode == "twitch",
               function() start_channel(name) end, nil, nil, live_badge(name))
    end
    button(x0, y0 + title_h, panel_w, "⌂ Écran d'accueil", mode == "home", show_home)
    local y = grid_y + rows * (bh + sp) + sp
    button(x0, y, bh, "", false, toggle_chat, chat_visible)   -- case : afficher / masquer le chat
    button(x0 + bh + sp, y, panel_w - bh - sp, "Chat : " .. CORNER_LABELS[corner], false, toggle_corner, nil,
           chat_visible and "FFFFFF" or "808080")

    -- QR code de la télécommande à droite du menu, s'il y a la place (pas sur l'écran d'ambiance, qui a le sien)
    local size = math.floor(math.min(panel_h, h * 0.3))
    local qx = x0 + panel_w + sp * 6
    if not ambient_visible and qx + size + sp * 2 <= w * 0.98 then
        local qy = y0 + (panel_h - size - fs * 1.6) / 2
        local drawing, side = qr_code(qx, qy, size)
        if drawing then
            out[#out + 1] = rect(qx - sp * 2, qy - sp * 2, side + sp * 4, side + fs * 1.6 + sp * 4, "000000", "50")
            out[#out + 1] = drawing
            out[#out + 1] = text(qx + side / 2, qy + side + fs * 0.5, fs * 0.6, "FFFFFF", "Télécommande")
            out[#out + 1] = text(qx + side / 2, qy + side + fs * 1.2, fs * 0.5, "B0B0B0", qr_host())
        end
    end

    menu.res_x, menu.res_y = w, h
    menu.data = table.concat(out, "\n")
    menu:update()
end

local function hide_menu()
    menu_visible = false
    sel, keyboard_nav = nil, false
    menu:remove()
    mp.remove_key_binding("streambox-click")
end

local function on_click()
    local m = mp.get_property_native("mouse-pos") or {}
    for _, it in ipairs(items) do
        if m.x and m.x >= it.x0 and m.x <= it.x1 and m.y >= it.y0 and m.y <= it.y1 then
            it.action()
            draw_menu()
            return
        end
    end
    hide_menu()   -- clic en dehors des boutons
end

local function show_menu(by_key)
    if not menu_visible then
        menu_visible = true
        qr_until = mp.get_time() + QR_SECONDS
        streamers = read_streamers()   -- relu à chaque ouverture : le fichier s'édite à chaud
        mp.add_forced_key_binding("MBTN_LEFT", "streambox-click", on_click)
        if by_key then
            -- Sélection de départ : la chaîne en cours
            sel = 1
            for i, name in ipairs(streamers) do
                if name == channel then sel = i end
            end
        end
    end
    if by_key then keyboard_nav = true end
    draw_menu()
    if hide_timer then hide_timer:kill() end
    hide_timer = mp.add_timeout(keyboard_nav and MENU_TIMEOUT_KEYS or MENU_TIMEOUT, hide_menu)
end

mp.observe_property("mouse-pos", "native", function(_, m)
    -- Ignore la position initiale du curseur au lancement de mpv
    if m and mp.get_time() - started > 2 and not mp.get_property_native("user-data/streambox/tvmenu") then
        keyboard_nav = false
        show_menu()
    end
end)


-- Télécommande Bluetooth (testé avec celle du Xiaomi TV Stick) : cage transmet ses touches à mpv comme celles d'un
-- clavier. OK et Menu n'ont pas de nom standard : leurs codes sont ceux de cette télécommande.

-- Bouton le plus proche dans la direction (dx, dy), depuis le bouton sélectionné
local function move_selection(dx, dy)
    local cur = items[sel or 1]
    if not cur then return end
    local cx, cy = (cur.x0 + cur.x1) / 2, (cur.y0 + cur.y1) / 2
    local best, best_score
    for i, it in ipairs(items) do
        local ix, iy = (it.x0 + it.x1) / 2 - cx, (it.y0 + it.y1) / 2 - cy
        local along, across = ix * dx + iy * dy, math.abs(ix * dy - iy * dx)
        if i ~= sel and along > 0 then
            local score = along + 2 * across
            if not best_score or score < best_score then best, best_score = i, score end
        end
    end
    if best then sel = best end
end

local function zap(step)
    local list = read_streamers()
    if #list == 0 then return end
    local idx = 1
    for i, name in ipairs(list) do
        if name == channel then idx = i end
    end
    local name = list[(idx - 1 + step) % #list + 1]
    local info = live[name]
    mp.osd_message(("▶ %s%s"):format(name, info and ("   ● " .. info.viewers) or "   (hors ligne)"), 3)
    start_channel(name)
end

-- Barre de lecture des vidéos, façon YouTube : affichée quelques secondes par Haut, ←/→ ou OK, retirée par Haut ou
-- Bas, et toujours affichée pendant la pause
local BAR_SECONDS = 5
local bar = mp.create_osd_overlay("ass-events")
local bar_visible, bar_until = false, 0

-- Disque de rayon r centré en (cx, cy) : quatre quarts de cercle en courbes de Bézier (k ≈ 0,5523 r)
local function disc(cx, cy, r, color)
    local k, d = r * 0.5523, 2 * r
    return ("{\\an5\\pos(%d,%d)\\bord0\\shad0\\1c&H%s&\\1a&H00&\\p1}"
        .. "m %d 0 b %d 0 %d %d %d %d b %d %d %d %d %d %d b %d %d %d %d 0 %d b 0 %d %d 0 %d 0{\\p0}")
        :format(math.floor(cx), math.floor(cy), color,
                r, r + k, d, r - k, d, r,  d, r + k, r + k, d, r, d,  r - k, d, 0, r + k, r,  r - k, r - k, r)
end

-- Direct : partie gardée en mémoire (début, fin = le direct) et position de lecture
local function live_window()
    local st = mp.get_property_native("demuxer-cache-state") or {}
    local r = (st["seekable-ranges"] or {})[1]
    local pos = mp.get_property_number("time-pos")
    if not r or not pos then return nil end
    return r.start, r["end"], pos
end

-- En différé (ou en pause), le petit tampon avant du direct bloquerait la lecture du flux : la mémoire cesserait de
-- se remplir et le retard fondrait. On l'agrandit tant qu'on n'est pas au bord du direct.
local function set_live_buffer(behind)
    mp.set_property("demuxer-max-bytes", behind and "150MiB" or "750KiB")
end

local function clock(t)
    t = math.max(0, math.floor(t or 0))
    local h, m, sec = math.floor(t / 3600), math.floor(t / 60) % 60, t % 60
    return h > 0 and ("%d:%02d:%02d"):format(h, m, sec) or ("%d:%02d"):format(m, sec)
end

local function draw_bar()
    if qt_ui() then   -- dessinée par qml/InfoBar.qml, d'après user-data/streambox/bar
        bar:remove()
        return
    end
    local w, h = mp.get_osd_size()
    if not w or w == 0 then return end
    local pos = mp.get_property_number("time-pos") or 0
    local dur = mp.get_property_number("duration")
    local cached = mp.get_property_number("demuxer-cache-time")
    local title = mp.get_property("media-title") or ""
    local left, right   -- textes sous la barre (par défaut : temps écoulé, durée)
    if mode == "twitch" then
        -- Direct : la barre représente ce qui est gardé en mémoire, son bout droit est le direct
        local s, e = live_window()
        dur, cached, left = s and (e - s) or nil, nil, ""
        if s then
            local delay = e - pos
            pos = pos - s
            right = delay < LIVE_EDGE and "{\\1c&H4848FF&}● EN DIRECT" or ("−" .. clock(delay))
        end
        title = channel .. (live[channel] and ("  ·  " .. live[channel].title) or "")
    end
    local paused = mp.get_property_native("pause")
    local fs = math.floor(h / 30)
    local x0, x1 = math.floor(w * 0.05), math.floor(w * 0.95)
    local by, bh = math.floor(h * 0.9), math.max(4, math.floor(h * 0.008))
    local out = { rect(0, math.floor(h * 0.78), w, h - math.floor(h * 0.78), "000000", "60") }
    -- Titre, précédé d'un symbole pause dessiné (deux barres) quand la vidéo est en pause
    local tx = x0
    if paused then
        out[#out + 1] = rect(x0, by - fs * 2.4, fs * 0.28, fs * 0.9, "FFFFFF", "00")
        out[#out + 1] = rect(x0 + fs * 0.5, by - fs * 2.4, fs * 0.28, fs * 0.9, "FFFFFF", "00")
        tx = x0 + fs * 1.3
    end
    out[#out + 1] = ("{\\an4\\pos(%d,%d)\\fs%d\\bord1.5\\shad0\\3c&H000000&\\1c&HFFFFFF&}%s")
        :format(tx, by - fs * 1.95, fs, ass_escape(title))
    -- Barre : fond, partie déjà chargée, partie lue (violet Twitch), curseur
    out[#out + 1] = rect(x0, by, x1 - x0, bh, "FFFFFF", "A0")
    if dur and dur > 0 then
        local function px(t) return x0 + (x1 - x0) * math.max(0, math.min(1, t / dur)) end
        if cached and cached > pos then out[#out + 1] = rect(px(pos), by, px(cached) - px(pos), bh, "FFFFFF", "60") end
        out[#out + 1] = rect(x0, by, px(pos) - x0, bh, "FF4691", "00")
        out[#out + 1] = disc(px(pos), by + bh / 2, math.floor(bh * 1.8), "FFFFFF")
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

local ctrl_focus = nil   -- rangée de boutons sous la barre (vidéo, appli Qt) : bouton choisi, nil hors de la rangée
local function hide_bar()
    if ctrl_focus then   -- la rangée de boutons part avec la barre
        ctrl_focus = nil
        mp.set_property_native("user-data/streambox/controls", { items = {}, focus = -1 })
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

mp.add_periodic_timer(0.5, function()
    if not bar_visible then return end
    if mp.get_property_native("idle-active") or (not mp.get_property_native("pause") and mp.get_time() > bar_until) then
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
        show_bar(2)   -- à la reprise, la barre reste encore un peu
    end
end)

-- Notification « X vient de lancer son live » (envoyée par remote.py), en haut à droite ; OK pour y aller
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
    if name == channel and mode == "twitch" then return end   -- on le regarde déjà
    local info = live[name] or {}
    if qt_ui() then   -- dessinée par qml/Toast.qml ; OK et Retour restent gérés ici (toast_channel)
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
        "{\\1c&H4848FF&}● {\\1c&HFFFFFF&\\b1}" .. ass_escape(name) .. "{\\b0} est en live",
        "{\\fs" .. math.floor(fs * 0.8) .. "\\1c&HC0C0C0&}" .. ass_escape(title .. (info.game and ("  ·  " .. info.game) or "")),
        "{\\fs" .. math.floor(fs * 0.8) .. "\\1c&HFF4691&}OK pour regarder",
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

-- Se déplacer dans le direct gardé en mémoire ; « live » revient au direct
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

-- Sous-titres et piste audio pendant une vidéo (touche ≡, appli Qt) : liste construite ici depuis track-list, publiée
-- dans user-data/streambox/tracks et dessinée par qml/TracksPanel.qml ; tant qu'elle est ouverte, ↑ ↓ choisissent,
-- OK applique, Retour ou ≡ ferment. Avec mpv seul, ≡ passe simplement aux sous-titres suivants.
local LANGS = { fr = "Français", fre = "Français", fra = "Français", en = "Anglais", eng = "Anglais", es = "Espagnol",
                spa = "Espagnol", de = "Allemand", ger = "Allemand", deu = "Allemand", it = "Italien", ita = "Italien",
                ja = "Japonais", jpn = "Japonais", pt = "Portugais", por = "Portugais", nl = "Néerlandais",
                dut = "Néerlandais", ko = "Coréen", kor = "Coréen", zh = "Chinois", chi = "Chinois" }
local tracks_open, tracks_items, tracks_sel = false, {}, 1

local function track_label(t)
    local lang = t.lang and (LANGS[t.lang:lower()] or LANGS[t.lang:lower():sub(1, 2)] or t.lang) or nil
    local label = lang or t.title or ("Piste " .. t.id)
    if lang and t.title and t.title ~= "" and t.title:lower() ~= lang:lower() then label = label .. " · " .. t.title end
    if t.forced then label = label .. " (forcés)" end
    if t["default"] and t.type == "audio" then label = label .. " (d'origine)" end
    return label
end

local function build_tracks()
    local subs, audio, sub_on = {}, {}, false
    for _, t in ipairs(mp.get_property_native("track-list") or {}) do
        if t.type == "sub" then
            subs[#subs + 1] = { kind = "sub", id = t.id, label = track_label(t), selected = t.selected == true }
            sub_on = sub_on or t.selected == true
        elseif t.type == "audio" then
            audio[#audio + 1] = { kind = "audio", id = t.id, label = track_label(t), selected = t.selected == true }
        end
    end
    local items = { { header = "Sous-titres" }, { kind = "sub", id = false, label = "Désactivés", selected = not sub_on } }
    for _, it in ipairs(subs) do items[#items + 1] = it end
    if #audio > 1 then   -- une seule piste audio : rien à choisir
        items[#items + 1] = { header = "Audio" }
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

local function open_tracks()
    build_tracks()
    tracks_open = true
    tracks_sel = 2
    for i, it in ipairs(tracks_items) do   -- focus sur le choix en cours
        if it.kind == "sub" and it.selected then tracks_sel = i break end
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
        if it then mp.set_property(it.kind == "sub" and "sid" or "aid", it.id and tostring(it.id) or "no") end
        close_tracks()
    else   -- Retour, ≡, Accueil…
        close_tracks()
    end
end
mp.observe_property("track-list", "native", function()
    if tracks_open then build_tracks() publish_tracks() end
end)
mp.register_event("end-file", close_tracks)

-- Lecture d'une vidéo : avance rapide qui accélère, rangée de boutons sous la barre (appli Qt), épisode suivant
-- (Jellyfin). États publiés pour InfoBar.qml et NextUp.qml : seekfx, controls, next_card ; remote.py publie next_up.

-- Avance rapide : appuis rapprochés ou touche maintenue → sauts de 10 s, puis 30 s, puis 1 min ; total affiché
local seek_last, seek_streak, seek_total, seek_dir, seek_n = 0, 0, 0, 0, 0
local function fmt_seek(t)
    t = math.abs(t)
    if t < 60 then return ("%d s"):format(t) end
    local m, sec = math.floor(t / 60), t % 60
    return sec > 0 and ("%d min %02d"):format(m, sec) or ("%d min"):format(m)
end
local function media_seek(dir)
    local now = mp.get_time()
    if now - seek_last < 0.12 then return end   -- répétition d'une touche maintenue : pas plus de 8 sauts par seconde
    if now - seek_last < 0.8 and dir == seek_dir then seek_streak = seek_streak + 1 else seek_streak, seek_total = 0, 0 end
    seek_last, seek_dir = now, dir
    local step = seek_streak < 3 and 10 or seek_streak < 9 and 30 or 60
    seek_total = seek_total + step
    seek_n = seek_n + 1
    mp.commandv("seek", tostring(step * dir))
    mp.set_property_native("user-data/streambox/seekfx", { text = (dir > 0 and "+" or "−") .. fmt_seek(seek_total), n = seek_n })
end

-- Épisode suivant (Jellyfin) : remote.py publie user-data/streambox/next_up { id, title, episode, thumb } ; dans les
-- 20 dernières secondes, une carte « Épisode suivant dans N s » (OK : tout de suite, Retour : non) ; à la fin, il part
local NEXT_BEFORE = 20
local next_dismissed, next_shown = false, false
-- seulement pendant l'épisode dont c'est la suite (of) : pas pour une vidéo lancée ensuite par le shim Jellyfin
local function next_up()
    local n = mp.get_property_native("user-data/streambox/next_up")
    if not (n and n.id and n.of) then return nil end
    return (mp.get_property("path") or ""):find("/Videos/" .. n.of .. "/", 1, true) and n or nil
end
local next_cache = nil   -- dernier next_up valable : à la fin du fichier, path n'est plus lisible
local function play_next()
    local n = next_up() or next_cache
    if not n then return end
    next_shown = false
    mp.set_property_native("user-data/streambox/next_card", {})
    mp.command_native_async({ name = "subprocess", playback_only = false, capture_stdout = true,
        args = { "curl", "-s", "-m", "10", "-X", "POST", "-H", "Content-Type: application/json",
                 "-d", ('{"id":"%s","from_start":true}'):format(n.id), "http://127.0.0.1:8080/api/jellyfin_play" } }, function() end)
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
        mp.osd_message(("Épisode suivant dans %d s : %s — OK pour le lancer, Retour pour rester"):format(math.ceil(left), n.episode or n.title), 2)
    end
end)
mp.register_event("end-file", function(e)
    if e.reason == "eof" and mode == "media" and not next_dismissed and next_cache then play_next() end
end)

-- Rangée de boutons sous la barre (appli Qt) : ↓ y descend, ← → choisissent, OK, ↑ ou Retour remontent
local function controls_list()
    local paused = mp.get_property_native("pause")
    local list = { { id = "back", label = "−10 s" }, { id = "play", label = paused and "Lecture" or "Pause" },
                   { id = "fwd", label = "+10 s" }, { id = "tracks", label = "Sous-titres" } }
    if #(mp.get_property_native("chapter-list") or {}) > 1 then list[#list + 1] = { id = "chapter", label = "Chapitre suivant" } end
    if next_up() then list[#list + 1] = { id = "next", label = "Épisode suivant" } end
    return list
end
local function publish_controls()
    local list = controls_list()
    if ctrl_focus then ctrl_focus = math.max(1, math.min(#list, ctrl_focus)) end
    mp.set_property_native("user-data/streambox/controls", { items = list, focus = ctrl_focus and ctrl_focus - 1 or -1 })
end
mp.observe_property("pause", "bool", function() if mode == "media" then publish_controls() end end)
mp.register_event("file-loaded", function() ctrl_focus = nil publish_controls() end)
local function controls_key(key)
    local list = controls_list()
    if key == "left" then ctrl_focus = math.max(1, ctrl_focus - 1)
    elseif key == "right" then ctrl_focus = math.min(#list, ctrl_focus + 1)
    elseif key == "up" or key == "back" then ctrl_focus = nil
    elseif key == "ok" then
        local id = (list[ctrl_focus] or {}).id
        if id == "back" or id == "fwd" then media_seek(id == "fwd" and 1 or -1)
        elseif id == "play" then mp.commandv("cycle", "pause")
        elseif id == "tracks" then open_tracks()
        elseif id == "chapter" then mp.commandv("add", "chapter", "1")
        elseif id == "next" then play_next() end
    end
    show_bar()
    publish_controls()
end

local back_pressed = 0
-- Grand menu façon Android TV (tv_menu.lua) : ouvert par le bouton Menu (touche Accueil) ; tant qu'il est ouvert,
-- toutes les touches lui sont transmises
local tvmenu_open = false
mp.observe_property("user-data/streambox/tvmenu", "native", function(_, v) tvmenu_open = v == true end)
local function open_tvmenu()
    if menu_visible then hide_menu() end
    hide_bar()
    mp.commandv("script-message", "streambox-tvmenu-open")
end

local KEYS = {
    UP = "up", DOWN = "down", LEFT = "left", RIGHT = "right",
    ENTER = "ok", KP_ENTER = "ok", ["0x21ffa0"] = "ok",
    HOMEPAGE = "home", GO_BACK = "back", ESC = "back", ["0x2111a0"] = "menu",
    WWW = "homescreen",
    PLAY = "corner", PLAYPAUSE = "corner",   -- sans ce lien, mpv les traduit en pause, ce qui figeait le direct
    POWER = "power", ["0x21ff2a"] = "power",  -- bouton power (télécommande, boîtier) : mpv seul, appli Qt
    VOLUME_UP = "volume_up", VOLUME_DOWN = "volume_down", MUTE = "mute",
}
-- Ces noms (mpv, ou keysyms bricolés comme 0x21ffa0) ne servent qu'en secours : normalement, input.py lit les touches
-- à la source avec les noms de Linux et envoie les actions (streambox-input) ; tant qu'il tourne, les touches reçues
-- ici sont ignorées (sinon chacune compterait deux fois)
local input_beat = 0
mp.observe_property("user-data/streambox/input", "string", function(_, v)
    input_beat = tonumber((v or ""):match("^evdev:(%d+)")) or 0
end)
local function input_service() return os.time() - input_beat < 15 end
local DIRECTIONS = { up = { 0, -1 }, down = { 0, 1 }, left = { -1, 0 }, right = { 1, 0 } }

-- Bouton power (télécommande Bluetooth, bouton du boîtier) : même action que le bouton d'arrêt de la page et de Home
-- Assistant (réglage « Bouton d'arrêt » : veille ou arrêt complet). logind n'agit plus de lui-même : remote.py tient un
-- verrou « handle-power-key ». Ignoré juste après le démarrage ou un réveil (la touche qui réveille arrive aussi).
local power_quiet_until = mp.get_time() + 15
local function power_key()
    if mp.get_time() < power_quiet_until then return end
    power_quiet_until = mp.get_time() + 15
    mp.command_native_async({ name = "subprocess", playback_only = false, capture_stdout = true,
        args = { "curl", "-s", "-m", "10", "-X", "POST", "-H", "Content-Type: application/json", "-d", "{}",
                 "http://127.0.0.1:8080/api/poweroff" } }, function() end)
end

-- Retour deux fois pendant un stream : dernière vidéo de l'historique, reprise là où elle en était (remote.py) ;
-- sur l'écran d'accueil : le plus récent du dernier stream et de la dernière vidéo
local function resume_last()
    mp.command_native_async({ name = "subprocess", playback_only = false, capture_stdout = true,
        args = { "curl", "-s", "-m", "20", "-X", "POST", "-H", "Content-Type: application/json",
                 "-d", mode == "home" and '{"or_stream":true}' or "{}",
                 "http://127.0.0.1:8080/api/resume_last" } }, function(_, r)
        local out = r and r.stdout or ""
        if not out:find('"ok"') then
            mp.osd_message(out:match('"error": "([^"]*)"') or "Pas de vidéo à reprendre", 3)
        end
    end)
end

local function on_key(key)
    if key == "power" then return power_key() end
    if key == "power_menu" then   -- power maintenu : fenêtre « veille, redémarrer, éteindre » (menu QML ou tv_menu.lua)
        if menu_visible then hide_menu() end
        hide_bar()
        return mp.commandv("script-message", "streambox-power-menu")
    end
    if key == "volume_up" or key == "volume_down" then
        mp.commandv("add", "volume", key == "volume_up" and "5" or "-5")
        mp.osd_message(("Volume %d %%"):format(mp.get_property_number("volume", 0)), 1.5)
        return
    elseif key == "mute" then
        mp.commandv("cycle", "mute")
        mp.osd_message(mp.get_property_native("mute") and "Son coupé" or "Son remis", 1.5)
        return
    end
    if tvmenu_open then
        mp.commandv("script-message", "streambox-tvmenu-key", key)
        return
    end
    if tracks_open then
        tracks_key(key)
        return
    end
    if next_shown and mode == "media" and (key == "ok" or key == "back") then   -- carte « Épisode suivant »
        if key == "ok" then play_next() else hide_next(true) end
        return
    end
    if ctrl_focus and mode == "media" and key ~= "home" and key ~= "menu" then
        controls_key(key)
        return
    end
    if key == "homescreen" then   -- écran d'accueil, depuis n'importe quel mode
        if menu_visible then hide_menu() end
        if mode ~= "home" then show_home() end
        return
    elseif key == "corner" then   -- coin suivant pour le chat, menu ouvert ou non
        toggle_corner()
        if menu_visible then show_menu(keyboard_nav) else mp.osd_message("Chat : " .. CORNER_LABELS[corner], 2) end
        return
    end
    if toast_channel and (key == "ok" or key == "back") then
        local name = toast_channel
        hide_toast()
        if key == "ok" then start_channel(name) end
        return
    end
    if menu_visible then
        if DIRECTIONS[key] then
            if keyboard_nav then move_selection(DIRECTIONS[key][1], DIRECTIONS[key][2]) end
            show_menu(true)
        elseif key == "ok" then
            if keyboard_nav and items[sel] then
                items[sel].action()
                -- Streamer ou écran d'accueil choisis : le menu se ferme ; réglages du chat : il reste ouvert
                if mode == "home" or (mode == "twitch" and sel <= #streamers) then hide_menu() else show_menu(true) end
            else
                show_menu(true)
            end
        elseif key == "home" then
            open_tvmenu()
        else
            hide_menu()
        end
    elseif mode == "twitch" or mode == "home" then
        if key == "up" or key == "down" then
            zap(key == "down" and 1 or -1)
        elseif key == "ok" and mode == "twitch" then
            -- Bandeau d'infos : streamer, titre du live, « EN DIRECT » ou retard ; le menu s'ouvre par Accueil
            if bar_visible then hide_bar() else show_bar() end
        elseif key == "ok" or key == "home" then
            open_tvmenu()
        elseif key == "left" or key == "right" then
            live_seek(key == "right" and 10 or -10)
        elseif key == "back" then
            -- Une fois : retour au direct ; deux fois en 2 s : dernière vidéo de l'historique
            if mp.get_time() - back_pressed < 2 then
                back_pressed = 0
                resume_last()
            else
                back_pressed = mp.get_time()
                live_seek("live")
                mp.osd_message(mode == "home" and "Retour encore une fois pour reprendre"
                    or "Retour encore une fois pour reprendre la dernière vidéo", 2)
            end
        elseif key == "menu" then
            toggle_chat()
            mp.osd_message(chat_visible and "Chat affiché" or "Chat masqué", 2)
        end
    else   -- vidéo (lien, Jellyfin)
        if key == "ok" then
            mp.commandv("cycle", "pause")
            show_bar()
        elseif key == "left" or key == "right" then
            media_seek(key == "right" and 1 or -1)
            show_bar()
        elseif key == "up" then
            if bar_visible and not mp.get_property_native("pause") then hide_bar() else show_bar() end
        elseif key == "down" then
            if qt_ui() then   -- barre et rangée de boutons, focus sur Pause / Lecture
                ctrl_focus = 2
                show_bar()
                publish_controls()
            elseif not mp.get_property_native("pause") then
                hide_bar()
            end
        elseif key == "home" then
            open_tvmenu()
        elseif key == "menu" then
            if qt_ui() then open_tracks() show_bar() else mp.commandv("cycle", "sub") end
        elseif key == "back" then
            if mp.get_time() - back_pressed < 2 then
                back_pressed = 0
                start_channel(channel)
            else
                back_pressed = mp.get_time()
                mp.osd_message("Retour encore une fois pour revenir au stream", 2)
            end
        end
    end
end

-- Touches apprises (assistant « Configurer les touches » du menu Système) : ~/.config/stream-box/keymap.json,
-- {"nom de touche mpv": "action"}, par-dessus KEYS (une touche apprise peut aussi remplacer celle d'une autre action)
local utils = require "mp.utils"
local KEYMAP_FILE = (os.getenv("HOME") or "") .. "/.config/stream-box/keymap.json"
local bound = {}   -- noms liés, pour pouvoir tout délier et relier
local learn_key    -- assistant en cours : reçoit le nom de chaque touche à la place de on_key

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
            -- Secours : power court au relâchement, maintenu 1 s → fenêtre (ui.py envoie keydown / keyup pour ces touches)
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
        elseif not name:match("^KEY_") and not name:match("^BTN_") and not name:match("^HAT_") then   -- noms de Linux : input.py
            mp.add_forced_key_binding(name, "streambox-key-" .. name, function()
                if input_service() then return end
                if learn_key then learn_key(name) else on_key(key) end
            end, { repeatable = DIRECTIONS[key] ~= nil or key == "volume_up" or key == "volume_down" })
            bound[name] = true
        end
    end
end
bind_keys()

-- Assistant : les actions une par une ; une touche dans les 8 s l'apprend, sinon l'action garde sa touche. État dans
-- user-data/streambox/learn (dessiné par qml/KeyWizard.qml), et en message à l'écran avec mpv seul
local LEARN = { { "up", "Haut" }, { "down", "Bas" }, { "left", "Gauche" }, { "right", "Droite" }, { "ok", "OK" },
                { "back", "Retour" }, { "home", "Menu de la TV" }, { "menu", "Options (≡)" },
                { "homescreen", "Écran d'accueil" }, { "corner", "Lecture / coin du chat" }, { "power", "Power" } }
local LEARN_WAIT = 8
local learn = nil   -- { step, learned = { nom = action }, timer, last }

local function learn_publish(phase, key)
    local item = LEARN[learn.step]
    mp.set_property_native("user-data/streambox/learn", { phase = phase, step = learn.step, total = #LEARN,
        label = item and item[2] or "", key = key or "", seconds = LEARN_WAIT })
    if not qt_ui() then
        mp.osd_message(phase == "done" and "Touches enregistrées"
            or ("Touches %d/%d : appuie sur la touche pour « %s »%s"):format(learn.step, #LEARN, item[2],
                phase == "taken" and " (déjà prise)" or ""), phase == "done" and 3 or LEARN_WAIT)
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

learn_step = function()
    if learn.timer then learn.timer:kill() end
    if learn.step > #LEARN then return learn_finish() end
    learn_publish("wait")
    learn.timer = mp.add_timeout(LEARN_WAIT, function() learn.step = learn.step + 1; learn_step() end)
end

local function learn_press(name)
    if not learn or not name or name:match("^MOUSE") or name:match("^MBTN") or name:match("^WHEEL") then return end
    local now = mp.get_time()
    if now - (learn.last or 0) < 0.6 then return end   -- touche maintenue, ou rebond
    learn.last = now
    if learn.learned[name] then learn_publish("taken", name) return end   -- déjà donnée à une action précédente
    learn.learned[name] = LEARN[learn.step][1]
    learn_publish("ok", name)
    if learn.timer then learn.timer:kill() end
    learn.timer = mp.add_timeout(0.7, function() learn.step = learn.step + 1; learn_step() end)
end

mp.register_script_message("streambox-keymap-wizard", function()
    if learn then return end
    mp.commandv("script-message", "streambox-tvmenu-close")
    learn = { step = 1, learned = {} }
    learn_publish("wait")
    -- La touche OK qui a lancé l'assistant ne doit pas être prise pour « Haut »
    mp.add_timeout(0.8, function()
        learn_key = learn_press
        if not input_service() then   -- secours : touches inconnues de mpv (sinon input.py envoie tout)
            mp.add_forced_key_binding("UNMAPPED", "streambox-learn-unmapped", function(t)
                if t.event == "down" or t.event == "press" then learn_press(t.key_name) end
            end, { complex = true })
        end
        learn_step()
    end)
end)

-- Touches lues à la source par input.py : nom de Linux (KEY_SELECT…) et action ; l'assistant apprend le nom
mp.register_script_message("streambox-input", function(name, action)
    if learn_key then
        if name ~= "VIRTUAL" then learn_key(name) end   -- la télécommande virtuelle de la page n'est pas apprise
        return
    end
    if action and action ~= "" then on_key(action) end
end)

mp.register_script_message("streambox-keymap-reset", function()
    os.remove(KEYMAP_FILE)
    bind_keys()
    mp.osd_message("Touches de la télécommande par défaut", 3)
end)

-- Télécommande web (remote.py) : mêmes actions que le menu
local function from_remote(fn)
    return function(...)
        fn(...)
        if menu_visible then draw_menu() end
    end
end
mp.register_script_message("streambox-channel", from_remote(start_channel))
mp.register_script_message("streambox-toggle-chat", from_remote(toggle_chat))
mp.register_script_message("streambox-cycle-corner", from_remote(toggle_corner))
mp.register_script_message("streambox-play", play_media)
mp.register_script_message("streambox-home", from_remote(show_home))
mp.register_script_message("streambox-twitch", from_remote(function() start_channel(channel) end))
-- Réveil après une mise en veille (remote.py, resume_loop) : flux coupés, on relance la lecture en cours
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

-- Réglages numériques du chat et des sous-titres, modifiables depuis la télécommande : défaut, minimum, maximum
local NUMBERS = { chat_bg = { 60, 0, 100 },     -- opacité du fond, en %
                  chat_size = { 32, 20, 60 },   -- taille du texte, en pixels 1920x1080
                  sub_size = { 100, 50, 200 },  -- taille des sous-titres, en % de celle de mpv
                  sub_bg = { 0, 0, 100 } }      -- fond des sous-titres : opacité d'un bandeau noir, en % (0 : contour)

-- Sous-titres : taille (sub-scale) et fond (bandeau noir derrière le texte, sinon contour et ombre habituels)
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
    auto_switch()   -- réactivée pendant que la chaîne est hors ligne : on bascule tout de suite
end
mp.register_script_message("streambox-auto-switch", set_auto_switch)

-- Écran d'ambiance : quand rien ne joue (chaîne hors ligne, liste vide), horloge, date, météo et prochains lives
-- (données de remote.py dans user-data/streambox/ambient). Le contenu se déplace un peu chaque minute, pour ne pas
-- marquer l'écran de la TV.
local WEEKDAYS = { "dimanche", "lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi" }   -- os.date : 1 = dimanche
local MONTHS = { "janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
                 "novembre", "décembre" }
local ambient = mp.create_osd_overlay("ass-events")
ambient.z = -10   -- sous le menu et les notifications
local ambient_drawn = nil

-- Fond « aurore » : trois grandes taches très floues qui dérivent lentement sur un fond presque noir.
-- { couleur BGR, opacité ASS (00 = opaque), vitesse, phase }
local AURORA = { { "FF4691", "B0", 0.011, 0.0 },    -- violet Twitch
                 { "6A2A12", "A0", 0.008, 2.1 },    -- bleu nuit
                 { "7A2A5E", "B8", 0.006, 4.2 } }   -- prune

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

local function ambient_wanted()
    return (mode == "home" or (mode == "twitch" and (offline or #streamers == 0)))
        and not mp.get_property_native("video-params")
end

local function draw_ambient()
    -- Appli Qt : l'écran d'accueil est dessiné en QML (qml/AmbientScreen.qml), d'après ambient_on et status
    if mp.get_property_native("user-data/streambox/chat_ui") == "qml" then
        ambient:remove()
        return
    end
    local w, h = mp.get_osd_size()
    if not w or w == 0 then return end
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
             ass_escape(("%s %d %s"):format(WEEKDAYS[t.wday], t.day, MONTHS[t.month]))),
    }
    local wx = ambient_data.weather
    if wx then
        local parts = { wx.city, ("%d°"):format(wx.temp), wx.text, ("%d° / %d°"):format(wx.min, wx.max) }
        if (tonumber(wx.rain) or 0) >= 30 then parts[#parts + 1] = ("pluie %d %%"):format(wx.rain) end
        local kept = {}
        for _, part in ipairs(parts) do if part and part ~= "" then kept[#kept + 1] = part end end
        out[#out + 1] = line(cy + h * 0.01, fs, "D0D0D0", ass_escape(table.concat(kept, "  ·  ")))
    end
    local schedule = ambient_data.schedule or {}
    if #schedule > 0 then
        local y = cy + h * 0.10
        out[#out + 1] = line(y, math.floor(fs * 0.75), "808080", "PROCHAINS LIVES")
        for _, item in ipairs(schedule) do
            y = y + fs * 1.35
            local title = item.title or ""
            if #title > 40 then title = title:sub(1, 37) .. "…" end
            out[#out + 1] = line(y, math.floor(fs * 0.85), "FFFFFF",
                "{\\b1}" .. ass_escape(item.login) .. "{\\b0\\1c&HB0B0B0&}  ·  " .. ass_escape(item.when)
                .. (title ~= "" and ("  ·  " .. ass_escape(title)) or ""))
        end
    end
    if status_text ~= "" then
        out[#out + 1] = line(h * 0.93, math.floor(fs * 0.7), "707070", ass_escape(status_text))
    end
    -- Mode configuration (mpv seul ; l'appli Qt a son propre écran) : QR code du Wi-Fi de la box en bas à droite
    local setup = ambient_data.setup
    if setup and setup.ssid then
        out[#out + 1] = line(h * 0.72, math.floor(fs * 0.9), "FFFFFF", "{\\b1}Configuration")
        out[#out + 1] = line(h * 0.77, math.floor(fs * 0.75), "D0D0D0",
            ass_escape(("1. Wi-Fi « %s », mot de passe %s"):format(setup.ssid, setup.password)))
        out[#out + 1] = line(h * 0.81, math.floor(fs * 0.75), "D0D0D0",
            ass_escape("2. Ouvre " .. (setup.url or ""):gsub("^http://", ""):gsub("/$", "") .. " et choisis le Wi-Fi de la maison"))
    elseif setup and setup.connecting then
        out[#out + 1] = line(h * 0.77, math.floor(fs * 0.8), "FFFFFF", ass_escape("Connexion au Wi-Fi « " .. setup.connecting .. " »…"))
    end
    -- QR code de la télécommande en bas à droite, qui dérive un peu lui aussi
    local size = math.floor(h * 0.17)
    local qx = w - size - w * 0.04 + math.sin(minute * 0.9) * w * 0.012
    local qy = h - size - h * 0.11 + math.cos(minute * 0.6) * h * 0.015
    local drawing, side = qr_code(qx, qy, size)
    if drawing then
        out[#out + 1] = drawing
        out[#out + 1] = text(qx + side / 2, qy - fs * 0.7, fs * 0.8, "A0A0A0", "Télécommande")
        out[#out + 1] = text(qx + side / 2, qy + side + fs * 0.7, fs * 0.65, "909090", qr_host())
    end
    ambient.res_x, ambient.res_y = w, h
    ambient.data = table.concat(out, "\n")
    ambient:update()
end

local function update_ambient(force)
    if ambient_wanted() then
        local key = os.time() .. status_text   -- redessiné toutes les 2 s : le fond bouge en continu
        if not ambient_visible then
            ambient_visible = true
            set_loading(nil)   -- chaîne hors ligne, écran d'accueil : plus rien à attendre
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
        set_status(status_text)   -- remet le message d'état (« Chargement… ») s'il y en a un
    end
end
mp.add_periodic_timer(2, function() update_ambient(false) end)
mp.observe_property("user-data/streambox/ambient", "native", function(_, value)
    ambient_data = value or {}
    local qr = ambient_data.qr
    local setup = ambient_data.setup
    if setup and setup.ssid then qr = { url = setup.url, rows = setup.wifi_rows } end   -- QR code du Wi-Fi de la box
    local changed = (qr and qr.url) ~= (qr_data and qr_data.url)
    qr_data = qr
    if ambient_visible then update_ambient(true) end
    if changed and menu_visible then draw_menu() end
end)

mp.observe_property("user-data/streambox/live", "native", function(_, value)
    live = value or {}
    if menu_visible then draw_menu() end
    auto_switch()
end)

-- Chien de garde : direct dont l'image n'avance plus depuis FROZEN secondes alors qu'il n'est pas en pause
-- (flux bloqué, tampon coincé) → on relance la chaîne
local last_pos, last_move = nil, 0
mp.add_periodic_timer(5, function()
    local pos = mp.get_property_number("playback-time")
    if mode ~= "twitch" or offline or not pos or mp.get_property_native("pause") then
        last_pos, last_move = nil, mp.get_time()
    elseif pos ~= last_pos then
        last_pos, last_move = pos, mp.get_time()
    elseif mp.get_time() - last_move > FROZEN then
        mp.msg.warn(("direct figé depuis %d s : on relance %s"):format(FROZEN, channel))
        last_pos, last_move = nil, mp.get_time()
        start_channel(channel)
    end
end)

-- Sondages et prédictions de la chaîne regardée (relevés par remote.py dans user-data/streambox/polls) : encart en
-- haut au centre, loin des coins où se met le chat, avec le temps restant et la part de chaque choix
local events = mp.create_osd_overlay("ass-events")
local events_data, events_on = {}, true
local OUTCOME_COLORS = { BLUE = "FF7A38", PINK = "9B00F5" }   -- couleurs des prédictions sur Twitch, en BGR

local function shorten(s, n)   -- coupe à n octets sans casser un caractère UTF-8
    if #s <= n then return s end
    local cut = n
    while cut > 0 and (s:byte(cut + 1) or 0) >= 0x80 and (s:byte(cut + 1) or 0) < 0xC0 do cut = cut - 1 end
    return s:sub(1, cut) .. "…"
end

local function amount(v)   -- 16617298 → « 16,6 M »
    v = tonumber(v) or 0
    local s = v >= 1e6 and ("%.1f M"):format(v / 1e6) or v >= 1e3 and ("%.1f k"):format(v / 1e3) or tostring(v)
    return (s:gsub("%.", ","))
end

local function draw_events()
    local poll, pred = events_data.poll, events_data.prediction
    local w, h = mp.get_osd_size()
    -- Appli Qt : encart dessiné par qml/PollsOverlay.qml (user-data/streambox/polls et events)
    if qt_ui() or not events_on or mode ~= "twitch" or not (poll or pred) or not w or w == 0 then
        events:remove()
        return
    end
    local fs = math.floor(h / 40)
    local bw = math.floor(w * 0.3)
    local x, y = math.floor((w - bw) / 2), math.floor(h * 0.03)
    local pad, row_h = fs * 0.7, fs * 1.5
    local out = {}
    -- rows : { libellé, part de 0 à 1, détail à droite, couleur BGR, gagnant }
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
            rows[#rows + 1] = { c.title, share, ("%d %%  ·  %s"):format(math.floor(share * 100 + 0.5), amount(c.votes)),
                                "FF4691", poll.ended and best > 0 and c.votes == best }
        end
        local left = (poll.ends_at or 0) - now
        block("SONDAGE", poll.title, poll.ended and "Résultats" or left > 0 and clock(left) or "Dépouillement…", rows)
    end
    if pred then
        local total = 0
        for _, o in ipairs(pred.outcomes or {}) do total = total + o.points end
        local rows = {}
        for i, o in ipairs(pred.outcomes or {}) do
            if i > 5 then break end
            local share = total > 0 and o.points / total or 0
            rows[#rows + 1] = { o.title, share, ("%d %%  ·  %s points  ·  %s"):format(
                                    math.floor(share * 100 + 0.5), amount(o.points), amount(o.users)),
                                OUTCOME_COLORS[o.color] or "FF4691", o.winner }
        end
        local left = (pred.ends_at or 0) - now
        local right = pred.status == "RESOLVED" and "Résultat" or pred.status == "CANCELED" and "Annulée"
            or pred.status == "ACTIVE" and left > 0 and ("Paris : " .. clock(left)) or "Paris fermés"
        block("PRÉDICTION", pred.title, right, rows)
    end
    events.res_x, events.res_y = w, h
    events.data = table.concat(out, "\n")
    events:update()
end

mp.observe_property("user-data/streambox/polls", "native", function(_, value)
    events_data = value or {}
    draw_events()
end)
mp.add_periodic_timer(1, function()   -- temps restant
    if events_data.poll or events_data.prediction then draw_events() end
end)

-- Réglages oui / non, depuis la télécommande web : { défaut, appliqué à chaque changement et au démarrage }
-- Mode nuit : compresseur qui rapproche les passages forts des passages faibles (explosions, cris), puis limiteur
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
    if not quiet and key == "night" then mp.osd_message(on and "Mode nuit activé" or "Mode nuit désactivé", 2) end
end
mp.register_script_message("streambox-flag", set_flag)
for key, spec in pairs(FLAGS) do
    local saved = read_state(key)
    set_flag(key, saved or (spec[1] and "yes" or "no"), true)
end

-- Affichage du QR code de la télécommande : always, timed (QR_SECONDS secondes à chaque arrivée sur l'écran d'ambiance
-- et ouverture du menu), never
local function set_qr_mode(value)
    if not QR_MODES[value] then return end
    qr_mode, qr_until = value, mp.get_time() + QR_SECONDS   -- en « timed », on le montre tout de suite pour l'exemple
    write_state("qr", value)
    mp.set_property_native("user-data/streambox/qr", value)
    if ambient_visible then update_ambient(true) end
    if menu_visible then draw_menu() end
end
mp.register_script_message("streambox-qr", set_qr_mode)
set_qr_mode(read_state("qr") or "always")

-- Pas de double-clic plein écran : la box doit rester en plein écran
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
-- Reprend le dernier streamer regardé, s'il est encore dans la liste
local last = read_state("channel")
for _, name in ipairs(streamers) do
    if name == last then
        start_channel(last)
        return
    end
end
if streamers[1] then
    start_channel(streamers[1])
else
    set_status("Aucun streamer : ajoute-en un dans la télécommande web (onglet Réglages)")
end

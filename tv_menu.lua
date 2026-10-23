-- Stream Box : grand menu façon Android TV, ouvert par le bouton Menu de la télécommande (touche Accueil).
-- Onglets à gauche, contenu à droite : streamers en direct, rediffusions et clips, historique, réglages, système.
-- La vidéo continue derrière, assombrie.
--
-- Les données et les actions passent par l'API de remote.py (comme la page web) : menu, page et Home Assistant restent
-- d'accord. Les touches arrivent de stream-box.lua (script-message streambox-tvmenu-key), qui les transmet tant que
-- user-data/streambox/tvmenu est vrai. Les photos et miniatures sont des images brutes (overlay-add) préparées par
-- remote.py (/api/tvimage), posées par-dessus le dessin ASS : rien ne peut se dessiner sur elles, d'où les barres de
-- progression sous les miniatures et les images retirées quand une fenêtre d'actions s'ouvre.
local mp = require "mp"
local utils = require "mp.utils"

local API = "http://127.0.0.1:8080"
local W, H = 1920, 1080        -- coordonnées du dessin ASS, mises à l'échelle de l'écran par mpv
local IDLE_CLOSE = 90          -- secondes sans touche avant de refermer le menu (écran de TV : pas d'image fixe)
local REFRESH = 5              -- secondes entre deux relevés de l'état pendant que le menu est ouvert
local MAX_IMAGES = 48          -- overlay-add accepte les identifiants 0 à 63

local TABS = { { id = "live", label = "En direct" }, { id = "follows", label = "Suivis" },
               { id = "replays", label = "Rediffusions" }, { id = "youtube", label = "YouTube" },
               { id = "jellyfin", label = "Jellyfin" },
               { id = "history", label = "Historique" }, { id = "settings", label = "Réglages" },
               { id = "system", label = "Système" } }
local KINDS = { youtube = "YouTube", ["twitch-vod"] = "Rediffusion Twitch", ["twitch-clip"] = "Clip Twitch", link = "Lien", jellyfin = "Jellyfin" }
local CORNERS = { tl = "↖ haut gauche", tr = "↗ haut droite", br = "↘ bas droite", bl = "↙ bas gauche" }
local CORNER_ORDER = { "tl", "tr", "br", "bl" }   -- même ordre que stream-box.lua
local QR_MODES = { { "always", "Toujours" }, { "timed", "30 secondes" }, { "never", "Jamais" } }
local VIOLET, LIVE_RED = "FF4691", "5E4FFF"       -- toutes les couleurs ASS sont en BGR (bleu, vert, rouge)

local osd = mp.create_osd_overlay("ass-events")
osd.res_x, osd.res_y, osd.z = W, H, 60             -- au-dessus du chat, des sondages et des notifications
local is_open = false
local state, display, account, qr = {}, nil, nil, nil
local tab, area, index = 1, "rail", 1              -- onglet, zone qui a le focus (rail ou content), élément
local shortcut = nil                                -- En direct : raccourci sélectionné au-dessus des streamers
local pending_display = nil                         -- résolution choisie aux flèches, appliquée par OK
local pending_player = nil                          -- lecteur choisi aux flèches, appliqué par OK (il redémarre)
local poweroff_until = 0
local idle_timer, refresh_timer
local images, shown = {}, {}                        -- cache des images préparées ; overlays posés (id → signature)
local replays, rp_login = {}, nil                   -- rediffusions par streamer (/api/replays) ; streamer affiché
local rp_row, rp_sel, rp_first = 1, {}, {}          -- rangée choisie (puces, rediffusions, clips), choix, défilement
local history = nil                                 -- /api/history, relu à chaque ouverture du menu
local modal = nil                                   -- fenêtre d'actions : { title, items = { { label, ok } }, sel }
local history_loading = false
local follows, follows_loading, follows_qr = nil, false, nil   -- /api/follows ; QR code du lien d'activation
local follows_timer = nil
-- YouTube et Jellyfin (/api/youtube, /api/jellyfin) : rangées de cartes, rangée et choix par onglet. Pas de recherche
-- ici (pas de clavier à l'écran avec mpv seul) : elle se fait depuis la télécommande web
local media = { youtube = { row = 1, sel = {}, first = {} }, jellyfin = { row = 1, sel = {}, first = {} } }
local draw, close_menu


-- Outils

local function ass_escape(s)
    return (tostring(s or ""):gsub("\\", "\\\239\187\191"):gsub("{", "\\{"))
end

local function shorten(s, n)   -- coupe à n octets sans casser un caractère UTF-8
    s = tostring(s or "")
    if #s <= n then return s end
    local cut = n
    while cut > 0 and (s:byte(cut + 1) or 0) >= 0x80 and (s:byte(cut + 1) or 0) < 0xC0 do cut = cut - 1 end
    return s:sub(1, cut) .. "…"
end

local function viewers(v)
    v = tonumber(v) or 0
    return v >= 1000 and (("%.1f k"):format(v / 1000):gsub("%.", ",")) or tostring(v)
end

local function clock(t)
    t = math.max(0, math.floor(tonumber(t) or 0))
    local h, m, sec = math.floor(t / 3600), math.floor(t / 60) % 60, t % 60
    return h > 0 and ("%d:%02d:%02d"):format(h, m, sec) or ("%d:%02d"):format(m, sec)
end

local function url_encode(s)
    return (s:gsub("[^%w%-_%.~]", function(c) return ("%%%02X"):format(c:byte()) end))
end

-- Rectangle aux coins arrondis (rayon r), en coordonnées 1920x1080
local function rrect(x, y, w, h, r, color, alpha, extra)
    r = math.min(r, w / 2, h / 2)
    local k = r * 0.4477   -- 1 - 0,5523 : point de contrôle des quarts de cercle
    local p = ("m %d 0 l %d 0 b %d 0 %d %d %d %d l %d %d b %d %d %d %d %d %d l %d %d b %d %d 0 %d 0 %d l 0 %d b 0 %d %d 0 %d 0")
        :format(r, w - r, w - k, w, k, w, r, w, h - r, w, h - k, w - k, h, w - r, h, r, h, k, h, h - k, h - r, r, k, k, r)
    return ("{\\an7\\pos(%d,%d)\\bord0\\shad0%s\\1c&H%s&\\1a&H%s&\\p1}%s{\\p0}")
        :format(math.floor(x), math.floor(y), extra or "", color, alpha or "00", p)
end

-- Tailles de texte ×1,2 : à taille égale, le texte ASS est plus petit que celui de l'appli Qt (qml/), le menu a
-- ainsi le même aspect avec mpv seul
local FONT = 1.2

local function label(x, y, size, color, s, align, extra)
    return ("{\\an%d\\pos(%d,%d)\\fs%d\\bord0\\shad0\\1c&H%s&%s}%s")
        :format(align or 4, math.floor(x), math.floor(y), math.floor(size * FONT + 0.5), color, extra or "", s)
end


-- Élément sélectionné : halo violet flou, puis cadre blanc (dessinés sous l'élément, qui les recouvre au centre)
local function focus_ring(x, y, w, h, r)
    return rrect(x - 10, y - 10, w + 20, h + 20, r + 8, VIOLET, "70", "\\blur14") .. "\n"
        .. rrect(x, y, w, h, r, "FFFFFF", "00")
end

-- Texte trop long pour sa place : il défile après une pause, coupé à la largeur par \clip ; sinon affiché tel quel.
-- ASS ne sait pas mesurer un texte : largeur estimée à 0,52 em par caractère, et \clip dans tous les cas.
local MARQUEE_SPEED, MARQUEE_PAUSE, MARQUEE_GAP = 70, 1.5, 90   -- pixels par seconde, secondes, pixels
local marquee_start, marquee_active = 0, false

local function text_width(s, size)
    local n = 0
    for _ in tostring(s):gmatch("[^\128-\191]") do n = n + 1 end
    return n * size * FONT * 0.52
end

local function marquee(out, x, y, width, size, color, s, extra)
    s = tostring(s or "")
    local clip = ("\\clip(%d,%d,%d,%d)"):format(x, y - size * FONT, x + width, y + size * FONT)
    local tw = text_width(s, size)
    if tw <= width then
        out[#out + 1] = label(x, y, size, color, ass_escape(s), 4, (extra or "") .. clip)
        return
    end
    marquee_active = true
    local t = (mp.get_time() - marquee_start) % ((tw + MARQUEE_GAP) / MARQUEE_SPEED + MARQUEE_PAUSE)
    local offset = math.max(0, t - MARQUEE_PAUSE) * MARQUEE_SPEED
    for _, dx in ipairs({ 0, tw + MARQUEE_GAP }) do   -- deux copies : la seconde arrive quand la première part
        out[#out + 1] = label(x - offset + dx, y, size, color, ass_escape(s), 4, (extra or "") .. clip)
    end
end


-- API de remote.py

local function api(method, path, body, callback)
    local args = { "curl", "-s", "-m", "10", API .. path }
    if method == "POST" then
        for _, a in ipairs({ "-X", "POST", "-H", "Content-Type: application/json", "-d", utils.format_json(body or {}) }) do
            args[#args + 1] = a
        end
    end
    mp.command_native_async({ name = "subprocess", args = args, capture_stdout = true, playback_only = false },
        function(ok, res)
            local data = ok and res and res.status == 0 and utils.parse_json(res.stdout or "") or nil
            if callback then callback(data) end
        end)
end

local function refresh()
    api("GET", "/api/state", nil, function(d)
        if d and d.streamers then state = d end
        if is_open then draw() end
    end)
end

-- Action, puis relevé de l'état (mpv applique les script-messages de façon asynchrone)
local function act(name, body)
    api("POST", "/api/" .. name, body, function() mp.add_timeout(0.3, refresh) end)
end


-- Images (photos, miniatures) : préparées par remote.py à la taille exacte en pixels de l'écran.
-- { src, x, y, w, h } en coordonnées 1920x1080, et round (disque) ou radius (coins arrondis)

local function place_images(list)
    local w = mp.get_osd_size()
    local scale = (w and w > 0) and w / W or 1
    local used = {}
    for i, im in ipairs(list) do
        if i > MAX_IMAGES then break end
        local id = i - 1
        local iw, ih = math.floor(im.w * scale), math.floor(im.h * scale)
        local radius = math.floor((im.radius or 0) * scale)
        local key = ("%s|%d|%d|%s|%d"):format(im.src, iw, ih, im.round and "1" or "0", radius)
        local c = images[key]
        if c == nil then
            images[key] = "loading"
            api("GET", ("/api/tvimage?src=%s&w=%d&h=%d&round=%s&radius=%d")
                :format(url_encode(im.src), iw, ih, im.round and "1" or "0", radius), nil, function(d)
                images[key] = d and d.path and d or false   -- false : échec, on garde l'initiale dessinée dessous
                if is_open then draw() end
            end)
        elseif type(c) == "table" then
            local x, y = math.floor(im.x * scale), math.floor(im.y * scale)
            local sig = ("%s|%d|%d"):format(key, x, y)
            if shown[id] ~= sig then
                mp.commandv("overlay-add", tostring(id), tostring(x), tostring(y), c.path, "0", "bgra",
                            tostring(c.w), tostring(c.h), tostring(c.w * 4))
                shown[id] = sig
            end
            used[id] = true
        end
    end
    for id in pairs(shown) do
        if not used[id] then
            mp.commandv("overlay-remove", tostring(id))
            shown[id] = nil
        end
    end
end


-- Rediffusions et historique : chargés à la première visite de l'onglet

local function load_replays(login)
    if not login or replays[login] ~= nil then return end
    replays[login] = "loading"
    api("GET", "/api/replays?login=" .. url_encode(login), nil, function(d)
        replays[login] = d and d.vods and d or false
        if is_open then draw() end
    end)
end

local function load_history()
    api("GET", "/api/history", nil, function(d)
        history, history_loading = type(d) == "table" and d or {}, false
        if is_open then draw() end
    end)
end

-- Chaînes suivies : liste à plat, en live d'abord (triées par spectateurs côté remote.py)
local function load_follows()
    if follows_loading then return end
    follows_loading = true
    api("GET", "/api/follows", nil, function(d)
        follows_loading = false
        follows = d or { error = true }
        local p = follows.pending
        if p and p.verification_uri and not p.error then
            if not follows_qr or follows_qr.text ~= p.verification_uri then
                api("GET", "/api/qr?text=" .. url_encode(p.verification_uri), nil, function(q)
                    follows_qr = q and { text = p.verification_uri, rows = q.rows } or nil
                    if is_open then draw() end
                end)
            end
            -- En attente du code tapé sur twitch.tv/activate : on relit l'état
            if follows_timer then follows_timer:kill() end
            follows_timer = mp.add_timeout(3, function() if is_open then load_follows() end end)
        end
        if is_open then draw() end
    end)
end

local function follows_list()
    local out = {}
    for _, c in ipairs(follows and follows.live or {}) do out[#out + 1] = c end
    for _, c in ipairs(follows and follows.offline or {}) do out[#out + 1] = c end
    return out
end

local function in_list(name)
    for _, n in ipairs(state.streamers or {}) do if n == name then return true end end
    return false
end

local function play(url, from_start)
    api("POST", "/api/play", { url = url, from_start = from_start or false }, function() mp.add_timeout(0.3, refresh) end)
    close_menu()
end

-- Vidéo commencée et pas finie : reprise possible
local function resumable(position, duration, finished)
    return not finished and (tonumber(position) or 0) >= 30 and (not duration or position < duration)
end

-- Rangées de l'onglet Rediffusions : streamers, puis rediffusions et clips s'il y en a
local function replay_rows()
    local rows = { { kind = "chips", items = state.streamers or {} } }
    local d = replays[rp_login]
    if type(d) == "table" then
        if #d.vods > 0 then rows[#rows + 1] = { kind = "vods", title = "Rediffusions", items = d.vods } end
        if #d.clips > 0 then rows[#rows + 1] = { kind = "clips", title = "Clips de la semaine", items = d.clips } end
    end
    return rows
end

local function open_modal(title, items)
    modal = { title = title, items = items, sel = 1 }
end

-- Lecture d'une vidéo : reprise proposée si elle est commencée, sinon lancée tout de suite
local function choose_video(item, seconds)
    if resumable(item.position, seconds, item.finished) then
        open_modal(item.title, {
            { label = "▶  Reprendre à " .. clock(item.position), ok = function() play(item.url) end },
            { label = "↺  Depuis le début", ok = function() play(item.url, true) end },
        })
    else
        play(item.url, true)
    end
end


-- Contenu des onglets. Chaque onglet donne ses éléments sélectionnables ; le dessin et les touches s'en servent.

local function pretty_mode(m)   -- « 2560x1440@60 » → « 2560 × 1440 · 60 Hz »
    return (tostring(m):gsub("x", " × "):gsub("@", " · ")) .. " Hz"
end

local function settings_rows()
    local s = state
    local modes = { "auto" }
    for _, m in ipairs(display and display.modes or {}) do modes[#modes + 1] = m end
    local function pretty(m)
        if m == "auto" then return display and display.auto and ("Auto (" .. pretty_mode(display.auto) .. ")") or "Auto" end
        return pretty_mode(m)
    end
    local current_display = pending_display or (display and display.setting) or "auto"
    local function find(list, v)
        for i, x in ipairs(list) do if x == v then return i end end
        return 1
    end
    local qr_i = 1
    for i, m in ipairs(QR_MODES) do if m[1] == s.qr then qr_i = i end end
    return {
        { header = "Chat" },
        { label = "Chat sur la TV", toggle = s.chat_visible, ok = function() act("chat") end },
        { label = "Coin du chat", value = CORNERS[s.corner] or "", step = function(d)
            local i = find(CORNER_ORDER, s.corner)
            -- l'API ne sait qu'avancer d'un coin : trois pas en avant valent un pas en arrière
            for _ = 1, (d > 0 and 1 or 3) do act("corner") end
            s.corner = CORNER_ORDER[(i - 1 + d) % 4 + 1]
        end },
        { label = "Fond du chat", value = ("%d %%"):format(s.chat_bg or 0), step = function(d)
            s.chat_bg = math.max(0, math.min(100, (s.chat_bg or 0) + 10 * d))
            act("set", { key = "chat_bg", value = s.chat_bg })
        end },
        { label = "Taille du texte", value = ("%d px"):format(s.chat_size or 0), step = function(d)
            s.chat_size = math.max(20, math.min(60, (s.chat_size or 0) + 2 * d))
            act("set", { key = "chat_size", value = s.chat_size })
        end },
        { header = "Sous-titres" },
        { label = "Taille des sous-titres", value = ("%d %%"):format(s.sub_size or 100), step = function(d)
            s.sub_size = math.max(50, math.min(200, (s.sub_size or 100) + 10 * d))
            act("set", { key = "sub_size", value = s.sub_size })
        end },
        { label = "Fond des sous-titres", value = (s.sub_bg or 0) > 0 and ("%d %%"):format(s.sub_bg) or "Aucun",
          step = function(d)
            s.sub_bg = math.max(0, math.min(100, (s.sub_bg or 0) + 10 * d))
            act("set", { key = "sub_bg", value = s.sub_bg })
        end },
        { header = "Lecture" },
        { label = "Bascule automatique", hint = "Passer sur un streamer en live si le sien est hors ligne",
          toggle = s.auto_switch, ok = function()
            s.auto_switch = not s.auto_switch
            act("auto_switch", { enabled = s.auto_switch })
        end },
        { label = "Sondages et prédictions", hint = "En haut de la TV pendant un direct", toggle = s.events, ok = function()
            s.events = not s.events
            act("flag", { key = "events", enabled = s.events })
        end },
        { label = "Mode nuit", hint = "Sons forts atténués, voix remontées", toggle = s.night, ok = function()
            s.night = not s.night
            act("flag", { key = "night", enabled = s.night })
        end },
        { label = "Volume", value = s.mute and "muet" or ("%d %%"):format(s.volume or 0), step = function(d)
            s.volume = math.max(0, math.min(130, (s.volume or 0) + 5 * d))
            act("volume", { delta = 5 * d })
        end },
        { header = "Affichage" },
        { label = "Résolution de la TV", value = display and pretty(current_display) or "…",
          hint = pending_display and pending_display ~= display.setting and "OK pour appliquer" or nil,
          step = display and function(d)
              local i = find(modes, current_display)
              pending_display = modes[math.max(1, math.min(#modes, i + d))]
          end, ok = function()
              if pending_display and display and pending_display ~= display.setting then
                  act("display", { mode = pending_display })
                  display.setting, pending_display = pending_display, nil
                  mp.add_timeout(3, function() api("GET", "/api/display", nil, function(d)
                      if d and d.modes then display = d end
                      if is_open then draw() end
                  end) end)
              end
          end },
        { label = "QR code de la télécommande", value = QR_MODES[qr_i][2], step = function(d)
            local i = math.max(1, math.min(#QR_MODES, qr_i + d))
            s.qr = QR_MODES[i][1]
            act("qr", { mode = s.qr })
        end },
    }
end

local function system_rows()
    local s = state
    local login = account and account.login
    return {
        { label = "Compte Twitch", value = login and ("Connecté : " .. login) or "Non connecté",
          hint = login and "Pas de pub sur les chaînes où tu es abonné" or "Se connecte depuis la télécommande du téléphone" },
        -- Pour revenir à l'appli Qt (menu animé) depuis mpv seul, choisi ici ou retour automatique après des plantages
        { label = "Lecteur", value = (pending_player or s.player) == "qt" and "Appli Qt (menu animé)" or "mpv seul",
          hint = pending_player and pending_player ~= s.player and "OK pour appliquer : le lecteur redémarre"
              or (s.player == "qt" and s.player_running == "mpv" and "L'appli Qt s'est arrêtée : OK pour réessayer")
              or nil,
          step = function() pending_player = (pending_player or s.player) == "qt" and "mpv" or "qt" end,
          ok = function()
              local choice = pending_player or s.player
              if choice == s.player and not (choice == "qt" and s.player_running == "mpv") then return end
              act("player", { mode = choice })
              pending_player = nil
              close_menu()
          end },
        { label = "Éteindre la box",
          hint = mp.get_time() < poweroff_until and "Appuie encore sur OK pour éteindre" or nil,
          danger = true, ok = function()
              if mp.get_time() < poweroff_until then
                  act("poweroff")
                  close_menu()
              else
                  poweroff_until = mp.get_time() + 4
                  mp.add_timeout(4.1, function() if is_open then draw() end end)
              end
          end },
    }
end

-- Lignes sélectionnables d'une liste (les titres de section ne le sont pas)
local function selectable(rows)
    local out = {}
    for i, r in ipairs(rows) do if not r.header then out[#out + 1] = i end end
    return out
end

local LIVE_COLS = 4

-- Raccourcis en haut de l'onglet En direct : écran d'accueil, et retour au stream quand on n'y est pas
local function shortcuts()
    local list = { { label = "⌂  Écran d'accueil", current = state.mode == "home", ok = function()
        act("home")
        close_menu()
    end } }
    if state.mode ~= "twitch" and state.channel then
        list[#list + 1] = { label = "▶  Reprendre " .. state.channel, ok = function()
            act("twitch")
            close_menu()
        end }
    end
    return list
end


-- Dessin

local function draw_rail(out)
    out[#out + 1] = rrect(0, 0, 400, H, 0, "10070B", "30")
    out[#out + 1] = rrect(56, 62, 52, 52, 14, "F7F2F4", "00")   -- logo neutre : tuile blanche, triangle anthracite
    out[#out + 1] = "{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H1C1517&\\p1}m 76 77 l 93 88 76 99{\\p0}"   -- ▶ dessiné
    out[#out + 1] = label(126, 88, 36, "FFFFFF", "Stream Box", 4, "\\b1")
    for i, t in ipairs(TABS) do
        local y = 206 + (i - 1) * 76   -- 9 onglets entre le logo et « En cours sur la TV »
        if i == tab and area == "rail" then
            out[#out + 1] = rrect(40, y, 320, 64, 32, "FFFFFF", "00")
            out[#out + 1] = label(78, y + 32, 30, "20101A", ass_escape(t.label), 4, "\\b1")
        else
            if i == tab then
                out[#out + 1] = rrect(40, y, 320, 64, 32, "FFFFFF", "E6")
                out[#out + 1] = rrect(60, y + 26, 12, 12, 6, VIOLET, "00")   -- onglet en cours : point dans la pastille
            end
            out[#out + 1] = label(i == tab and 88 or 78, y + 32, 30, i == tab and "FFFFFF" or "C2AFB4", ass_escape(t.label), 4,
                                  i == tab and "\\b1" or "")
        end
    end
    local live = state.live or {}
    local now = state.mode == "twitch" and state.channel
        and (state.channel .. "  ·  " .. (live[state.channel] and live[state.channel].title or "hors ligne"))
        or state.mode == "media" and (state.title or "Vidéo") or nil
    if now then
        out[#out + 1] = label(56, H - 172, 21, "C09FA9", "EN COURS SUR LA TV", 4, "\\b1\\fsp2")
        marquee(out, 56, H - 130, 310, 28, "FFFFFF", now)
    end
    out[#out + 1] = label(56, H - 60, 24, "A0858A",
        "▲▼◀▶ se déplacer   ·   OK valider   ·   Retour revenir   ·   Menu fermer", 4)
end

local function draw_header(out, title, subtitle)
    out[#out + 1] = label(460, 100, 52, "FFFFFF", ass_escape(title), 4, "\\b1")
    if subtitle then out[#out + 1] = label(460, 158, 32, "C2AFB4", ass_escape(subtitle), 4) end
    out[#out + 1] = label(W - 80, 100, 40, "FFFFFF", os.date("%H:%M"), 6)
    local wx = (mp.get_property_native("user-data/streambox/ambient") or {}).weather
    if wx and wx.temp then
        out[#out + 1] = label(W - 215, 102, 32, "C2AFB4", ass_escape(("%d°  %s"):format(wx.temp, wx.text or "")), 6)
    end
end

-- Carte de streamer (En direct, Suivis) : photo (anneau rouge en live), nom, spectateurs, jeu
local SCARD_W, SCARD_H, SCARD_GAP = 330, 150, 26

local function streamer_card(out, imgs, x, y, name, avatar, info, focused, current)
    local cw, ch = SCARD_W, SCARD_H
    if focused then out[#out + 1] = focus_ring(x - 6, y - 6, cw + 12, ch + 12, 26) end
    -- Streamer en cours : carte teintée de violet (un badge chevaucherait le nom)
    out[#out + 1] = rrect(x, y, cw, ch, 22, current and "8A3C6B" or (focused and "4E2C3A" or "34202A"),
                          (focused or current) and "00" or "30")
    -- Photo : disque de couleur avec l'initiale, recouvert par l'image quand elle est prête
    local ax, ay, as = x + 22, y + 30, 90
    if info then out[#out + 1] = rrect(ax - 5, ay - 5, as + 10, as + 10, (as + 10) / 2, LIVE_RED, "00") end
    out[#out + 1] = rrect(ax, ay, as, as, as / 2, "5C3D4A", "00")
    out[#out + 1] = label(ax + as / 2, ay + as / 2, 40, "E0C8D0", ass_escape(name:sub(1, 1):upper()), 5, "\\b1")
    if avatar then imgs[#imgs + 1] = { src = avatar, x = ax, y = ay, w = as, h = as, round = true } end
    local tx = ax + as + 20
    if focused then
        marquee(out, tx, y + 40, x + cw - tx - 16, 34, "FFFFFF", name, "\\b1")
    else
        out[#out + 1] = label(tx, y + 40, 34, "FFFFFF", ass_escape(shorten(name, 10)), 4, "\\b1")
    end
    if info then
        out[#out + 1] = label(tx, y + 82, 27, LIVE_RED, "● " .. viewers(info.viewers), 4, "\\b1")
        if focused then
            marquee(out, tx, y + 116, x + cw - tx - 16, 25, "C2AFB4", info.game or info.title)
        else
            out[#out + 1] = label(tx, y + 116, 25, "C2AFB4", ass_escape(shorten(info.game or info.title or "", 12)), 4)
        end
    else
        out[#out + 1] = label(tx, y + 82, 27, "A0858A", "Hors ligne", 4)
    end
end

local function draw_live(out, imgs)
    local list, live = state.streamers or {}, state.live or {}
    local n_live = 0
    for _, name in ipairs(list) do if live[name] then n_live = n_live + 1 end end
    draw_header(out, "En direct", n_live == 0 and "Aucun streamer de la liste n'est en live"
        or n_live == 1 and "1 streamer en live" or (n_live .. " streamers en live"))
    if #list == 0 then
        out[#out + 1] = label(460, 280, 34, "C2AFB4", "La liste est vide : ajoute des streamers depuis la télécommande web.")
        return
    end
    local cw, ch, gap, x0, y0 = SCARD_W, SCARD_H, SCARD_GAP, 460, 310
    local rows_visible = 3
    local sx = x0
    for i, sc in ipairs(shortcuts()) do
        local focused = area == "content" and shortcut == i
        local sw = 72 + #sc.label * 15
        if focused then out[#out + 1] = focus_ring(sx - 5, 205, sw + 10, 74, 37) end
        out[#out + 1] = rrect(sx, 210, sw, 64, 32, sc.current and VIOLET or (focused and "4E2C3A" or "34202A"),
                              (focused or sc.current) and "00" or "30")
        out[#out + 1] = label(sx + sw / 2, 242, 31, "FFFFFF", ass_escape(sc.label), 5, sc.current and "\\b1" or "")
        sx = sx + sw + 20
    end
    local focus_row = area == "content" and not shortcut and math.floor((index - 1) / LIVE_COLS) or 0
    local first_row = math.max(0, focus_row - rows_visible + 1)
    for i, name in ipairs(list) do
        local row, col = math.floor((i - 1) / LIVE_COLS) - first_row, (i - 1) % LIVE_COLS
        if row >= 0 and row < rows_visible then
            streamer_card(out, imgs, x0 + col * (cw + gap), y0 + row * (ch + gap), name, (state.avatars or {})[name],
                          live[name], area == "content" and not shortcut and i == index,
                          state.mode == "twitch" and state.channel == name)
        end
    end
    -- Titre du live sélectionné, en entier, sous la grille
    local name = area == "content" and not shortcut and list[index]
    local info = name and live[name]
    if info and info.title then
        marquee(out, 460, y0 + rows_visible * (ch + gap) + 24, W - 500, 31, "E0C8D0", name .. "  ·  " .. info.title)
    end
end

-- Carte vidéo : miniature (image posée par-dessus un fond), barre de progression dessous, titre, ligne d'infos
local CARD_W, CARD_IMG_H, CARD_H, CARD_GAP = 330, 186, 302, 26

local function video_card(out, imgs, x, y, item, focused, meta, progress)
    if focused then out[#out + 1] = focus_ring(x - 6, y - 6, CARD_W + 12, CARD_IMG_H + 12, 22) end
    out[#out + 1] = rrect(x, y, CARD_W, CARD_IMG_H, 16, "34202A", "00")
    out[#out + 1] = "{\\an5\\pos(" .. math.floor(x + CARD_W / 2) .. "," .. math.floor(y + CARD_IMG_H / 2)
        .. ")\\fs60\\bord0\\shad0\\1c&H68505A&\\p1}m -14 -20 l 22 0 -14 20{\\p0}"   -- ▶ en attendant l'image
    if item.thumb then
        imgs[#imgs + 1] = { src = item.thumb, x = x, y = y, w = CARD_W, h = CARD_IMG_H, radius = 16 }
    end
    if progress and progress > 0 then
        out[#out + 1] = rrect(x, y + CARD_IMG_H + 10, CARD_W, 6, 3, "5C3D4A", "00")
        out[#out + 1] = rrect(x, y + CARD_IMG_H + 10, math.max(6, CARD_W * math.min(1, progress)), 6, 3, VIOLET, "00")
    end
    if focused then
        marquee(out, x, y + CARD_IMG_H + 46, CARD_W, 33, "FFFFFF", item.title, "\\b1")
    else
        out[#out + 1] = label(x, y + CARD_IMG_H + 46, 33, "EADAE0", ass_escape(shorten(item.title or "", 16)), 4)
    end
    if meta then out[#out + 1] = label(x, y + CARD_IMG_H + 88, 27, "C09FA9", ass_escape(shorten(meta, 26)), 4) end
end

-- Premier élément visible d'une rangée qui défile, pour garder sel à l'écran
local function scroll(first, sel, visible)
    first = first or 1
    if sel < first then first = sel end
    if sel > first + visible - 1 then first = sel - visible + 1 end
    return math.max(1, first)
end

local function date_fr(iso)
    local y, m, d = tostring(iso or ""):match("(%d+)-(%d+)-(%d+)")
    local months = { "janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc." }
    return d and ("%d %s"):format(tonumber(d), months[tonumber(m)]) or ""
end

local function draw_replays(out, imgs)
    local rows = replay_rows()
    rp_row = math.min(rp_row, #rows)
    local d = replays[rp_login]
    draw_header(out, "Rediffusions", d == "loading" and ((rp_login or "") .. " · chargement…")
        or d == false and "Twitch injoignable pour l'instant"
        or (type(d) == "table" and #rows == 1) and ((rp_login or "") .. " : rien cette semaine")
        or ((rp_login or "") .. " · rediffusions et clips de la semaine"))
    -- Puces des streamers
    local chips = rows[1].items
    local csel = rp_sel.chips or 1
    local x, focused_row = 460, area == "content" and rp_row or nil
    local function chip_w(name) return 96 + #name * 17 end
    -- Défilement à la largeur : la puce choisie et celle du streamer affiché doivent tenir dans la ligne
    local keep = focused_row == 1 and csel or 1
    for i, name in ipairs(chips) do if focused_row ~= 1 and name == rp_login then keep = i end end
    local first = math.min(rp_first.chips or 1, keep)
    local function fits(from)
        local used = 0
        for i = from, keep do used = used + chip_w(chips[i]) + 16 end
        return 460 + used <= W - 40
    end
    while first < keep and not fits(first) do first = first + 1 end
    rp_first.chips = first
    for i = rp_first.chips, #chips do
        local name = chips[i]
        local cw = chip_w(name)
        if x + cw > W - 40 then break end
        local focused = focused_row == 1 and i == csel
        local current = name == rp_login
        if focused then out[#out + 1] = focus_ring(x - 5, 185, cw + 10, 74, 37) end
        out[#out + 1] = rrect(x, 190, cw, 64, 32, current and VIOLET or (focused and "4E2C3A" or "34202A"),
                              (current or focused) and "00" or "30")
        out[#out + 1] = rrect(x + 10, 198, 48, 48, 24, "5C3D4A", "00")
        if state.avatars and state.avatars[name] then
            imgs[#imgs + 1] = { src = state.avatars[name], x = x + 10, y = 198, w = 48, h = 48, round = true }
        end
        out[#out + 1] = label(x + 70, 222, 28, "FFFFFF", ass_escape(name), 4, current and "\\b1" or "")
        x = x + cw + 16
    end
    -- Rediffusions et clips
    local y = 300
    for r = 2, #rows do
        local row = rows[r]
        out[#out + 1] = label(462, y, 25, "C09FA9", ass_escape(row.title:upper()), 4, "\\b1\\fsp2")
        local sel = rp_sel[row.kind] or 1
        rp_first[row.kind] = scroll(rp_first[row.kind], sel, 4)
        for i = rp_first[row.kind], math.min(#row.items, rp_first[row.kind] + 3) do
            local item = row.items[i]
            local cx = 460 + (i - rp_first[row.kind]) * (CARD_W + CARD_GAP)
            local meta = row.kind == "vods" and (date_fr(item.date) .. " · " .. clock(item.seconds))
                or (clock(item.seconds) .. " · " .. viewers(item.views) .. " vues")
            if item.finished then meta = meta .. " · vu" end
            video_card(out, imgs, cx, y + 26, item, focused_row == r and i == sel, meta,
                       item.finished and 1 or (item.position and item.seconds and item.position / item.seconds) or 0)
        end
        if #row.items > rp_first[row.kind] + 3 then
            out[#out + 1] = label(W - 40, y + 26 + CARD_IMG_H / 2, 40, "C09FA9", "›", 6)
        end
        y = y + CARD_H + 34
    end
end

-- YouTube et Jellyfin

local function load_media(id)
    local m = media[id]
    if m.loading or m.data then return end
    m.loading = true
    api("GET", "/api/" .. id, nil, function(d)
        m.loading, m.data = false, d or { error = true }
        if is_open then draw() end
    end)
end

local function media_rows(id)
    local m, rows = media[id], {}
    local d = m.data or {}
    if id == "youtube" then
        for _, c in ipairs(d.channels or {}) do
            rows[#rows + 1] = { key = c.id, title = c.name, items = c.videos or {} }
        end
    elseif d.configured then
        if m.series then rows[#rows + 1] = { key = "series", title = m.series.name .. " · épisodes", items = m.series.episodes or {} } end
        if #(d.resume or {}) > 0 then rows[#rows + 1] = { key = "resume", title = "Reprendre", items = d.resume } end
        if #(d.nextup or {}) > 0 then rows[#rows + 1] = { key = "nextup", title = "Prochains épisodes", items = d.nextup } end
        for _, l in ipairs(d.libraries or {}) do
            rows[#rows + 1] = { key = "lib:" .. l.id, title = l.name .. " · ajouts récents", items = l.items or {} }
        end
    end
    return rows
end

local function days_ago(iso)
    local y, mo, d = tostring(iso or ""):match("(%d+)-(%d+)-(%d+)")
    if not d then return "" end
    local n = math.floor((os.time() - os.time({ year = y, month = mo, day = d, hour = 12 })) / 86400)
    return n <= 0 and "aujourd'hui" or n == 1 and "hier" or n < 7 and ("il y a %d j"):format(n)
        or n < 31 and ("il y a %d sem."):format(math.floor(n / 7)) or date_fr(iso)
end

local function hm(t)
    t = tonumber(t) or 0
    local h, m = math.floor(t / 3600), math.floor(t / 60) % 60
    return h > 0 and ("%d h %02d"):format(h, m) or ("%d min"):format(m)
end

local function media_meta(id, it)
    local parts = {}
    local function add(v) if v and v ~= "" then parts[#parts + 1] = tostring(v) end end
    if id == "youtube" then
        add(days_ago(it.date))
        if it.views then add(viewers(it.views) .. " vues") end
    elseif it.type == "Series" then
        add((it.unplayed or 0) > 0 and (it.unplayed .. " à voir") or "Série")
        add(it.year)
    elseif it.episode then
        add(it.episode)
    else
        add(it.year)
        if it.seconds then add(hm(it.seconds)) end
    end
    local meta = table.concat(parts, " · ")
    return it.finished and (meta .. " · vu") or meta
end

local function draw_media(out, imgs, id)
    local m, rows = media[id], media_rows(id)
    local d = m.data
    local subtitle
    if not d then subtitle = "Chargement…"
    elseif d.error then subtitle = (id == "youtube" and "YouTube" or "Jellyfin") .. " injoignable pour l'instant"
    elseif id == "youtube" then
        subtitle = #rows > 0 and (#rows .. (#rows == 1 and " chaîne" or " chaînes") .. " · recherche depuis la télécommande web")
            or "Ajoute des chaînes depuis la télécommande web (Réglages → Chaînes YouTube)"
    else
        subtitle = d.configured and ((d.server or "Jellyfin") .. " · recherche depuis la télécommande web")
            or "Jellyfin n'est pas associé à la box (« Lire sur… » depuis l'appli Jellyfin)"
    end
    draw_header(out, id == "youtube" and "YouTube" or "Jellyfin", subtitle)
    m.row = math.max(1, math.min(m.row, #rows))
    local first_row = math.max(1, m.row - 1)   -- deux rangées à l'écran
    local y = 230
    for r = first_row, math.min(#rows, first_row + 1) do
        local row = rows[r]
        local focused_row = area == "content" and r == m.row
        out[#out + 1] = label(462, y, 25, "C09FA9", ass_escape(row.title:upper()), 4, "\\b1\\fsp2")
        local sel = math.min(m.sel[row.key] or 1, math.max(1, #row.items))
        m.first[row.key] = scroll(m.first[row.key], sel, 4)
        local f = m.first[row.key]
        for i = f, math.min(#row.items, f + 3) do
            local it = row.items[i]
            local title = id == "jellyfin" and it.episode and it.title or it.title
            video_card(out, imgs, 460 + (i - f) * (CARD_W + CARD_GAP), y + 26, { title = title, thumb = it.thumb },
                       focused_row and i == sel, media_meta(id, it),
                       it.finished and 1 or (it.position and it.seconds and it.seconds > 0 and it.position / it.seconds) or 0)
        end
        if #row.items == 0 then out[#out + 1] = label(462, y + 90, 28, "A0858A", "Rien ici", 4) end
        if #row.items > f + 3 then out[#out + 1] = label(W - 40, y + 26 + CARD_IMG_H / 2, 40, "C09FA9", "›", 6) end
        y = y + CARD_H + 34
    end
end

local function jellyfin_play(it, from_start)
    api("POST", "/api/jellyfin_play", { id = it.id, from_start = from_start or false }, function() mp.add_timeout(0.3, refresh) end)
    close_menu()
end

local function jellyfin_series(it)
    local m = media.jellyfin
    m.series = { id = it.series, name = it.title, episodes = nil }
    m.row = 1
    api("GET", "/api/jellyfin_series?id=" .. url_encode(it.series), nil, function(d)
        if m.series and m.series.id == it.series then
            m.series.episodes = d and d.episodes or {}
            m.sel.series, m.first.series = (d and d.first or 0) + 1, nil
        end
        if is_open then draw() end
    end)
end

local function jellyfin_choose(it)
    if it.type == "Series" or it.type == "Season" then return jellyfin_series(it) end
    local items = {}
    if resumable(it.position, it.seconds, it.finished) then
        items[#items + 1] = { label = "▶  Reprendre à " .. clock(it.position), ok = function() jellyfin_play(it) end }
        items[#items + 1] = { label = "↺  Depuis le début", ok = function() jellyfin_play(it, true) end }
    else
        items[#items + 1] = { label = it.finished and "↺  Revoir" or "▶  Lire", ok = function() jellyfin_play(it, true) end }
    end
    if it.type == "Episode" and it.series then
        items[#items + 1] = { label = "☰  Tous les épisodes", ok = function() jellyfin_series(it) end }
    end
    open_modal(it.episode and (it.title .. " · " .. it.episode) or it.title, items)
end

local FOLLOW_ROWS = 4

local function draw_qr_rows(out, rows, x, y, size)
    local n = #(rows or {})
    local m = n > 0 and math.floor(size / (n + 4)) or 0
    if m < 2 then return end
    local paths = {}
    for r, row in ipairs(rows) do
        local c = 1
        while c <= n do
            if row:sub(c, c) == "1" then
                local s0 = c
                while c <= n and row:sub(c, c) == "1" do c = c + 1 end
                paths[#paths + 1] = ("m %d %d l %d %d %d %d %d %d"):format((s0 + 1) * m, (r + 1) * m, (c + 1) * m,
                    (r + 1) * m, (c + 1) * m, (r + 2) * m, (s0 + 1) * m, (r + 2) * m)
            else
                c = c + 1
            end
        end
    end
    local side = (n + 4) * m
    out[#out + 1] = rrect(x, y, side, side, 18, "E8E8E8", "00")
    out[#out + 1] = ("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H101010&\\1a&H00&\\p1}%s{\\p0}")
        :format(x, y, table.concat(paths, " "))
    return side
end

local function draw_follows(out, imgs)
    local f = follows
    if f == nil then
        draw_header(out, "Suivis", "Chargement…")
        return
    end
    if f.error then
        draw_header(out, "Suivis", "Twitch injoignable pour l'instant")
        return
    end
    if not f.configured then
        draw_header(out, "Suivis", "Tes chaînes suivies sur Twitch")
        out[#out + 1] = label(460, 280, 34, "FFFFFF", "Pour les afficher, la box a besoin de ta propre appli Twitch.")
        out[#out + 1] = label(460, 336, 28, "C2AFB4", "Télécommande web → Réglages → Chaînes suivies : tout y est expliqué.")
        return
    end
    if not f.authorized then
        local p = f.pending
        draw_header(out, "Suivis", "Autorise la box à lire tes chaînes suivies (lecture seule)")
        if p and p.user_code and not p.error then
            out[#out + 1] = label(460, 290, 34, "FFFFFF", "Sur ton téléphone, ouvre twitch.tv/activate et tape :")
            out[#out + 1] = label(460, 400, 96, "FFFFFF", ass_escape(p.user_code), 4, "\\b1\\fsp12")
            out[#out + 1] = label(460, 500, 28, "C2AFB4", "ou scanne le QR code. La TV se met à jour toute seule.")
            if follows_qr and follows_qr.rows then draw_qr_rows(out, follows_qr.rows, 1400, 240, 360) end
        else
            if p and p.error then
                out[#out + 1] = label(460, 250, 28, "8F8FFF", ass_escape("Autorisation refusée : " .. p.error))
            end
            local focused = area == "content"
            if focused then out[#out + 1] = focus_ring(455, 295, 450, 84, 42) end
            out[#out + 1] = rrect(460, 300, 440, 74, 37, VIOLET, "00")
            out[#out + 1] = label(680, 337, 32, "FFFFFF", "Autoriser la box", 5, "\\b1")
        end
        return
    end
    local list = follows_list()
    draw_header(out, "Suivis", (#f.live == 0 and "Personne en live" or (#f.live .. " en live")) .. "  ·  "
        .. (#list .. " chaînes suivies"))
    local focus_row = area == "content" and math.floor((index - 1) / LIVE_COLS) or 0
    local first_row = math.max(0, focus_row - FOLLOW_ROWS + 1)
    for i, c in ipairs(list) do
        local row, col = math.floor((i - 1) / LIVE_COLS) - first_row, (i - 1) % LIVE_COLS
        if row >= 0 and row < FOLLOW_ROWS then
            streamer_card(out, imgs, 460 + col * (SCARD_W + SCARD_GAP), 210 + row * (SCARD_H + SCARD_GAP), c.login,
                          c.avatar, c.viewers and c or nil, area == "content" and i == index,
                          state.mode == "twitch" and state.channel == c.login)
        end
    end
    if math.ceil(#list / LIVE_COLS) > first_row + FOLLOW_ROWS then
        out[#out + 1] = label(460 + 2 * (SCARD_W + SCARD_GAP) - SCARD_GAP / 2,
                              210 + FOLLOW_ROWS * (SCARD_H + SCARD_GAP) + 10, 26, "C09FA9", "▼", 5)
    end
end

local HIST_COLS, HIST_ROWS = 4, 2

local function draw_history(out, imgs)
    local list = history or {}
    draw_header(out, "Historique", history == nil and "Chargement…"
        or #list == 0 and "Les vidéos lancées sur la TV s'afficheront ici"
        or (#list == 1 and "1 vidéo" or (#list .. " vidéos")) .. " · OK pour reprendre ou retirer")
    local focus_row = area == "content" and math.floor((index - 1) / HIST_COLS) or 0
    local first_row = math.max(0, focus_row - HIST_ROWS + 1)
    for i, e in ipairs(list) do
        local row, col = math.floor((i - 1) / HIST_COLS) - first_row, (i - 1) % HIST_COLS
        if row >= 0 and row < HIST_ROWS then
            local started = resumable(e.position, e.duration, e.finished)
            local meta = KINDS[e.kind] or ""
            if e.finished then
                meta = meta .. " · vu"
            elseif e.duration and e.duration > 0 then
                meta = meta .. " · " .. clock(e.position) .. " / " .. clock(e.duration)
            end
            video_card(out, imgs, 460 + col * (CARD_W + CARD_GAP), 210 + row * (CARD_H + 30), e,
                       area == "content" and i == index, meta,
                       e.finished and 1 or (started and e.duration and e.duration > 0 and e.position / e.duration) or 0)
        end
    end
    if math.ceil(#list / HIST_COLS) > first_row + HIST_ROWS then
        out[#out + 1] = label(460 + 2 * (CARD_W + CARD_GAP) - CARD_GAP / 2, 210 + HIST_ROWS * (CARD_H + 30), 26,
                              "C09FA9", "▼", 5)
    end
end

local function draw_modal(out)
    local n = #modal.items
    local mw, mh = 820, 150 + n * 92
    local mx, my = (W - mw) / 2, (H - mh) / 2
    out[#out + 1] = rrect(0, 0, W, H, 0, "0A0305", "50")
    out[#out + 1] = rrect(mx, my, mw, mh, 28, "2C1821", "00")
    marquee(out, mx + 44, my + 62, mw - 88, 35, "FFFFFF", modal.title, "\\b1")
    for i, it in ipairs(modal.items) do
        local by = my + 112 + (i - 1) * 92
        local focused = i == modal.sel
        out[#out + 1] = rrect(mx + 30, by, mw - 60, 76, 38, focused and "FFFFFF" or "3F2833", "00")
        out[#out + 1] = label(mx + 70, by + 38, 33, focused and "20101A" or (it.danger and "8F8FFF" or "FFFFFF"),
                              ass_escape(it.label), 4, focused and "\\b1" or "")
    end
end

local function draw_rows(out, rows, title, subtitle, width)
    draw_header(out, title, subtitle)
    local sel = selectable(rows)
    local focused_row = area == "content" and sel[index] or nil
    local x, y, rw = 460, 210, width or 980
    -- Défilement : on part de la ligne qui garde l'élément choisi dans les 760 px disponibles
    local heights = {}
    for i, r in ipairs(rows) do heights[i] = r.header and 68 or (r.hint and 110 or 84) end
    local first, used = 1, 0
    if focused_row then
        for i = focused_row, 1, -1 do
            used = used + heights[i] + 10
            if used > 780 then break end
            first = i
        end
    end
    for i = first, #rows do
        local r = rows[i]
        if y + heights[i] > H - 60 then break end
        if r.header then
            out[#out + 1] = label(x + 4, y + 42, 25, "C09FA9", ass_escape(r.header:upper()), 4, "\\b1\\fsp2")
        else
            local focused = i == focused_row
            local h = heights[i]
            if focused then out[#out + 1] = focus_ring(x - 5, y - 5, rw + 10, h + 10, 24) end
            out[#out + 1] = rrect(x, y, rw, h, 20, focused and "4E2C3A" or "34202A", focused and "00" or "30")
            local ty = r.hint and y + 38 or y + h / 2
            out[#out + 1] = label(x + 30, ty, 34, r.danger and "8F8FFF" or "FFFFFF", ass_escape(r.label), 4)
            if r.hint then out[#out + 1] = label(x + 30, y + 78, 25, "C2AFB4", ass_escape(r.hint), 4) end
            if r.toggle ~= nil then   -- interrupteur dessiné
                local sx, sy = x + rw - 110, y + h / 2 - 20
                out[#out + 1] = rrect(sx, sy, 76, 40, 20, r.toggle and VIOLET or "68505A", "00")
                out[#out + 1] = rrect(sx + (r.toggle and 40 or 4), sy + 4, 32, 32, 16, "FFFFFF", "00")
            elseif r.value then
                local arrows = focused and r.step
                out[#out + 1] = label(x + rw - 30, y + h / 2, 32, "F4E2E8",
                                      (arrows and "◀  " or "") .. ass_escape(r.value) .. (arrows and "  ▶" or ""), 6)
            end
        end
        y = y + heights[i] + 10
    end
end

local function draw_qr(out, x, y, size)
    local rows = qr and qr.rows or {}
    local n = #rows
    local m = n > 0 and math.floor(size / (n + 4)) or 0
    if m < 2 then return end
    local paths = {}
    for r, row in ipairs(rows) do
        local c = 1
        while c <= n do
            if row:sub(c, c) == "1" then
                local s0 = c
                while c <= n and row:sub(c, c) == "1" do c = c + 1 end
                paths[#paths + 1] = ("m %d %d l %d %d %d %d %d %d"):format((s0 + 1) * m, (r + 1) * m, (c + 1) * m,
                    (r + 1) * m, (c + 1) * m, (r + 2) * m, (s0 + 1) * m, (r + 2) * m)
            else
                c = c + 1
            end
        end
    end
    local side = (n + 4) * m
    out[#out + 1] = rrect(x, y, side, side, 18, "E8E8E8", "00")
    out[#out + 1] = ("{\\an7\\pos(%d,%d)\\bord0\\shad0\\1c&H101010&\\1a&H00&\\p1}%s{\\p0}"):format(x, y, table.concat(paths, " "))
    return side
end

function draw()
    if not is_open then return end
    marquee_active = false
    -- Voile sur la vidéo ; opaque sans vidéo, pour cacher l'écran d'ambiance (horloge, QR code)
    local out = { rrect(0, 0, W, H, 0, "12060A", mp.get_property_native("video-params") and "1C" or "00") }
    out[#out + 1] = "{\\an7\\pos(0,0)\\bord0\\shad0\\1c&HFF4691&\\1a&HD8&\\blur120\\p1}m 1400 -200 l 2200 -200 2200 500 1400 500{\\p0}"
    local imgs = {}
    draw_rail(out)
    local id = TABS[tab].id
    if id == "live" then
        draw_live(out, imgs)
    elseif id == "follows" then
        if follows == nil then load_follows() end
        draw_follows(out, imgs)
    elseif id == "replays" then
        rp_login = rp_login or state.channel or (state.streamers or {})[1]
        load_replays(rp_login)
        draw_replays(out, imgs)
    elseif id == "youtube" or id == "jellyfin" then
        load_media(id)
        draw_media(out, imgs, id)
    elseif id == "history" then
        if history == nil and not history_loading then
            history_loading = true
            load_history()
        end
        draw_history(out, imgs)
    elseif id == "settings" then
        draw_rows(out, settings_rows(), "Réglages", "◀ ▶ pour changer une valeur")
    else
        draw_rows(out, system_rows(), "Système", nil, 820)
        -- QR code de la télécommande web : pour tout ce qui demande de taper du texte
        local side = draw_qr(out, 1340, 230, 300)
        if side then
            out[#out + 1] = label(1340, 230 + side + 44, 30, "FFFFFF", "Télécommande sur le téléphone", 4, "\\b1")
            out[#out + 1] = label(1340, 230 + side + 86, 25, "C2AFB4", "Lien, streamer, compte Twitch…", 4)
            out[#out + 1] = label(1340, 230 + side + 124, 25, "C2AFB4",
                                  ass_escape((qr.url or ""):gsub("^https?://", ""):gsub("/$", "")), 4)
        end
    end
    if modal then
        draw_modal(out)
        imgs = {}   -- les images passeraient par-dessus la fenêtre
    end
    osd.data = table.concat(out, "\n")
    osd:update()
    place_images(imgs)
end


-- Ouverture, fermeture, touches

local function arm_idle()
    if idle_timer then idle_timer:kill() end
    idle_timer = mp.add_timeout(IDLE_CLOSE, function() close_menu() end)
end

function close_menu()
    if not is_open then return end
    is_open = false
    pending_display, poweroff_until, modal = nil, 0, nil
    osd:remove()
    place_images({})
    if idle_timer then idle_timer:kill() end
    if refresh_timer then refresh_timer:kill() end
    mp.set_property_native("user-data/streambox/tvmenu", false)
end

local function open_menu()
    if is_open then return end
    is_open = true
    -- Le menu rouvre sur le dernier onglet (rangée et carte gardées pour YouTube et Jellyfin), données relues
    area, index, shortcut = TABS[tab].id == "follows" and "rail" or "content", 1, nil
    media.youtube.data, media.jellyfin.data = nil, nil
    -- Relus à chaque ouverture : l'historique change, remote.py garde les rediffusions 5 min en cache
    history, history_loading, replays, rp_login, rp_row, rp_sel, rp_first = nil, false, {}, nil, 1, {}, {}
    follows = nil
    -- Focus de départ : le streamer regardé
    for i, name in ipairs(state.streamers or {}) do
        if name == state.channel then index = i end
    end
    mp.set_property_native("user-data/streambox/tvmenu", true)
    local amb = mp.get_property_native("user-data/streambox/ambient") or {}
    qr = amb.qr
    draw()
    refresh()
    api("GET", "/api/display", nil, function(d) if d and d.modes then display = d end end)
    api("GET", "/api/account", nil, function(d) account = d end)
    arm_idle()
    refresh_timer = mp.add_periodic_timer(REFRESH, refresh)
end

local function content_count()
    local id = TABS[tab].id
    if id == "live" or id == "replays" then return #(state.streamers or {}) end
    if id == "follows" then
        if not follows or not follows.configured then return 0 end
        return follows.authorized and #follows_list() or 1
    end
    if id == "history" then return #(history or {}) end
    if id == "youtube" or id == "jellyfin" then return #media_rows(id) end
    return #selectable(id == "settings" and settings_rows() or system_rows())
end

local function current_row()
    local id = TABS[tab].id
    if id == "live" or id == "replays" or id == "history" or id == "follows" or id == "youtube" or id == "jellyfin" then
        return nil
    end
    local rows = id == "settings" and settings_rows() or system_rows()
    return rows[selectable(rows)[index]]
end

local function on_key(key)
    arm_idle()
    marquee_start = mp.get_time()
    if key == "home" then return close_menu() end
    if key == "homescreen" then
        act("home")
        return close_menu()
    end
    if key == "corner" then
        act("corner")
        return
    end
    if modal then
        if key == "up" or key == "down" then
            modal.sel = math.max(1, math.min(#modal.items, modal.sel + (key == "down" and 1 or -1)))
        elseif key == "ok" then
            local it = modal.items[modal.sel]
            modal = nil
            it.ok()
        elseif key == "back" or key == "left" then
            modal = nil
        end
        if is_open then draw() end
        return
    end
    if area == "rail" then
        if key == "up" or key == "down" then
            tab = math.max(1, math.min(#TABS, tab + (key == "down" and 1 or -1)))
            index, shortcut = 1, nil
        elseif (key == "right" or key == "ok") and content_count() > 0 then
            area, index, shortcut = "content", 1, nil
            if TABS[tab].id == "replays" then
                rp_row = 1
                for i, name in ipairs(state.streamers or {}) do if name == rp_login then rp_sel.chips = i end end
            end
        elseif key == "back" then
            return close_menu()
        end
        return draw()
    end
    -- Contenu
    local id, count = TABS[tab].id, content_count()
    if key == "back" then
        area, pending_display, pending_player = "rail", nil, nil
    elseif id == "live" and shortcut then
        local list = shortcuts()
        shortcut = math.min(shortcut, #list)
        if key == "left" then
            if shortcut == 1 then area, shortcut = "rail", nil else shortcut = shortcut - 1 end
        elseif key == "right" then
            shortcut = math.min(#list, shortcut + 1)
        elseif key == "down" and count > 0 then
            shortcut = nil
        elseif key == "ok" then
            list[shortcut].ok()
            if not is_open then return end
        end
    elseif id == "replays" then
        local rows = replay_rows()
        rp_row = math.min(rp_row, #rows)
        local row = rows[rp_row]
        local sel = rp_sel[row.kind] or 1
        if key == "up" then
            rp_row = math.max(1, rp_row - 1)
        elseif key == "down" then
            rp_row = math.min(#rows, rp_row + 1)
        elseif key == "left" then
            if sel == 1 then area = "rail" else rp_sel[row.kind] = sel - 1 end
        elseif key == "right" then
            rp_sel[row.kind] = math.min(#row.items, sel + 1)
        elseif key == "ok" then
            if row.kind == "chips" then
                local name = row.items[sel]
                if name and name ~= rp_login then
                    rp_login, rp_sel.vods, rp_sel.clips, rp_first.vods, rp_first.clips = name, 1, 1, 1, 1
                    load_replays(name)
                end
            else
                local item = row.items[sel]
                if item then choose_video(item, item.seconds) end
            end
        end
    elseif id == "youtube" or id == "jellyfin" then
        local m, rows = media[id], media_rows(id)
        m.row = math.max(1, math.min(m.row, #rows))
        local row = rows[m.row]
        local sel = row and math.min(m.sel[row.key] or 1, math.max(1, #row.items)) or 1
        if key == "up" then
            m.row = math.max(1, m.row - 1)
        elseif key == "down" then
            m.row = math.min(#rows, m.row + 1)
        elseif key == "left" then
            if sel == 1 then area = "rail" else m.sel[row.key] = sel - 1 end
        elseif key == "right" and row then
            m.sel[row.key] = math.min(#row.items, sel + 1)
        elseif key == "ok" and row and row.items[sel] then
            local it = row.items[sel]
            if id == "youtube" then choose_video(it, it.seconds) else jellyfin_choose(it) end
            if not is_open then return end
        end
    elseif id == "follows" then
        if not follows.authorized then
            if key == "left" then
                area = "rail"
            elseif key == "ok" and not (follows.pending and follows.pending.user_code and not follows.pending.error) then
                api("POST", "/api/follows_login", nil, function() load_follows() end)
            end
        else
            local list = follows_list()
            local col = (index - 1) % LIVE_COLS
            if key == "left" then
                if col == 0 then area = "rail" else index = index - 1 end
            elseif key == "right" then
                if col < LIVE_COLS - 1 and index < #list then index = index + 1 end
            elseif key == "up" then
                if index > LIVE_COLS then index = index - LIVE_COLS end
            elseif key == "down" then
                if index + LIVE_COLS <= #list then
                    index = index + LIVE_COLS
                elseif math.ceil(index / LIVE_COLS) < math.ceil(#list / LIVE_COLS) then
                    index = #list
                end
            elseif key == "ok" and list[index] then
                local name = list[index].login
                local watch = function()
                    act("channel", { name = name })
                    close_menu()
                end
                if in_list(name) then
                    watch()
                    return
                end
                open_modal(name, {
                    { label = "▶  Regarder", ok = watch },
                    { label = "＋  Ajouter à ma liste", ok = function()
                        api("POST", "/api/streamers", { action = "add", login = name }, function() refresh() end)
                    end },
                })
            end
        end
    elseif id == "history" then
        local list = history or {}
        local col = (index - 1) % HIST_COLS
        if key == "left" then
            if col == 0 then area = "rail" else index = index - 1 end
        elseif key == "right" then
            if col < HIST_COLS - 1 and index < #list then index = index + 1 end
        elseif key == "up" then
            if index > HIST_COLS then index = index - HIST_COLS end
        elseif key == "down" then
            if index + HIST_COLS <= #list then
                index = index + HIST_COLS
            elseif math.ceil(index / HIST_COLS) < math.ceil(#list / HIST_COLS) then
                index = #list
            end
        elseif key == "ok" and list[index] then
            local e = list[index]
            local items = {}
            if resumable(e.position, e.duration, e.finished) then
                items[#items + 1] = { label = "▶  Reprendre à " .. clock(e.position), ok = function() play(e.url) end }
                items[#items + 1] = { label = "↺  Depuis le début", ok = function() play(e.url, true) end }
            else
                items[#items + 1] = { label = e.finished and "↺  Revoir" or "▶  Lire", ok = function() play(e.url, true) end }
            end
            items[#items + 1] = { label = "✕  Retirer de l'historique", danger = true, ok = function()
                api("POST", "/api/history", { action = "remove", key = e.key }, function() load_history() end)
                table.remove(list, index)
                index = math.max(1, math.min(index, #list))
                if #list == 0 then area = "rail" end
            end }
            open_modal(e.title, items)
        end
    elseif id == "live" then
        local col = (index - 1) % LIVE_COLS
        if key == "left" then
            if col == 0 then area = "rail" else index = index - 1 end
        elseif key == "right" then
            if col < LIVE_COLS - 1 and index < count then index = index + 1 end
        elseif key == "up" then
            if index > LIVE_COLS then index = index - LIVE_COLS else shortcut = 1 end
        elseif key == "down" then
            if index + LIVE_COLS <= count then
                index = index + LIVE_COLS
            elseif math.ceil(index / LIVE_COLS) < math.ceil(count / LIVE_COLS) then
                index = count   -- dernière rangée incomplète
            end
        elseif key == "ok" then
            local name = (state.streamers or {})[index]
            if name then
                act("channel", { name = name })
                return close_menu()
            end
        end
    else
        local row = current_row()
        if key == "up" then
            index = math.max(1, index - 1)
            pending_display = nil
        elseif key == "down" then
            index = math.min(count, index + 1)
            pending_display = nil
        elseif (key == "left" or key == "right") and row and row.step then
            row.step(key == "right" and 1 or -1)
        elseif key == "left" then
            area = "rail"
        elseif key == "ok" and row then
            if row.ok then row.ok() elseif row.step then row.step(1) end
        end
    end
    if is_open then draw() end
end

mp.register_script_message("streambox-tvmenu-open", open_menu)
mp.register_script_message("streambox-tvmenu-close", close_menu)
mp.register_script_message("streambox-tvmenu-key", on_key)
mp.observe_property("osd-dimensions", "native", function() if is_open then draw() end end)
mp.add_periodic_timer(20, function() if is_open then draw() end end)   -- heure
mp.add_periodic_timer(1 / 15, function() if is_open and marquee_active then draw() end end)   -- textes défilants
mp.set_property_native("user-data/streambox/tvmenu", false)
refresh()

-- Stream Box : grand menu façon Android TV, ouvert par le bouton Menu de la télécommande (touche Accueil).
-- Onglets à gauche, contenu à droite : streamers en direct, réglages, système. La vidéo continue derrière, assombrie.
--
-- Les données et les actions passent par l'API de remote.py (comme la page web) : menu, page et Home Assistant restent
-- d'accord. Les touches arrivent de stream-box.lua (script-message streambox-tvmenu-key), qui les transmet tant que
-- user-data/streambox/tvmenu est vrai. Les photos sont des images brutes (overlay-add) préparées par remote.py
-- (/api/tvimage), posées par-dessus le dessin ASS.
local mp = require "mp"
local utils = require "mp.utils"

local API = "http://127.0.0.1:8080"
local W, H = 1920, 1080        -- coordonnées du dessin ASS, mises à l'échelle de l'écran par mpv
local IDLE_CLOSE = 90          -- secondes sans touche avant de refermer le menu (écran de TV : pas d'image fixe)
local REFRESH = 5              -- secondes entre deux relevés de l'état pendant que le menu est ouvert
local MAX_IMAGES = 48          -- overlay-add accepte les identifiants 0 à 63

local TABS = { { id = "live", label = "En direct" }, { id = "settings", label = "Réglages" },
               { id = "system", label = "Système" } }
local CORNERS = { tl = "↖ haut gauche", tr = "↗ haut droite", br = "↘ bas droite", bl = "↙ bas gauche" }
local CORNER_ORDER = { "tl", "tr", "br", "bl" }   -- même ordre que stream-box.lua
local QR_MODES = { { "always", "Toujours" }, { "timed", "30 secondes" }, { "never", "Jamais" } }
local VIOLET, LIVE_RED = "FF4691", "5E4FFF"       -- BGR

local osd = mp.create_osd_overlay("ass-events")
osd.res_x, osd.res_y, osd.z = W, H, 60             -- au-dessus du chat, des sondages et des notifications
local is_open = false
local state, display, account, qr = {}, nil, nil, nil
local tab, area, index = 1, "rail", 1              -- onglet, zone qui a le focus (rail ou content), élément
local shortcut = nil                                -- En direct : raccourci sélectionné au-dessus des streamers
local pending_display = nil                         -- résolution choisie aux flèches, appliquée par OK
local poweroff_until = 0
local idle_timer, refresh_timer
local images, shown = {}, {}                        -- cache des images préparées ; overlays posés (id → signature)
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

local function label(x, y, size, color, s, align, extra)
    return ("{\\an%d\\pos(%d,%d)\\fs%d\\bord0\\shad0\\1c&H%s&%s}%s")
        :format(align or 4, math.floor(x), math.floor(y), size, color, extra or "", s)
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


-- Images (photos des streamers) : préparées par remote.py à la taille exacte en pixels de l'écran

local function place_images(list)
    local w = mp.get_osd_size()
    local scale = (w and w > 0) and w / W or 1
    local used = {}
    for i, im in ipairs(list) do
        if i > MAX_IMAGES then break end
        local id = i - 1
        local size = math.floor(im.size * scale)
        local key = im.src .. "|" .. size
        local c = images[key]
        if c == nil then
            images[key] = "loading"
            api("GET", ("/api/tvimage?src=%s&w=%d&h=%d&round=1"):format(url_encode(im.src), size, size), nil, function(d)
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
    out[#out + 1] = rrect(0, 0, 400, H, 0, "0B0710", "30")
    out[#out + 1] = rrect(56, 62, 52, 52, 14, VIOLET, "00")
    out[#out + 1] = "{\\an5\\pos(82,88)\\fs30\\bord0\\shad0\\1c&HFFFFFF&\\p1}m -7 -11 l 11 0 -7 11{\\p0}"   -- ▶ dessiné
    out[#out + 1] = label(126, 88, 36, "FFFFFF", "Stream Box", 4, "\\b1")
    for i, t in ipairs(TABS) do
        local y = 220 + (i - 1) * 92
        if i == tab and area == "rail" then
            out[#out + 1] = rrect(40, y, 320, 72, 36, "FFFFFF", "00")
            out[#out + 1] = label(78, y + 36, 32, "1A1020", ass_escape(t.label), 4, "\\b1")
        else
            if i == tab then
                out[#out + 1] = rrect(40, y, 320, 72, 36, "FFFFFF", "E6")
                out[#out + 1] = rrect(48, y + 22, 6, 28, 3, VIOLET, "00")
            end
            out[#out + 1] = label(78, y + 36, 32, i == tab and "FFFFFF" or "B4AFC2", ass_escape(t.label), 4,
                                  i == tab and "\\b1" or "")
        end
    end
    out[#out + 1] = label(56, H - 60, 22, "8A85A0",
        "▲▼◀▶ se déplacer   ·   OK valider   ·   Retour revenir   ·   Menu fermer", 4)
end

local function draw_header(out, title, subtitle)
    out[#out + 1] = label(460, 100, 52, "FFFFFF", ass_escape(title), 4, "\\b1")
    if subtitle then out[#out + 1] = label(460, 152, 26, "B4AFC2", ass_escape(subtitle), 4) end
    out[#out + 1] = label(W - 80, 100, 40, "FFFFFF", os.date("%H:%M"), 6)
end

local function draw_live(out, imgs)
    local list, live = state.streamers or {}, state.live or {}
    local n_live = 0
    for _, name in ipairs(list) do if live[name] then n_live = n_live + 1 end end
    draw_header(out, "En direct", n_live == 0 and "Aucun streamer de la liste n'est en live"
        or n_live == 1 and "1 streamer en live" or (n_live .. " streamers en live"))
    if #list == 0 then
        out[#out + 1] = label(460, 260, 30, "B4AFC2", "La liste est vide : ajoute des streamers depuis la télécommande web.")
        return
    end
    local cw, ch, gap, x0, y0 = 330, 150, 26, 460, 310
    local rows_visible = 3
    local sx = x0
    for i, sc in ipairs(shortcuts()) do
        local focused = area == "content" and shortcut == i
        local sw = 64 + #sc.label * 13
        if focused then out[#out + 1] = rrect(sx - 5, 205, sw + 10, 74, 37, "FFFFFF", "00") end
        out[#out + 1] = rrect(sx, 210, sw, 64, 32, sc.current and VIOLET or (focused and "3A2C4E" or "2A2034"),
                              (focused or sc.current) and "00" or "30")
        out[#out + 1] = label(sx + sw / 2, 242, 28, "FFFFFF", ass_escape(sc.label), 5, sc.current and "\\b1" or "")
        sx = sx + sw + 20
    end
    local focus_row = area == "content" and not shortcut and math.floor((index - 1) / LIVE_COLS) or 0
    local first_row = math.max(0, focus_row - rows_visible + 1)
    for i, name in ipairs(list) do
        local row, col = math.floor((i - 1) / LIVE_COLS) - first_row, (i - 1) % LIVE_COLS
        if row >= 0 and row < rows_visible then
            local x, y = x0 + col * (cw + gap), y0 + row * (ch + gap)
            local focused = area == "content" and not shortcut and i == index
            local info = live[name]
            local current = state.mode == "twitch" and state.channel == name
            if focused then out[#out + 1] = rrect(x - 6, y - 6, cw + 12, ch + 12, 26, "FFFFFF", "00") end
            out[#out + 1] = rrect(x, y, cw, ch, 22, focused and "3A2C4E" or "2A2034", focused and "00" or "30")
            -- Photo : disque de couleur avec l'initiale, recouvert par l'image quand elle est prête
            local ax, ay, as = x + 22, y + 30, 90
            if info then out[#out + 1] = rrect(ax - 5, ay - 5, as + 10, as + 10, (as + 10) / 2, LIVE_RED, "00") end
            out[#out + 1] = rrect(ax, ay, as, as, as / 2, "4A3D5C", "00")
            out[#out + 1] = label(ax + as / 2, ay + as / 2, 40, "D0C8E0", ass_escape(name:sub(1, 1):upper()), 5, "\\b1")
            if state.avatars and state.avatars[name] then
                imgs[#imgs + 1] = { src = state.avatars[name], x = ax, y = ay, size = as }
            end
            local tx = ax + as + 20
            out[#out + 1] = label(tx, y + 44, 30, "FFFFFF", ass_escape(shorten(name, 14)), 4, "\\b1")
            if info then
                out[#out + 1] = label(tx, y + 80, 22, LIVE_RED, "● " .. viewers(info.viewers), 4, "\\b1")
                out[#out + 1] = label(tx, y + 110, 20, "B4AFC2", ass_escape(shorten(info.game or info.title or "", 18)), 4)
            else
                out[#out + 1] = label(tx, y + 80, 22, "8A85A0", "Hors ligne", 4)
            end
            if current then
                out[#out + 1] = rrect(x + cw - 120, y + 12, 104, 30, 15, VIOLET, "00")
                out[#out + 1] = label(x + cw - 68, y + 27, 18, "FFFFFF", "EN COURS", 5, "\\b1")
            end
        end
    end
    -- Titre du live sélectionné, en entier, sous la grille
    local name = area == "content" and not shortcut and list[index]
    local info = name and live[name]
    if info and info.title then
        out[#out + 1] = label(460, y0 + rows_visible * (ch + gap) + 20, 26, "D0C8E0",
                              ass_escape(shorten(name .. "  ·  " .. info.title, 110)), 4)
    end
end

local function draw_rows(out, rows, title, subtitle, width)
    draw_header(out, title, subtitle)
    local sel = selectable(rows)
    local focused_row = area == "content" and sel[index] or nil
    local x, y, rw = 460, 210, width or 980
    -- Défilement : on part de la ligne qui garde l'élément choisi dans les 760 px disponibles
    local heights = {}
    for i, r in ipairs(rows) do heights[i] = r.header and 64 or (r.hint and 98 or 78) end
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
            out[#out + 1] = label(x + 4, y + 40, 22, "A99FC0", ass_escape(r.header:upper()), 4, "\\b1\\fsp2")
        else
            local focused = i == focused_row
            local h = heights[i]
            if focused then out[#out + 1] = rrect(x - 5, y - 5, rw + 10, h + 10, 24, "FFFFFF", "00") end
            out[#out + 1] = rrect(x, y, rw, h, 20, focused and "3A2C4E" or "2A2034", focused and "00" or "30")
            local ty = r.hint and y + 34 or y + h / 2
            out[#out + 1] = label(x + 30, ty, 30, r.danger and "8F8FFF" or "FFFFFF", ass_escape(r.label), 4)
            if r.hint then out[#out + 1] = label(x + 30, y + 70, 21, "B4AFC2", ass_escape(r.hint), 4) end
            if r.toggle ~= nil then   -- interrupteur dessiné
                local sx, sy = x + rw - 110, y + h / 2 - 20
                out[#out + 1] = rrect(sx, sy, 76, 40, 20, r.toggle and VIOLET or "5A5068", "00")
                out[#out + 1] = rrect(sx + (r.toggle and 40 or 4), sy + 4, 32, 32, 16, "FFFFFF", "00")
            elseif r.value then
                local arrows = focused and r.step
                out[#out + 1] = label(x + rw - 30, y + h / 2, 28, "E8E2F4",
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
    -- Voile sur la vidéo ; opaque sans vidéo, pour cacher l'écran d'ambiance (horloge, QR code)
    local out = { rrect(0, 0, W, H, 0, "0A0612", mp.get_property_native("video-params") and "1C" or "00") }
    out[#out + 1] = "{\\an7\\pos(0,0)\\bord0\\shad0\\1c&HFF4691&\\1a&HD8&\\blur120\\p1}m 1400 -200 l 2200 -200 2200 500 1400 500{\\p0}"
    local imgs = {}
    draw_rail(out)
    local id = TABS[tab].id
    if id == "live" then
        draw_live(out, imgs)
    elseif id == "settings" then
        draw_rows(out, settings_rows(), "Réglages", "◀ ▶ pour changer une valeur")
    else
        draw_rows(out, system_rows(), "Système", nil, 820)
        -- QR code de la télécommande web : pour tout ce qui demande de taper du texte
        local side = draw_qr(out, 1340, 230, 300)
        if side then
            out[#out + 1] = label(1340, 230 + side + 40, 26, "FFFFFF", "Télécommande sur le téléphone", 4, "\\b1")
            out[#out + 1] = label(1340, 230 + side + 78, 21, "B4AFC2", "Lien à lire, nouveau streamer, compte Twitch…", 4)
            out[#out + 1] = label(1340, 230 + side + 110, 21, "B4AFC2",
                                  ass_escape((qr.url or ""):gsub("^https?://", ""):gsub("/$", "")), 4)
        end
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
    pending_display, poweroff_until = nil, 0
    osd:remove()
    place_images({})
    if idle_timer then idle_timer:kill() end
    if refresh_timer then refresh_timer:kill() end
    mp.set_property_native("user-data/streambox/tvmenu", false)
end

local function open_menu()
    if is_open then return end
    is_open = true
    tab, area, index, shortcut = 1, "content", 1, nil
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
    if id == "live" then return #(state.streamers or {}) end
    return #selectable(id == "settings" and settings_rows() or system_rows())
end

local function current_row()
    local id = TABS[tab].id
    if id == "live" then return nil end
    local rows = id == "settings" and settings_rows() or system_rows()
    return rows[selectable(rows)[index]]
end

local function on_key(key)
    arm_idle()
    if key == "home" then return close_menu() end
    if key == "homescreen" then
        act("home")
        return close_menu()
    end
    if key == "corner" then
        act("corner")
        return
    end
    if area == "rail" then
        if key == "up" or key == "down" then
            tab = math.max(1, math.min(#TABS, tab + (key == "down" and 1 or -1)))
            index, shortcut = 1, nil
        elseif (key == "right" or key == "ok") and content_count() > 0 then
            area, index, shortcut = "content", 1, nil
        elseif key == "back" then
            return close_menu()
        end
        return draw()
    end
    -- Contenu
    local id, count = TABS[tab].id, content_count()
    if key == "back" then
        area, pending_display = "rail", nil
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
mp.set_property_native("user-data/streambox/tvmenu", false)
refresh()

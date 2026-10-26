-- Interface language (see i18n.py): texts written in English, translated from locales/<lang>.json of the repository;
-- the language is in ~/.config/stream-box/language ("en" when missing), reloaded on script-message streambox-language
local utils = require "mp.utils"

local M = { dict = {}, lang = "en", dir = "." }

function M.load(dir)   -- dir: repository (where locales/ is), remembered for the next reloads
    M.dir = dir or M.dir
    local home = os.getenv("HOME") or ""
    local f, lang = io.open(home .. "/.config/stream-box/language"), "en"
    if f then lang = (f:read("*l") or "en"):match("^%s*(%a+)") or "en" f:close() end
    M.dict, M.lang = {}, lang
    if lang == "en" then return end
    local lf = io.open(M.dir .. "/locales/" .. lang .. ".json")
    if lf then
        M.dict = utils.parse_json(lf:read("*a") or "") or {}
        lf:close()
    end
end

-- tr("Connected: {login}", { login = name })
function M.tr(s, a)
    local out = M.dict[s] or s
    if a then for k, v in pairs(a) do out = out:gsub("{" .. k .. "}", (tostring(v):gsub("%%", "%%%%"))) end end
    return out
end

-- decimal separator of the interface language: "4.6 k" in English, "4,6 k" in French
function M.dec(s) return M.lang == "fr" and (s:gsub("%.", ",")) or s end

return M

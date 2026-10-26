-- Drawing modules of stream-box.lua run outside mpv (mp and mp.utils stubbed), on every branch: luajit units.lua REPO
package.preload["mp.utils"] = function() return { parse_json = function() return {} end } end
package.preload["mp"] = function() return {} end
package.path = arg[1] .. "/lua/?.lua;" .. package.path   -- arg[1]: the repository
local polls = require "streambox.polls"
local ambient = require "streambox.ambient"
local fmt = require "streambox.fmt"
local now = os.time()
local s = polls.draw(1920, 1080, {
    poll = { title = "Quel boss ensuite ?", ends_at = now + 75, choices = { { title = "A", votes = 1200 }, { title = "B", votes = 3 } } },
    prediction = { title = "Gagne ?", status = "ACTIVE", ends_at = now + 30,
                   outcomes = { { title = "Oui", points = 16617298, users = 1200, color = "BLUE" }, { title = "Non", points = 5, users = 1, color = "PINK", winner = true } } } })
assert(s:find("1:15") or s:find("1:14"), "time left")
assert(s:find("16.6 M"), "amount")
s = polls.draw(1920, 1080, { poll = { title = "x", ended = true, choices = {} } })
assert(s:find("Results"))
local qr = function(x, y, size) return "QR", 100 end
s = ambient.draw(1920, 1080, { weather = { city = "Paris", temp = 12, text = "Sun", min = 1, max = 2, rain = 50 },
                               schedule = { { login = "a", when = "now", title = string.rep("t", 50) } },
                               setup = { ssid = "Box", password = "pw", url = "http://10.0.0.1/" } }, "Loading…", qr, "host")
assert(s:find("Setup") and s:find("rain 50%%") and s:find("QR") and s:find("Loading"), "ambient")
s = ambient.draw(1920, 1080, { setup = { connecting = "Home" } }, "", function() return nil end, "")
assert(s:find("Connecting"))
assert(fmt.clock(3725) == "1:02:05" and fmt.shorten("ééé", 3) == "é…")
print("units ok")

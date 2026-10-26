// Shared formatting for the menu components. Functions that produce words or units take the caller's tr function
// (see i18n.js) as their last parameter: Fmt.viewers(n, tr). Without it, the English text is returned.
.pragma library

function _t(tr, s, a) {
    if (tr) return tr(s, a)
    for (var k in a) s = s.split("{" + k + "}").join(a[k])
    return s
}

// One decimal, split into integer and decimal parts so the separator is translatable ("{int}.{dec}k")
function _parts(x) {
    var s = x.toFixed(1).split(".")
    return { int: s[0], dec: s[1] }
}

// Number with one decimal: "4.5" (translatable separator)
function decimal(v, tr) {
    return _t(tr, "{int}.{dec}", _parts(Number(v) || 0))
}

function viewers(v, tr) {
    v = Number(v) || 0
    return v >= 1000 ? _t(tr, "{int}.{dec}k", _parts(v / 1000)) : String(v)
}

function clock(t) {
    t = Math.max(0, Math.floor(Number(t) || 0))
    var h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60, s = t % 60
    var p = function (n) { return (n < 10 ? "0" : "") + n }
    return h > 0 ? h + ":" + p(m) + ":" + p(s) : m + ":" + p(s)
}

var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

function dateFr(iso, tr) {
    var m = /(\d+)-(\d+)-(\d+)/.exec(iso || "")
    return m ? _t(tr, "{month} {day}", { day: Number(m[3]), month: _t(tr, MONTHS[Number(m[2]) - 1], {}) }) : ""
}

// Video started and not finished: can be resumed
function resumable(position, duration, finished) {
    position = Number(position) || 0
    return !finished && position >= 30 && (!duration || position < duration)
}

// Big numbers: 16617298 → "16.6M", 4500 → "4.5k"
function big(v, tr) {
    v = Number(v) || 0
    if (v >= 1e6) return _t(tr, "{int}.{dec}M", _parts(v / 1e6))
    return viewers(v, tr)
}

// Duration of a live: "2h 14m", "35 min"
function since(epochSeconds, tr) {
    var s = Math.max(0, Date.now() / 1000 - (Number(epochSeconds) || 0))
    var h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60
    return h > 0 ? _t(tr, "{h}h {m}m", { h: h, m: (m < 10 ? "0" : "") + m }) : _t(tr, "{m} min", { m: m })
}

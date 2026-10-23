// Mise en forme commune aux composants du menu
.pragma library

function viewers(v) {
    v = Number(v) || 0
    return v >= 1000 ? (v / 1000).toFixed(1).replace(".", ",") + " k" : String(v)
}

function clock(t) {
    t = Math.max(0, Math.floor(Number(t) || 0))
    var h = Math.floor(t / 3600), m = Math.floor(t / 60) % 60, s = t % 60
    var p = function (n) { return (n < 10 ? "0" : "") + n }
    return h > 0 ? h + ":" + p(m) + ":" + p(s) : m + ":" + p(s)
}

var MONTHS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]

function dateFr(iso) {
    var m = /(\d+)-(\d+)-(\d+)/.exec(iso || "")
    return m ? Number(m[3]) + " " + MONTHS[Number(m[2]) - 1] : ""
}

// Vidéo commencée et pas finie : reprise possible
function resumable(position, duration, finished) {
    position = Number(position) || 0
    return !finished && position >= 30 && (!duration || position < duration)
}

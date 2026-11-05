// TV menu, PC link tab (the gamestream add-on's own tab, kind "custom": loaded by qml/TvMenu.qml, which calls load,
// key, hint, canEnter, enter and reset): games streamed from PCs with Sunshine (Moonlight, service.py). Chips of the
// PCs (found on the network or paired) above; OK on a PC not paired yet shows a code to type in Sunshine (its account's
// code dialog); ≡ on a PC, its account dialog; the chosen PC's games below, in a grid of posters (Sunshine's box art is
// 3:4), 5 per row
import QtQuick
import "../../../../qml/menu/layout.js" as Layout
import "../../../../qml"

Item {
    id: page
    required property var menu
    property string tabId: "games"
    anchors.fill: parent
    visible: menu.tabId === tabId
    function tr(s, a) { return menu.tr(s, a) }

    // The PCs (/api/gamestream: their state, their games), the chosen PC, focus on the chips (row 0) or its games
    property var gs: null
    property int pcIndex: 0
    property int row: 0
    property int sel: 0
    readonly property var pcs: (gs && gs.pcs) || []
    readonly property var pc: pcs.length ? pcs[Math.min(pcIndex, pcs.length - 1)] : ({})
    Timer { interval: 3000; repeat: true; running: page.menu.isOpen && page.visible; onTriggered: page.load() }

    function load() { menu.call("GET", "/api/gamestream", undefined, function (d) { if (d) gs = d; menu.checkArea() }) }
    function reset() { sel = 0; row = 0 }
    function canEnter() { return pcs.length > 0 }
    function enter() { row = pc.paired && (pc.apps || []).length ? 1 : 0 }   // the games, or the PCs to pair
    function pair(p) { menu.openCode("gamestream", "gamestream_pair", { host: p.host }) }
    function hint() {
        if (!gs) return tr("Loading…")
        if (!pcs.length) return gs.searching ? tr("Looking for PCs on the network…") : tr("No PC with Sunshine found on the network")
        if (!pc.online) return tr("{name} is off or unreachable", { name: pc.name })
        if (!pc.paired) return tr("OK on {name} to pair the box", { name: pc.name })
        if (pc.loading) return tr("Loading…")
        if (pc.unpaired_on_pc) return tr("{name} no longer knows the box: pair it again (≡)", { name: pc.name })
        return tr("{name} · {n} games", { name: pc.name, n: pc.apps.length }) + (pc.playing ? "  ·  " + tr("a game is running") : "")
    }
    function launch(a) { menu.call("POST", "/api/gamestream_launch", { host: pc.host, app: a.name }); menu.close() }
    function key(k) {
        if (!pcs.length) { if (k === "left") menu.area = "rail"; return }
        pcIndex = Math.min(pcIndex, pcs.length - 1)
        var p = pc
        if (k === "menu" && row === 0) return menu.accountMenu("gamestream", "pc:" + p.host)
        if (row === 0) {   // the PCs' chips
            if (k === "left") { if (pcIndex === 0) menu.area = "rail"; else { pcIndex--; sel = 0 } }
            else if (k === "right") { pcIndex = Math.min(pcs.length - 1, pcIndex + 1); sel = 0 }
            else if ((k === "down" || k === "ok") && p.paired && p.apps.length) row = 1
            else if (k === "ok" && !p.paired && p.online) pair(p)
            else if (k === "ok" && p.paired && p.unpaired_on_pc) pair(p)
            return
        }
        var list = p.apps, a = list[sel]
        if (k === "ok" && a) return launch(a)
        if (k === "menu" && a) {
            var items = [{ label: tr("▶  Play"), ok: function () { launch(a) } }]
            if (p.playing) items.push({ label: tr("✕  Close the game on the PC"), danger: true,
                                        ok: function () { menu.call("POST", "/api/gamestream_quit", { host: p.host }, function () { load() }) } })
            items.push({ label: tr("Cancel"), ok: function () {} })
            menu.openModal(a.name, items)
            return
        }
        if (k === "up" && sel < 5) { row = 0; return }   // (5 posters per row)
        var n = menu.grid(sel, list.length, 5, k)
        if (n < 0) menu.area = "rail"; else sel = n
    }

    ListView {   // the PCs
        y: 196; x: -40; width: 1440; height: 64
        orientation: ListView.Horizontal; spacing: 16; interactive: false; clip: false
        leftMargin: 40
        model: page.pcs.length
        currentIndex: page.pcIndex
        delegate: Item {
            readonly property var p: page.pcs[index] || {}
            readonly property bool foc: menu.area === "content" && page.row === 0 && index === page.pcIndex
            readonly property bool cur: index === page.pcIndex
            TextMetrics { id: chipMetrics; text: p.name || ""; font.pixelSize: 22; font.bold: true }
            width: Math.ceil(chipMetrics.advanceWidth) + 100; height: 64
            scale: foc ? 1.05 : 1
            Behavior on scale { NumberAnimation { duration: 160 } }
            FocusFrame { active: parent.foc; radius: 32 }
            Rectangle { anchors.fill: parent; radius: 32; color: parent.cur ? menu.pal.surfaceFocus : menu.pal.surface }
            Rectangle {   // state: green online and paired, amber not paired, grey off
                x: 26; anchors.verticalCenter: parent.verticalCenter; width: 14; height: 14; radius: 7
                color: !p.online ? "#6b6478" : p.paired ? "#3ecf6e" : "#f5b342"
            }
            Text { x: 54; anchors.verticalCenter: parent.verticalCenter; text: p.name || ""; color: "white"; font.pixelSize: 22; font.bold: parent.cur }
        }
    }
    Item {   // clip: the posters scroll between the chips and the help at the bottom
        x: -53; y: 276; width: Layout.contentW + 80; height: menu.height - 85 - 276; clip: true
        GridView {
            visible: !!page.pc.paired
            y: 0; x: 40; width: Layout.contentW; height: 2 * 480 + 47
            cellWidth: Layout.contentW / 5; cellHeight: 480
            interactive: false; clip: false; topMargin: 30   // (room for the focused poster, which grows)
            model: (page.pc.apps || []).length
            currentIndex: page.sel
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
            Behavior on contentY { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
            delegate: Item {
                width: Layout.contentW / 5; height: 480
                readonly property real rel: y - GridView.view.contentY
                opacity: rel > -240 && rel < GridView.view.height - 240 ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 150 } }
                readonly property var a: (page.pc.apps || [])[index] || {}
                VideoCard {
                    x: 13; y: 13; width: parent.width - 26; ratio: 3 / 4
                    title: a.name || ""
                    thumb: a.art || ""
                    meta: ""
                    accent: menu.accent
                    focused: menu.area === "content" && page.row === 1 && index === page.sel
                }
            }
        }
    }
}

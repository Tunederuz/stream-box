// TV menu, PC link tab: games streamed from PCs with Sunshine (Moonlight, gamestream.py). Chips of the PCs (found on
// the network or paired) above; OK on a PC not paired yet shows a code to type in Sunshine (menu/CodeDialog.qml); the
// chosen PC's games below, in a grid of posters (Sunshine's box art is 3:4), 5 per row
import QtQuick
import "layout.js" as Layout
import ".."

Item {
    id: page
    required property var menu
    anchors.fill: parent
    visible: menu.tabId === "games"
    readonly property var pcs: (menu.gs && menu.gs.pcs) || []
    readonly property var pc: menu.gsCur || ({})

    ListView {   // the PCs
        y: 196; x: -40; width: 1440; height: 64
        orientation: ListView.Horizontal; spacing: 16; interactive: false; clip: false
        leftMargin: 40
        model: page.pcs.length
        currentIndex: menu.gsPc
        delegate: Item {
            readonly property var p: page.pcs[index] || {}
            readonly property bool foc: menu.area === "content" && menu.gsRow === 0 && index === menu.gsPc
            readonly property bool cur: index === menu.gsPc
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
        x: -53; y: 276; width: Layout.contentW + 80; height: Layout.listBottom - 276; clip: true
        GridView {
            visible: !!page.pc.paired
            y: 0; x: 40; width: Layout.contentW; height: 2 * 480 + 47
            cellWidth: Layout.contentW / 5; cellHeight: 480
            interactive: false; clip: false; topMargin: 30   // (room for the focused poster, which grows)
            model: (page.pc.apps || []).length
            currentIndex: menu.gsSel
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
                    focused: menu.area === "content" && menu.gsRow === 1 && index === menu.gsSel
                }
            }
        }
    }
}

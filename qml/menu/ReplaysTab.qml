// TV menu, Replays tab: chips of the streamers of the list, then rows of replays and clips of the chosen one
import QtQuick
import "layout.js" as Layout
import ".."
import "../fmt.js" as Fmt

Item {
    id: page
    required property var menu
    anchors.fill: parent
    visible: menu.tabId === "replays"
    readonly property var rows: visible ? menu.replayRows() : []   // hidden tab: nothing to recompute
    ListView {   // streamer chips
        y: 196; x: -40; width: 1440; height: 64   // stops before the edge of the screen
        orientation: ListView.Horizontal; spacing: 16; interactive: false; clip: false
        leftMargin: 40
        model: (menu.st.streamers || []).length
        currentIndex: menu.rpSel[0]
        onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
        Behavior on contentX { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        delegate: Item {
            readonly property string login: (menu.st.streamers || [])[index] || ""
            readonly property bool foc: menu.area === "content" && menu.rpRow === 0 && index === menu.rpSel[0]
            readonly property bool cur: login === menu.rpLogin
            // width measured in bold (the displayed streamer is bold): the chip doesn't change size when it becomes so
            TextMetrics { id: chipMetrics; text: login; font.pixelSize: chipText.font.pixelSize; font.bold: true }
            width: Math.ceil(chipMetrics.advanceWidth) + 100; height: 64
            readonly property real rel: x - ListView.view.contentX
            // chips of variable widths: hidden if they go past the row (no first/fits window here)
            opacity: rel > -20 && rel + width < ListView.view.width + 20 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 90 } }
            scale: foc ? 1.05 : 1
            Behavior on scale { NumberAnimation { duration: 160 } }
            FocusFrame { active: parent.foc; radius: 32 }
            Rectangle { anchors.fill: parent; radius: 32; color: parent.cur ? "#9146ff" : (parent.foc ? "#3a2c4e" : "#2a2034") }
            RoundImage { x: 10; y: 8; width: 48; height: 48; circle: true; placeholder: "#4a3d5c"; source: (menu.st.avatars || {})[login] || "" }
            Text { id: chipText; x: 70; anchors.verticalCenter: parent.verticalCenter; text: login; color: "white"; font.pixelSize: 22; font.bold: parent.cur }
        }
    }
    Item {   // clip: the rows scroll between the chips and the help at the bottom
        x: -40; y: 276; width: parent.width + 80; height: menu.height - 85 - 276; clip: true
        SkeletonRows { visible: menu.replays[menu.rpLogin] === "loading"; x: 40; y: 24; rows: 2 }   // the streamer's replays not read yet
        Repeater {
            model: Math.max(0, page.rows.length - 1)
            Item {
                readonly property int r: index + 1
                readonly property var row: page.rows[r]
                // one full row, the next one showing its top; the focused row goes to the top
                x: 40; y: 24 + (index - Math.max(0, menu.rpRow - 1)) * Layout.rowH; width: Layout.contentW; height: Layout.rowH - 10
                Behavior on y { NumberAnimation { duration: 280; easing.type: Easing.OutCubic } }
                Text { x: 2; text: row ? row.title.toUpperCase() : ""; color: "#a99fc0"; font.pixelSize: 20; font.bold: true; font.letterSpacing: 2 }
                CardRow {
                    view.model: row ? row.items.length : 0
                    view.currentIndex: menu.rpSel[r] || 0
                    view.delegate: VideoCard {
                        readonly property var it: row.items[index] || {}
                        opacity: index >= ListView.view.first && index < ListView.view.first + ListView.view.fits ? 1 : 0   // target window
                        Behavior on opacity { NumberAnimation { duration: 90 } }
                        title: it.title || ""
                        thumb: it.thumb || ""
                        meta: it.more ? menu.cardMeta(row, it)   // ("Load more")
                              : (row.kind === "vods" ? Fmt.dateFr(it.date, menu.tr) + " · " + Fmt.clock(it.seconds)
                                 : Fmt.clock(it.seconds) + " · " + menu.tr("{n} views", { n: Fmt.viewers(it.views, menu.tr) }))
                                + (it.finished ? " · " + menu.tr("watched") : "")
                        glyph: it.more ? "+" : "▶"
                        progress: it.finished ? 1 : (it.position && it.seconds ? it.position / it.seconds : 0)
                        focused: menu.area === "content" && menu.rpRow === r && index === (menu.rpSel[r] || 0)
                    }
                }
            }
        }
    }
}

// TV menu, Live tab: shortcuts above (resume, second stream), grid of the streamers of the list, title of the chosen
// live. After a moment on a live streamer, its live plays in the background of the menu (TvMenu.bgLive)
import QtQuick
import "layout.js" as Layout
import ".."

Item {
    id: root
    required property var menu
    anchors.fill: parent
    visible: menu.tabId === "live"

    Row {
        y: 210; spacing: 20
        Repeater {
            model: menu.shortcuts()
            Item {
                width: label.implicitWidth + 72; height: 64
                readonly property bool foc: menu.area === "content" && menu.shortcut === index
                scale: foc ? 1.05 : 1
                Behavior on scale { NumberAnimation { duration: 160 } }
                FocusFrame { active: foc; radius: 32 }
                Rectangle { anchors.fill: parent; radius: 32; color: modelData.current ? "#9146ff" : (foc ? "#3a2c4e" : "#2a2034") }
                Text { id: label; anchors.centerIn: parent; text: modelData.label; color: "white"; font.pixelSize: 24; font.bold: !!modelData.current }
                Tap { tv: menu; rightKey: "back"; onPick: { menu.area = "content"; menu.shortcut = index } }
            }
        }
    }
    Item {   // clip: what scrolls stops at the edge of the area (neither over the title nor over the help at the bottom)
        x: -53; y: 255; width: Layout.contentW + 80; height: 3 * Layout.cellH + 60 + 30; clip: true
        GridView {
            id: liveGrid
            y: 15; x: 40; width: Layout.contentW; height: 3 * Layout.cellH + 60
            cellWidth: Layout.cellW; cellHeight: Layout.cellH
            interactive: false; clip: false
            topMargin: 27
            model: (menu.st.streamers || []).length
            currentIndex: menu.liveSel
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
            Behavior on contentY { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            delegate: Item {
                width: Layout.cellW; height: Layout.cellH
                readonly property real rel: y - GridView.view.contentY
                opacity: rel > -88 && rel < GridView.view.height - 88 ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 150 } }
                readonly property string login: (menu.st.streamers || [])[index] || ""
                readonly property var info: (menu.st.live || {})[login]
                StreamerCard {
                    x: 13; y: 13
                    name: login
                    avatar: (menu.st.avatars || {})[login] || ""
                    live: !!info
                    viewers: info ? info.viewers : 0
                    game: info ? (info.game || info.title || "") : ""
                    focused: menu.area === "content" && menu.shortcut < 0 && index === menu.liveSel
                    current: menu.st.mode === "twitch" && menu.st.channel === login
                }
                Tap { tv: menu; onPick: { menu.area = "content"; menu.shortcut = -1; menu.liveSel = index } }
            }
        }
    }
    Marquee {   // title of the chosen live, in full
        y: 290 + 3 * Layout.cellH + 40; width: 1400; pixelSize: 24; color: "#d0c8e0"; running: true
        readonly property string login: (menu.st.streamers || [])[menu.liveSel] || ""
        readonly property var info: (menu.st.live || {})[login]
        visible: menu.area === "content" && menu.shortcut < 0 && !!info
        text: info ? login + "  ·  " + info.title : ""
    }
    Text {
        visible: !(menu.st.streamers || []).length
        y: 280; text: menu.tr("The list is empty: add streamers from the companion app.")
        color: "#b4afc2"; font.pixelSize: 27
    }
}

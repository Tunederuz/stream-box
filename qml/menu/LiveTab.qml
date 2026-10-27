// TV menu, Live tab: shortcuts above (resume, second stream), grid of the streamers of the list, title of the chosen
// live. After a moment on a live streamer, its card grows over its neighbors into a 16:9 tile that plays the live
import QtQuick
import "layout.js" as Layout
import "../fmt.js" as Fmt
import ".."

Item {
    id: root
    required property var menu
    anchors.fill: parent
    visible: menu.tabId === "live"

    // Live preview (card preview "twitch:<login>": streamlink started by ui.py): not for the stream already on the TV
    // (behind the menu) nor the second one; any key puts the card back, and it grows again after a moment
    readonly property string login: (menu.st.streamers || [])[menu.liveSel] || ""
    readonly property var info: (menu.st.live || {})[login]
    readonly property bool previewable: !!info && menu.isOpen && menu.tabId === "live" && menu.area === "content"
        && menu.shortcut < 0 && !menu.modal && !(menu.st.mode === "twitch" && menu.st.channel === login)
        && pip.channel !== login
    readonly property int tileW: 480
    readonly property int videoH: 270
    readonly property int captionH: 88
    property bool grown: false
    property var to: ({ x: 0, y: 0, width: 0, height: 0 })
    Timer { id: dwell; interval: 900; onTriggered: root.grow() }
    function again() { grown = false; if (previewable) dwell.restart(); else dwell.stop() }
    onPreviewableChanged: again()
    onLoginChanged: again()
    Connections {
        target: root.menu
        function onKeyCountChanged() { root.again() }
    }
    function grow() {
        var card = liveGrid.currentItem
        if (!previewable || !card) return
        var c = card.mapToItem(root, 13, 13, 330, 150)   // the StreamerCard inside the cell
        var h = videoH + captionH
        var x = Math.max(0, Math.min(Layout.contentW - 40 - tileW, c.x + c.width / 2 - tileW / 2))   // margin of the cards
        var y = Math.max(200, Math.min(Layout.listBottom - h, c.y + c.height / 2 - h / 2))
        to = { x: x, y: y, width: tileW, height: h }
        tile.x = c.x; tile.y = c.y; tile.width = c.width; tile.height = c.height
        grown = true
        growAnim.restart()
        // the video goes where the tile ends up, it fades in once the live is there (about 2 s)
        menu.startPreview({ url: "twitch:" + login }, root.mapToItem(menu, x, y, tileW, videoH))
    }

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
            }
        }
    }
    Item {   // the grown card: Twitch's live thumbnail (the live fades in over it), name, viewers, game
        id: tile
        visible: root.grown
        ParallelAnimation {
            id: growAnim
            NumberAnimation { target: tile; property: "x"; to: root.to.x; duration: 220; easing.type: Easing.OutCubic }
            NumberAnimation { target: tile; property: "y"; to: root.to.y; duration: 220; easing.type: Easing.OutCubic }
            NumberAnimation { target: tile; property: "width"; to: root.to.width; duration: 220; easing.type: Easing.OutCubic }
            NumberAnimation { target: tile; property: "height"; to: root.to.height; duration: 220; easing.type: Easing.OutCubic }
        }
        FocusFrame { active: true; radius: 18 }
        Rectangle { anchors.fill: parent; radius: 18; color: "#3a2c4e" }
        RoundImage {
            width: parent.width; height: Math.max(0, parent.height - root.captionH)
            radius: 18
            placeholder: "#2a2034"
            source: root.grown ? "https://static-cdn.jtvnw.net/previews-ttv/live_user_" + root.login
                                 + "-640x360.jpg?t=" + Math.floor(root.menu.now.getTime() / 300000) : ""
        }
        Row {
            x: 18; y: parent.height - root.captionH + 16; spacing: 14
            visible: tile.height > root.captionH + 40   // not while it is still growing from the card
            RoundImage {
                width: 50; height: 50; circle: true; placeholder: "#4a3d5c"
                source: (root.menu.st.avatars || {})[root.login] || ""
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter
                Text { text: root.login; color: "white"; font.pixelSize: 25; font.bold: true }
                Text {
                    width: root.tileW - 100; elide: Text.ElideRight
                    text: root.info ? "● " + Fmt.viewers(root.info.viewers, root.menu.tr)
                                      + (root.info.game ? "  ·  " + root.info.game : "") : ""
                    color: "#ff8a95"; font.pixelSize: 20
                }
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

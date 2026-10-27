// TV menu, Live tab: banner of the chosen streamer (its live plays muted in the frame after a moment: card
// preview), shortcuts (resume, second stream), then the grid of the streamers of the list
import QtQuick
import "layout.js" as Layout
import "../fmt.js" as Fmt
import ".."

Item {
    id: root
    required property var menu
    anchors.fill: parent
    visible: menu.tabId === "live"

    readonly property string login: (menu.st.streamers || [])[menu.liveSel] || ""
    readonly property var info: (menu.st.live || {})[login]
    readonly property bool onTv: menu.st.mode === "twitch" && menu.st.channel === login
    // Live preview in the banner: not for the stream already on the TV (behind the menu) nor the second one
    readonly property bool previewable: !!info && menu.isOpen && menu.tabId === "live" && menu.area === "content"
        && menu.shortcut < 0 && !menu.modal && !onTv && pip.channel !== login
    Timer {
        id: dwell
        interval: 900
        onTriggered: if (root.previewable) root.menu.startPreview({ url: "twitch:" + root.login }, frame)
    }
    onPreviewableChanged: if (previewable) dwell.restart(); else dwell.stop()
    onLoginChanged: if (previewable) dwell.restart()
    Connections {   // any key stops the preview (TvMenu.key): it starts again on the streamer still chosen
        target: root.menu
        function onKeyCountChanged() { if (root.previewable) dwell.restart() }
    }

    // Banner: picture of the live (Twitch's thumbnail, refreshed every 5 minutes) or the photo of an offline streamer
    Item {
        id: banner
        visible: !!root.login
        y: 200
        width: Layout.contentW; height: Layout.bannerH
        Item {
            id: frame
            width: Layout.bannerH * 16 / 9; height: Layout.bannerH
            Rectangle { anchors.fill: parent; radius: 16; color: "#2a2034" }
            RoundImage {
                anchors.fill: parent
                visible: !!root.info
                radius: 16
                placeholder: "#2a2034"
                source: root.info ? "https://static-cdn.jtvnw.net/previews-ttv/live_user_" + root.login
                                    + "-640x360.jpg?t=" + Math.floor(root.menu.now.getTime() / 300000) : ""
            }
            RoundImage {
                visible: !root.info
                anchors.centerIn: parent
                width: 150; height: 150
                circle: true
                placeholder: "#4a3d5c"
                source: (root.menu.st.avatars || {})[root.login] || ""
                opacity: 0.6
            }
        }
        Column {
            x: frame.width + 40; width: banner.width - frame.width - 80
            anchors.verticalCenter: frame.verticalCenter
            spacing: 10
            Text {
                width: parent.width; elide: Text.ElideRight
                text: root.login; color: "white"; font.pixelSize: 36; font.bold: true
            }
            Text {
                text: root.info ? "● " + root.menu.tr("{n} viewers", { n: Fmt.viewers(root.info.viewers, root.menu.tr) })
                    + (root.onTv ? "   ·   " + root.menu.tr("On the TV") : "") : root.menu.tr("Offline")
                color: root.info ? "#ff4f5e" : "#8a85a0"; font.pixelSize: 24; font.bold: !!root.info
            }
            Text {
                visible: !!(root.info && root.info.game)
                width: parent.width; elide: Text.ElideRight
                text: root.info ? root.info.game || "" : ""; color: "#b4afc2"; font.pixelSize: 25
            }
            Text {
                visible: !!(root.info && root.info.title)
                width: parent.width; wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight
                text: root.info ? root.info.title || "" : ""; color: "#e0daea"; font.pixelSize: 25
            }
        }
    }
    Row {
        y: 200 + Layout.bannerH + 20; spacing: 20
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
    Item {   // clip: what scrolls stops at the edge of the area (neither over the banner nor over the help at the bottom)
        x: -53; y: 200 + Layout.bannerH + 66; width: Layout.contentW + 80; height: 2 * Layout.cellH + 60 + 30; clip: true
        GridView {
            y: 15; x: 40; width: Layout.contentW; height: 2 * Layout.cellH + 60   // two rows of streamers
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
    Text {
        visible: !(menu.st.streamers || []).length
        y: 280; text: menu.tr("The list is empty: add streamers from the companion app.")
        color: "#b4afc2"; font.pixelSize: 27
    }
}

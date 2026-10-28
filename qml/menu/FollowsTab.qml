// TV menu, Following tab: Twitch app missing, authorization (code and QR code), or grid of the followed channels
// (after a moment on a live one, its live plays in the menu's background: TvMenu.bgLive)
import QtQuick
import "layout.js" as Layout
import ".."

Item {
    id: page
    required property var menu
    anchors.fill: parent
    visible: menu.tabId === "follows"
    readonly property var f: menu.follows || {}
    readonly property var pend: f.pending || null
    readonly property bool waiting: !!(pend && pend.user_code && !pend.error)
    Column {
        visible: !!menu.follows && !menu.follows.error && !page.f.configured
        y: 260; spacing: 20
        Text { text: menu.tr("To show them, the box needs your own Twitch app."); color: "white"; font.pixelSize: 27 }
        Text { text: menu.tr("Companion app → Settings → Followed channels: everything is explained there."); color: "#b4afc2"; font.pixelSize: 22 }
    }
    Item {
        visible: !!page.f.configured && !page.f.authorized
        anchors.fill: parent
        Column {
            visible: page.waiting
            y: 260; spacing: 26
            Text { text: menu.tr("On your phone, open twitch.tv/activate and enter:"); color: "white"; font.pixelSize: 27 }
            Text { text: page.pend ? page.pend.user_code || "" : ""; color: "white"; font.pixelSize: 75; font.bold: true; font.letterSpacing: 12 }
            Text { text: menu.tr("or scan the QR code. The TV updates by itself."); color: "#b4afc2"; font.pixelSize: 22 }
        }
        QrCode { visible: page.waiting && n > 0; x: 940; y: 240; size: 360; rows: menu.followsQr ? menu.followsQr.rows : [] }
        Item {
            visible: !page.waiting
            y: 290; width: 440; height: 74
            readonly property bool foc: menu.area === "content"
            scale: foc ? 1.05 : 1
            Behavior on scale { NumberAnimation { duration: 160 } }
            FocusFrame { active: parent.foc; radius: 37 }
            Rectangle { anchors.fill: parent; radius: 37; color: "#9146ff" }
            // asked, the code not there yet (TvMenu sets pending {} at once)
            Text { anchors.centerIn: parent; text: page.pend && !page.pend.error ? menu.tr("Requesting the code…") : menu.tr("Authorize the box")
                   color: "white"; font.pixelSize: 25; font.bold: true }
        }
        Text {
            visible: !!(page.pend && page.pend.error)
            y: 230; text: visible ? menu.tr("Authorization denied: {error}", { error: page.pend.error }) : ""
            color: "#ff8f8f"; font.pixelSize: 22
        }
    }
    Item {   // clip: what scrolls stops at the edge of the area (neither over the title nor over the help at the bottom)
        x: -53; y: 161; width: Layout.contentW + 80; height: 4 * Layout.cellH + 60 + 30; clip: true
        GridView {
            visible: !!page.f.authorized
            y: 15; x: 40; width: Layout.contentW; height: 4 * Layout.cellH + 60
            cellWidth: Layout.cellW; cellHeight: Layout.cellH
            interactive: false; clip: false; topMargin: 27
            model: menu.followItems.length
            currentIndex: menu.followSel
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
            Behavior on contentY { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            delegate: Item {
                width: Layout.cellW; height: Layout.cellH
                readonly property real rel: y - GridView.view.contentY
                opacity: rel > -88 && rel < GridView.view.height - 88 ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 150 } }
                readonly property var c: menu.followItems[index] || {}
                StreamerCard {
                    x: 13; y: 13
                    name: c.login || ""
                    avatar: c.avatar || ""
                    live: c.viewers !== undefined && c.viewers !== null
                    viewers: c.viewers || 0
                    game: c.game || c.title || ""
                    focused: menu.area === "content" && index === menu.followSel
                    current: menu.st.mode === "twitch" && menu.st.channel === c.login
                }
            }
        }
    }
}

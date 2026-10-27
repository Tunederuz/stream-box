// Peek at a live, full screen (▶ on a live streamer of the Live tab, TvMenu.peek). Two layers around the video
// (CardPreview, between them in TvMenu): "back", a black screen and Twitch's live thumbnail while the live loads;
// "front", the streamer's photo, name, viewers, game and title at the bottom, and the keys.
import QtQuick
import "../fmt.js" as Fmt
import ".."

Item {
    id: root
    required property var menu
    required property string part   // "back" or "front"
    anchors.fill: parent
    visible: opacity > 0
    opacity: menu.peek ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 200 } }
    property string login: ""   // stays while fading out
    readonly property string peek: menu.peek
    onPeekChanged: if (peek) login = peek
    readonly property var info: (menu.st.live || {})[login]

    Rectangle { visible: root.part === "back"; anchors.fill: parent; color: "black" }
    Image {
        visible: root.part === "back"
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        source: root.login ? "https://static-cdn.jtvnw.net/previews-ttv/live_user_" + root.login
                             + "-1280x720.jpg?t=" + Math.floor(root.menu.now.getTime() / 300000) : ""
    }

    Item {
        visible: root.part === "front"
        anchors.fill: parent
        Rectangle {   // darkens the bottom, under the caption
            anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
            height: 300
            gradient: Gradient {
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 1; color: "#e0000000" }
            }
        }
        Row {
            x: 80; anchors.bottom: parent.bottom; anchors.bottomMargin: 110; spacing: 24
            RoundImage {
                width: 96; height: 96; circle: true; placeholder: "#4a3d5c"
                source: (root.menu.st.avatars || {})[root.login] || ""
            }
            Column {
                anchors.verticalCenter: parent.verticalCenter; spacing: 4
                Text { text: root.login; color: "white"; font.pixelSize: 40; font.bold: true }
                Text {
                    text: root.info ? "● " + Fmt.viewers(root.info.viewers, root.menu.tr)
                                      + (root.info.game ? "  ·  " + root.info.game : "") : ""
                    color: "#ff8a95"; font.pixelSize: 26
                }
                Text {
                    width: 1500; elide: Text.ElideRight
                    text: root.info ? root.info.title || "" : ""
                    color: "#e0e0e0"; font.pixelSize: 26
                }
            }
        }
        Text {
            x: 80; anchors.bottom: parent.bottom; anchors.bottomMargin: 48
            text: root.menu.tr("OK watch   ·   any other key: back")
            color: "#b0b0b0"; font.pixelSize: 22
        }
        Text {   // until the live is there (streamlink takes a few seconds)
            anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 60
            visible: !cardPreview.ready
            text: root.menu.tr("Loading…")
            color: "white"; font.pixelSize: 26
        }
    }
}

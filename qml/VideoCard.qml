// Video card (VODs, clips, history): rounded thumbnail, progress, title scrolling when focused, info
import QtQuick

Item {
    id: root
    property string title: ""
    property string meta: ""
    property string thumb: ""
    property real progress: 0
    property bool focused: false
    property color accent: "#9146ff"   // glow and progress: red on the YouTube tab
    property string glyph: "▶"         // in the center, without a thumbnail ("+": action card, "Connect my account")
    property bool previewable: false   // its video can play in the thumbnail (TvMenu.startPreview)
    signal previewWanted(Item picture)  // focused for a moment: the thumbnail where the preview goes
    readonly property int picH: Math.round(width * 9 / 16)   // 16:9 thumbnail
    width: 456   // 3 cards per row in the menu
    height: picH + 106
    z: focused ? 2 : 1
    Timer { interval: 900; running: root.focused && root.previewable; onTriggered: root.previewWanted(picture) }

    Item {
        id: picture
        width: root.width
        height: root.picH
        scale: root.focused ? 1.06 : 1
        transformOrigin: Item.Bottom
        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        FocusFrame { active: root.focused; radius: 16; glow: root.accent }
        RoundImage {
            anchors.fill: parent
            radius: 16
            placeholder: "#2a2034"
            // VOD of the ongoing live: Twitch gives a "processing" image, the drawn ▶ is better
            source: root.thumb.indexOf("404_processing") >= 0 ? "" : root.thumb
            Text {   // while waiting for the image (or for an ongoing VOD, without a thumbnail)
                anchors.centerIn: parent
                z: -1
                text: "▶"
                color: "#5a5068"
                font.pixelSize: 42
            }
        }
        Text {   // action card, without a thumbnail
            visible: root.glyph !== "▶"
            anchors.centerIn: parent
            text: root.glyph
            color: "white"
            font.pixelSize: 72
        }
    }
    Rectangle {
        visible: root.progress > 0
        y: root.picH + 10
        width: root.width
        height: 6
        radius: 3
        color: "#4a3d5c"
        Rectangle {
            width: Math.max(6, parent.width * Math.min(1, root.progress))
            height: parent.height
            radius: 3
            color: root.accent
        }
    }
    Marquee {
        y: root.picH + 28
        width: root.width
        text: root.title
        color: root.focused ? "white" : "#e0daea"
        pixelSize: 28
        bold: root.focused
        running: root.focused
    }
    Text {
        y: root.picH + 74
        width: root.width
        text: root.meta
        color: "#a99fc0"
        font.pixelSize: 22
        elide: Text.ElideRight
    }
}

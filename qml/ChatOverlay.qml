// Twitch chat with emotes (Qt app): messages from chat_qt.py (via the "chat" object of ui.py), in the chosen corner,
// with the settings of the companion app (background, size). Words and emotes follow each other in a Flow; animated
// emotes (GIF, WebP) move. Coordinates in 1920x1080.
import QtQuick

Item {
    id: root
    anchors.fill: parent
    readonly property var messages: { try { return JSON.parse(chat.messages || "[]") } catch (e) { return [] } }
    readonly property bool atLeft: chat.corner === "tl" || chat.corner === "bl"
    readonly property bool atTop: chat.corner === "tl" || chat.corner === "tr"
    // Size set for the ASS chat (\fs): Qt draws larger for the same value
    readonly property real fontSize: chat.size * 0.78
    readonly property real maxWidth: 820
    visible: chat.visible && messages.length > 0
    opacity: visible ? 1 : 0
    Behavior on opacity { NumberAnimation { duration: 200 } }

    Rectangle {   // semi-transparent background
        x: column.x - 14; y: column.y - 14
        width: column.width + 28; height: column.height + 28
        radius: 12
        color: "black"
        opacity: chat.bg / 100
        visible: chat.bg > 0
    }
    Column {
        id: column
        x: root.atLeft ? 40 : root.width - 40 - width
        y: root.atTop ? 40 : root.height - 40 - height
        spacing: 4
        Repeater {
            model: root.messages
            // Wrapper at the width actually taken by the message (fitted background, right alignment possible);
            // the Flow inside wraps at maxWidth
            Item {
                width: line.childrenRect.width
                height: line.height
                x: 0   // text left-aligned in the frame, even in a right corner
                Flow {
                    id: line
                    readonly property var m: modelData
                    width: root.maxWidth
                    spacing: root.fontSize * 0.28
                    Text {
                        text: line.m.name
                        color: line.m.color
                        font.pixelSize: root.fontSize
                        font.bold: true
                        height: root.fontSize * 1.45
                        verticalAlignment: Text.AlignVCenter
                        style: Text.Outline
                        styleColor: "#cc000000"
                    }
                    Repeater {
                        model: line.m.parts
                        Loader {
                            sourceComponent: modelData.t === "e" ? emote : word
                            property var part: modelData
                        }
                    }
                }
            }
        }
    }
    Component {
        id: word
        Text {
            text: part.v
            color: "white"
            font.pixelSize: root.fontSize
            height: root.fontSize * 1.45
            verticalAlignment: Text.AlignVCenter
            style: Text.Outline
            styleColor: "#cc000000"
        }
    }
    Component {
        id: emote
        AnimatedImage {
            source: part.u
            height: root.fontSize * 1.45
            width: status === AnimatedImage.Ready && implicitHeight > 0 ? implicitWidth * height / implicitHeight : height
            fillMode: Image.PreserveAspectFit
            asynchronous: true
            cache: true
            playing: root.visible
        }
    }
}

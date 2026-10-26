// Single-line text: cut with "…" at rest; when running and it overflows, it scrolls after a pause, and a
// second copy comes in as the first one leaves.
import QtQuick

Item {
    id: root
    property string text: ""
    property color color: "white"
    property int pixelSize: 19
    property bool bold: false
    property bool running: false
    readonly property real gap: 90
    readonly property bool overflow: probe.implicitWidth > width
    readonly property bool scrolling: running && overflow
    clip: true
    implicitHeight: probe.implicitHeight

    Text {
        id: probe   // measuring only
        visible: false
        text: root.text
        font.pixelSize: root.pixelSize
        font.bold: root.bold
    }
    Text {   // at rest (or short enough): cut with "…"
        visible: !root.scrolling
        width: root.width
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        color: root.color
        font.pixelSize: root.pixelSize
        font.bold: root.bold
        elide: Text.ElideRight
    }
    Row {   // scrolling: two copies one behind the other
        id: row
        visible: root.scrolling
        x: 0
        anchors.verticalCenter: parent.verticalCenter
        spacing: root.gap
        Repeater {
            model: 2
            Text {
                text: root.text
                color: root.color
                font.pixelSize: root.pixelSize
                font.bold: root.bold
            }
        }
    }
    SequentialAnimation {
        id: anim
        running: root.scrolling
        loops: Animation.Infinite
        onRunningChanged: if (!running) row.x = 0
        PropertyAction { target: row; property: "x"; value: 0 }
        PauseAnimation { duration: 1500 }
        NumberAnimation {
            target: row
            property: "x"
            from: 0
            to: -(probe.implicitWidth + root.gap)
            duration: (probe.implicitWidth + root.gap) / 70 * 1000   // 70 px/s, like the old menu
        }
    }
}

// Focus frame, under the chosen item: soft gradient purple glow all around (blurry rectangular shadow, computed
// by the GPU) and white border, fading
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property bool active: false
    property real radius: 22
    property color glow: "#9146ff"   // purple; red on the YouTube tab
    anchors.fill: parent
    opacity: active ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 180 } }

    RectangularShadow {
        anchors.fill: parent
        radius: root.radius
        blur: 42
        spread: 4
        color: root.glow
        opacity: 0.9
    }
    Rectangle {
        anchors.fill: parent
        anchors.margins: -6
        radius: root.radius + 6
        color: "transparent"
        border.color: "white"
        border.width: 4
    }
}

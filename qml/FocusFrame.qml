// Cadre de focus : halo violet flou et bord blanc autour de l'élément parent, en fondu
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property bool active: false
    property real radius: 22
    anchors.fill: parent
    anchors.margins: -6
    opacity: active ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 160 } }

    Rectangle {
        id: glowShape
        anchors.fill: parent
        radius: root.radius + 6
        color: "#9146ff"
        visible: false
    }
    MultiEffect {
        source: glowShape
        anchors.fill: glowShape
        anchors.margins: -24
        autoPaddingEnabled: true
        blurEnabled: true
        blur: 1.0
        blurMax: 32
        opacity: 0.55
    }
    Rectangle {
        anchors.fill: parent
        radius: root.radius + 6
        color: "transparent"
        border.color: "white"
        border.width: 4
    }
}

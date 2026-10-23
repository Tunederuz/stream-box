// Cadre de focus, sous l'élément choisi : halo violet en dégradé doux tout autour (ombre rectangulaire floue, calculée
// par la puce graphique) et bord blanc, en fondu
import QtQuick
import QtQuick.Effects

Item {
    id: root
    property bool active: false
    property real radius: 22
    anchors.fill: parent
    opacity: active ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 180 } }

    RectangularShadow {
        anchors.fill: parent
        radius: root.radius
        blur: 42
        spread: 4
        color: "#9146ff"
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

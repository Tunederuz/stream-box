// Choix des sous-titres et de la piste audio pendant une vidéo (touche ≡), au-dessus de la barre de lecture, à droite.
// stream-box.lua tient la liste, le choix et les touches (user-data/streambox/tracks) ; ici, seulement le dessin.
import QtQuick
import QtQuick.Effects

Item {
    id: root
    anchors.fill: parent
    readonly property var t: { try { return JSON.parse(osd.tracks || "{}") } catch (e) { return {} } }
    readonly property bool shown: !!t.open
    property var last: ({ items: [], sel: 0 })   // dernier état, gardé pendant la sortie
    onTChanged: if (t.open) last = t
    readonly property var items: last.items || []

    Item {
        id: card
        width: 600
        height: Math.min(list.contentHeight, 520) + 56
        x: parent.width - width - 96
        y: parent.height - 540 - height   // au-dessus du titre de la barre de lecture
        opacity: root.shown ? 1 : 0
        scale: root.shown ? 1 : 0.96
        transformOrigin: Item.BottomRight
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 180 } }
        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }

        RectangularShadow { anchors.fill: parent; radius: 26; blur: 50; color: "black"; opacity: 0.6 }
        Rectangle { anchors.fill: parent; radius: 26; color: "#f0141418"; border.color: "#26ffffff"; border.width: 1 }
        ListView {
            id: list
            x: 20; y: 28; width: parent.width - 40; height: parent.height - 56
            interactive: false; clip: true; spacing: 4
            model: root.items.length
            currentIndex: root.last.sel || 0
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
            delegate: Item {
                readonly property var it: root.items[index] || {}
                readonly property bool foc: index === (root.last.sel || 0)
                width: list.width
                height: it.header ? 48 : 58
                Text {
                    visible: !!it.header
                    x: 16; anchors.bottom: parent.bottom; anchors.bottomMargin: 10
                    text: (it.header || "").toUpperCase()
                    color: "#a3a3ad"; font.pixelSize: 17; font.bold: true; font.letterSpacing: 2
                }
                Rectangle {
                    visible: !it.header
                    anchors.fill: parent; radius: 29
                    color: foc ? "white" : "transparent"
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Text {
                        x: 22; anchors.verticalCenter: parent.verticalCenter
                        width: parent.width - 80; elide: Text.ElideRight
                        text: it.label || ""
                        color: foc ? "#17151c" : "white"; font.pixelSize: 24; font.bold: foc
                    }
                    Text {   // choix en cours
                        visible: !!it.selected
                        anchors.right: parent.right; anchors.rightMargin: 24; anchors.verticalCenter: parent.verticalCenter
                        text: "✓"; color: foc ? "#17151c" : "white"; font.pixelSize: 26; font.bold: true
                    }
                }
            }
        }
    }
}

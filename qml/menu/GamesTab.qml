// TV menu, PC link tab: games streamed from a PC with Sunshine (Moonlight, gamestream.py). Not paired yet: a button
// that shows a code to type in Sunshine (menu/CodeDialog.qml); paired: its games in a grid of cards (box art)
import QtQuick
import "layout.js" as Layout
import ".."

Item {
    id: page
    required property var menu
    anchors.fill: parent
    visible: menu.tabId === "games"
    readonly property var g: menu.gs || ({})

    Item {   // pairing button
        visible: page.menu.gsCanPair()
        y: 290; width: 440; height: 74
        readonly property bool foc: menu.area === "content"
        scale: foc ? 1.05 : 1
        Behavior on scale { NumberAnimation { duration: 160 } }
        FocusFrame { active: parent.foc; radius: 37 }
        Rectangle { anchors.fill: parent; radius: 37; color: parent.foc ? menu.pal.surfaceFocus : menu.pal.surface }
        Text { anchors.centerIn: parent; text: menu.tr("Pair the box"); color: "white"; font.pixelSize: 25; font.bold: true }
    }
    Item {   // clip: what scrolls stops at the edge of the area (neither over the title nor over the help at the bottom)
        x: -53; y: 161; width: Layout.contentW + 80; height: Layout.listBottom - 161; clip: true
        GridView {
            visible: !!page.g.paired
            y: 15; x: 40; width: Layout.contentW; height: 2 * 400 + 27
            cellWidth: Layout.cardStep; cellHeight: 400
            interactive: false; clip: false; topMargin: 27
            model: (page.g.apps || []).length
            currentIndex: menu.gsSel
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
            Behavior on contentY { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
            delegate: Item {
                width: Layout.cardStep; height: 400
                readonly property real rel: y - GridView.view.contentY
                opacity: rel > -200 && rel < GridView.view.height - 200 ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 150 } }
                readonly property var a: (page.g.apps || [])[index] || {}
                VideoCard {
                    x: 13; y: 13
                    title: a.name || ""
                    thumb: a.art || ""
                    meta: ""
                    accent: menu.accent
                    focused: menu.area === "content" && index === menu.gsSel
                }
            }
        }
    }
}

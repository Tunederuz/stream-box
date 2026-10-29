// TV menu: action dialog (menu.modal: { title, items: [{ label, danger, ok }] }, focus menu.modalSel)
import QtQuick
import ".."

Item {
    required property var menu
    anchors.fill: parent
    opacity: menu.modal ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 160 } }
    Rectangle { anchors.fill: parent; color: "#05030a"; opacity: 0.6 }
    MouseArea {   // outside the dialog: Back; and nothing reaches the menu underneath
        anchors.fill: parent; enabled: !!menu.modal
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: menu.key("back")
        onWheel: function (w) { menu.key(w.angleDelta.y > 0 ? "up" : "down") }
    }
    Rectangle {
        id: sheet
        readonly property var items: menu.modal ? menu.modal.items : []
        width: 820; height: 150 + items.length * 92; radius: 28
        anchors.centerIn: parent
        color: menu.pal.sheet
        scale: menu.modal ? 1 : 0.92
        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutBack } }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.LeftButton | Qt.RightButton }   // (the sheet itself: no Back)
        Marquee { x: 44; y: 46; width: parent.width - 88; text: menu.modal ? menu.modal.title || "" : ""; pixelSize: 27; bold: true; running: !!menu.modal }
        Repeater {
            model: sheet.items.length
            Rectangle {
                readonly property bool foc: index === menu.modalSel
                x: 30; y: 112 + index * 92; width: sheet.width - 60; height: 76; radius: 38
                color: foc ? "white" : menu.pal.key
                Behavior on color { ColorAnimation { duration: 140 } }
                Text {
                    x: 40; anchors.verticalCenter: parent.verticalCenter
                    text: sheet.items[index] ? sheet.items[index].label : ""
                    color: parent.foc ? "#1a1020" : (sheet.items[index] && sheet.items[index].danger ? "#ff8f8f" : "white")
                    font.pixelSize: 26; font.bold: parent.foc
                }
                Tap { tv: menu; rightKey: "back"; enabled: !!menu.modal; onPick: menu.modalSel = index }
            }
        }
    }
}

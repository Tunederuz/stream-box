// TV menu: on-screen keyboard of the YouTube and Jellyfin search (keys: menu.kbKeys, focus: menu.kbRow, kbCol)
import QtQuick

Item {
    required property var menu
    anchors.fill: parent
    opacity: menu.kbOpen ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 160 } }
    Rectangle { anchors.fill: parent; color: "#05030a"; opacity: 0.6 }
    Rectangle {
        width: 1180; height: 690; radius: 30
        anchors.centerIn: parent
        color: menu.pal.sheet
        scale: menu.kbOpen ? 1 : 0.95
        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        Text { x: 48; y: 36; text: menu.tr("Search {service}", { service: menu.libTab ? menu.libName : "YouTube" }); color: menu.pal.label; font.pixelSize: 22; font.bold: true }
        Rectangle {   // typed text
            x: 44; y: 78; width: parent.width - 88; height: 76; radius: 18
            color: Qt.darker(menu.pal.sheet, 1.8); border.color: menu.pal.surfaceFocus; border.width: 2
            Text {
                x: 26; anchors.verticalCenter: parent.verticalCenter; width: parent.width - 52; elide: Text.ElideLeft
                text: menu.kbText + "▏"; color: menu.kbText ? "white" : "#8a85a0"; font.pixelSize: 34
            }
        }
        Column {
            x: 56; y: 182; spacing: 12
            Repeater {
                model: menu.kbKeys.length
                Row {
                    readonly property int r: index
                    spacing: 12
                    Repeater {
                        model: menu.kbKeys[r].length
                        Rectangle {
                            readonly property string label: menu.kbKeys[r][index]
                            readonly property bool foc: menu.kbRow === r && menu.kbCol === index
                            readonly property bool wide: label.length > 1
                            width: wide ? (r === 5 ? 348 : 312) : 96; height: 72; radius: 16   // 10 keys wide: 1068
                            color: foc ? "white" : label === "Search" ? menu.accent : menu.pal.key
                            scale: foc ? 1.06 : 1
                            Behavior on scale { NumberAnimation { duration: 120 } }
                            Text {
                                anchors.centerIn: parent; text: menu.tr(label)
                                color: parent.foc ? "#1a1020" : "white"; font.pixelSize: wide ? 26 : 32; font.bold: parent.foc
                            }
                        }
                    }
                }
            }
        }
    }
}

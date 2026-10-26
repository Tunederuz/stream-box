// TV menu: header of the tab (title, subtitle), weather and clock at the top right
import QtQuick
import "layout.js" as Layout

Item {
    required property var menu
    anchors.fill: parent

    Text { x: Layout.contentX; y: 100 - height / 2; text: menu.tr(menu.tabs[menu.tab].label); color: "white"; font.pixelSize: 41; font.bold: true }
    Text { x: Layout.contentX; y: 158 - height / 2; text: menu.subtitle(); color: "#b4afc2"; font.pixelSize: 25 }
    Row {
        anchors.right: parent.right; anchors.rightMargin: 80; y: 100 - height / 2; spacing: 28
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: !!(menu.ambient.weather && menu.ambient.weather.temp !== undefined)
            text: visible ? menu.ambient.weather.temp + "°  " + (menu.ambient.weather.text || "") : ""
            color: "#b4afc2"; font.pixelSize: 25
        }
        Text { text: Qt.formatTime(menu.now, "hh:mm"); color: "white"; font.pixelSize: 31 }
    }
}

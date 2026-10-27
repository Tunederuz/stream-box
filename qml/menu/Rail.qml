// TV menu: rail of tabs on the left (logo, "Home screen", tabs with the sliding pill), what plays on the TV, key help
import QtQuick
import ".."

Item {
    required property var menu
    anchors.fill: parent

    Rectangle { width: 400; height: parent.height; color: menu.pal.rail; opacity: 0.55
                Behavior on color { ColorAnimation { duration: 400 } } }
    Logo { x: 56; y: 62 }
    Text { x: 126; y: 88 - height / 2; text: "Stream Box"; color: "white"; font.pixelSize: 28; font.bold: true }
    Rectangle {   // pill: slides from one entry to the other
        x: 40; width: 320; height: 64; radius: 32
        y: menu.railHome ? 150 : 236 + menu.tab * menu.railStep
        color: "white"
        opacity: menu.area === "rail" ? 1 : 0.10
        Behavior on opacity { NumberAnimation { duration: 160 } }
        Behavior on y { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
    }
    Text {   // global: home screen, whatever the tab
        x: 78; y: 182 - height / 2
        text: menu.tr("⌂  Home screen")
        color: menu.railHome && menu.area === "rail" ? "#1a1020" : "#b4afc2"
        font.pixelSize: 25; font.bold: menu.railHome
    }
    Rectangle { x: 60; y: 225; width: 280; height: 1; color: "#33ffffff" }
    Repeater {
        model: menu.tabs.length
        Item {
            x: 40; y: 236 + index * menu.railStep; width: 320; height: 64
            readonly property bool cur: index === menu.tab
            readonly property bool pill: cur && menu.area === "rail" && !menu.railHome
            Rectangle {   // current tab, focus in the content or on "Home screen": dot in the tab's color
                visible: cur && !pill
                x: 20; anchors.verticalCenter: parent.verticalCenter
                width: 12; height: 12; radius: 6; color: menu.accent
            }
            Text {
                x: cur && !pill ? 48 : 38
                anchors.verticalCenter: parent.verticalCenter
                text: menu.tr(menu.tabs[index].label)
                color: pill ? "#1a1020" : (cur ? "white" : "#b4afc2")
                font.pixelSize: 25
                font.bold: cur
                Behavior on x { NumberAnimation { duration: 160 } }
            }
        }
    }
    Column {   // what plays on the TV
        x: 56; y: menu.height - 190; width: 310; spacing: 8
        visible: (menu.st.mode === "twitch" && !!menu.st.channel) || menu.st.mode === "media"
        Text { text: menu.tr("NOW ON THE TV"); color: "#a99fc0"; font.pixelSize: 16; font.bold: true; font.letterSpacing: 2 }
        Marquee {
            width: parent.width; pixelSize: 22; running: menu.isOpen
            // Channel outside the list (followed, swapped second stream): no live info, just its name
            readonly property var info: (menu.st.live || {})[menu.st.channel]
            text: menu.st.mode === "media" ? (menu.st.title || menu.tr("Video"))
                : (menu.st.channel || "") + (info ? "  ·  " + info.title : "")
        }
    }
    Text {
        x: 56; y: menu.height - 75
        text: menu.peekable() ? menu.tr("▲▼◀▶ move   ·   OK watch   ·   ▶ peek   ·   ≡ options   ·   Back go back   ·   Menu close")
                              : menu.tr("▲▼◀▶ move   ·   OK select   ·   ≡ options   ·   Back go back   ·   Menu close")
        color: "#8a85a0"; font.pixelSize: 19
    }
}

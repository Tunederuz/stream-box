// Ligne de réglage : titre de section, interrupteur animé, ou valeur réglable (◀ ▶ au focus)
import QtQuick

Item {
    id: root
    property var row: ({})
    property bool focused: false
    readonly property bool header: !!row.header
    width: 980
    height: header ? 68 : (row.hint ? 110 : 84)

    Text {
        visible: root.header
        x: 4
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: 8
        text: (root.row.header || "").toUpperCase()
        color: "#a99fc0"
        font.pixelSize: 20
        font.bold: true
        font.letterSpacing: 2
    }
    Item {
        visible: !root.header
        anchors.fill: parent
        scale: root.focused ? 1.02 : 1
        Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
        FocusFrame { active: root.focused; radius: 20 }
        Rectangle {
            anchors.fill: parent
            radius: 20
            color: root.focused ? "#3a2c4e" : "#2a2034"
            opacity: root.focused ? 1 : 0.85
            Behavior on color { ColorAnimation { duration: 160 } }
        }
        Column {
            x: 30
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            Text {
                text: root.row.label || ""
                color: root.row.danger ? "#ff8f8f" : "white"
                font.pixelSize: 27
            }
            Text {
                visible: !!root.row.hint
                text: root.row.hint || ""
                color: "#c2afb4"
                font.pixelSize: 20
            }
        }
        // Interrupteur : le bouton glisse, le fond passe au violet
        Rectangle {
            visible: root.row.toggle !== undefined
            anchors.right: parent.right
            anchors.rightMargin: 34
            anchors.verticalCenter: parent.verticalCenter
            width: 80; height: 44; radius: 22
            color: root.row.toggle ? "#9146ff" : "#5a5068"
            Behavior on color { ColorAnimation { duration: 180 } }
            Rectangle {
                y: 4
                x: root.row.toggle ? parent.width - width - 4 : 4
                width: 36; height: 36; radius: 18
                color: "white"
                Behavior on x { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
            }
        }
        Text {
            visible: root.row.value !== undefined
            anchors.right: parent.right
            anchors.rightMargin: 34
            anchors.verticalCenter: parent.verticalCenter
            text: (root.focused && root.row.step ? "◀  " : "") + (root.row.value || "") + (root.focused && root.row.step ? "  ▶" : "")
            color: "#f4e2e8"
            font.pixelSize: 25
        }
    }
}

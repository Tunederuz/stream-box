// Stream Box: scene of the app (ui.py): the video of the main player, the second stream (inset in a corner or
// side by side, animated transitions), and on top the QML interface (big TV menu), drawn in 1920x1080 and
// scaled to the screen. The videos keep their render size and are scaled down by the GPU
// (scale): switching from one layout to another stays smooth.
import QtQuick
import QtQuick.Effects
import StreamBox 1.0
import "../qml"

Item {
    id: stage
    readonly property bool split: pip.layout === "split"
    readonly property bool inset: pip.layout === "pip"
    readonly property real unit: width / 1920
    readonly property real insetScale: 0.3
    // Inset at the top, on the side opposite to the chat if it is at the top right
    readonly property bool insetLeft: pip.chatCorner === "tr"

    Item {
        id: mainBox
        width: stage.width
        height: stage.height
        transformOrigin: Item.TopLeft
        scale: stage.split ? 0.5 : 1
        y: stage.split ? stage.height / 4 : 0
        Behavior on scale { NumberAnimation { duration: 380; easing.type: Easing.InOutCubic } }
        Behavior on y { NumberAnimation { duration: 380; easing.type: Easing.InOutCubic } }
        MpvVideo {
            anchors.fill: parent
        }
    }

    Item {
        id: pipBox
        width: stage.width
        height: stage.height
        transformOrigin: Item.TopLeft
        opacity: pip.layout ? 1 : 0
        visible: opacity > 0
        scale: stage.split ? 0.5 : stage.insetScale
        x: stage.split ? stage.width / 2
           : stage.insetLeft ? 40 * stage.unit : stage.width * (1 - stage.insetScale) - 40 * stage.unit
        y: stage.split ? stage.height / 4 : 40 * stage.unit
        Behavior on opacity { NumberAnimation { duration: 250 } }
        Behavior on scale { NumberAnimation { duration: 380; easing.type: Easing.InOutCubic } }
        Behavior on x { NumberAnimation { duration: 380; easing.type: Easing.InOutCubic } }
        Behavior on y { NumberAnimation { duration: 380; easing.type: Easing.InOutCubic } }

        RectangularShadow {   // shadow of the inset, to set it apart from the main video
            anchors.fill: parent
            visible: stage.inset
            radius: 12 / stage.insetScale
            blur: 90
            color: "black"
            opacity: 0.8
        }
        Rectangle {   // black background while the second stream starts
            anchors.fill: parent
            color: "black"
        }
        MpvVideo {
            anchors.fill: parent
            which: "pip"
        }
        Rectangle {   // border of the inset (thickness compensated for the scaling)
            anchors.fill: parent
            visible: stage.inset
            color: "transparent"
            border.color: "#55ffffff"
            border.width: 3 / stage.insetScale
        }
    }

    Item {
        width: 1920
        height: 1080
        scale: Math.min(parent.width / 1920, parent.height / 1080)
        transformOrigin: Item.TopLeft
        // background changed in the menu: right away here too
        AmbientScreen { backdrop: tvMenu.st.backdrop || null; covered: tvMenu.isOpen && !tvMenu.powerOnly }
        ChatOverlay {}
        PollsOverlay {}
        LoadingOverlay {}
        PauseScreen {}
        InfoBar {}
        NextUp {}
        Toast {}
        TracksPanel {}
        InfoPanel {}
        KeyWizard {}
        TvMenu {
            id: tvMenu
            objectName: "tvMenu"
            // With the home screen: under it (the home screen is above the menu); the "Box" dialog alone stays on top
            z: box.ambientOn && !powerOnly ? -1 : 0
        }
        Notice {}
    }
}

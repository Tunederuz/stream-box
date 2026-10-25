// Stream Box : scène de l'appli (ui.py) : la vidéo du lecteur principal, le second stream (incrustation dans un coin ou
// côte à côte, transitions animées), et par-dessus l'interface en QML (grand menu de la TV), dessinée en 1920x1080 et
// mise à l'échelle de l'écran. Les vidéos gardent leur taille de rendu et sont réduites par la puce graphique
// (scale) : le passage d'une disposition à l'autre reste fluide.
import QtQuick
import QtQuick.Effects
import StreamBox 1.0
import "qml"

Item {
    id: stage
    readonly property bool split: pip.layout === "split"
    readonly property bool inset: pip.layout === "pip"
    readonly property real unit: width / 1920
    readonly property real insetScale: 0.3
    // Incrustation en haut, du côté opposé au chat s'il est en haut à droite
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

        RectangularShadow {   // ombre de l'incrustation, pour la détacher de la vidéo principale
            anchors.fill: parent
            visible: stage.inset
            radius: 12 / stage.insetScale
            blur: 90
            color: "black"
            opacity: 0.8
        }
        Rectangle {   // fond noir le temps que le second stream démarre
            anchors.fill: parent
            color: "black"
        }
        MpvVideo {
            anchors.fill: parent
            which: "pip"
        }
        Rectangle {   // liseré de l'incrustation (épaisseur compensée de la réduction)
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
        AmbientScreen { backdrop: tvMenu.st.backdrop || null }   // fond changé dans le menu : tout de suite ici aussi
        ChatOverlay {}
        PollsOverlay {}
        LoadingOverlay {}
        PauseScreen {}
        InfoBar {}
        NextUp {}
        Toast {}
        TracksPanel {}
        KeyWizard {}
        TvMenu {
            id: tvMenu
            objectName: "tvMenu"
        }
        Notice {}
    }
}

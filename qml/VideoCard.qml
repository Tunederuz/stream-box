// Carte vidéo (rediffusions, clips, historique) : miniature arrondie, progression, titre défilant au focus, infos
import QtQuick

Item {
    id: root
    property string title: ""
    property string meta: ""
    property string thumb: ""
    property real progress: 0
    property bool focused: false
    property color accent: "#9146ff"   // halo et progression : rouge sur l'onglet YouTube
    property string glyph: "▶"         // au centre, sans miniature (« + » : carte d'action, « Connecter mon compte »)
    width: 330
    height: 302
    z: focused ? 2 : 1

    Item {
        id: picture
        width: root.width
        height: 186
        scale: root.focused ? 1.06 : 1
        transformOrigin: Item.Bottom
        Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        FocusFrame { active: root.focused; radius: 16; glow: root.accent }
        RoundImage {
            anchors.fill: parent
            radius: 16
            placeholder: "#2a2034"
            // Rediffusion du live en cours : Twitch donne une image « en cours de traitement », le ▶ dessiné vaut mieux
            source: root.thumb.indexOf("404_processing") >= 0 ? "" : root.thumb
            Text {   // en attendant l'image (ou pour une rediffusion en cours, sans miniature)
                anchors.centerIn: parent
                z: -1
                text: "▶"
                color: "#5a5068"
                font.pixelSize: 42
            }
        }
        Text {   // carte d'action, sans miniature
            visible: root.glyph !== "▶"
            anchors.centerIn: parent
            text: root.glyph
            color: "white"
            font.pixelSize: 72
        }
    }
    Rectangle {
        visible: root.progress > 0
        y: 196
        width: root.width
        height: 6
        radius: 3
        color: "#4a3d5c"
        Rectangle {
            width: Math.max(6, parent.width * Math.min(1, root.progress))
            height: parent.height
            radius: 3
            color: root.accent
        }
    }
    Marquee {
        y: 214
        width: root.width
        text: root.title
        color: root.focused ? "white" : "#e0daea"
        pixelSize: 26
        bold: root.focused
        running: root.focused
    }
    Text {
        y: 258
        width: root.width
        text: root.meta
        color: "#a99fc0"
        font.pixelSize: 21
        elide: Text.ElideRight
    }
}

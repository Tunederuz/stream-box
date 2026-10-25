// Écran de pause (vidéo) : l'image s'assombrit, une grande icône pause au centre, et le résumé de la vidéo ou de
// l'épisode (remote.py, user-data/streambox/meta) au-dessus de la barre de lecture. Fondu à l'entrée et à la sortie.
import QtQuick
import QtQuick.Effects

Item {
    id: root
    anchors.fill: parent
    readonly property var b: { try { return JSON.parse(osd.bar || "{}") } catch (e) { return {} } }
    readonly property var meta: { try { return JSON.parse(osd.meta || "{}") } catch (e) { return {} } }
    readonly property bool shown: b.mode === "media" && !!b.bar && !!(b.playback || {}).pause
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 300; easing.type: Easing.InOutQuad } }

    Rectangle { anchors.fill: parent; color: "black"; opacity: 0.55 }
    Rectangle {   // icône pause
        anchors.horizontalCenter: parent.horizontalCenter
        y: 190
        width: 132; height: 132; radius: 66
        color: "#40ffffff"; border.color: "#80ffffff"; border.width: 2
        scale: root.shown ? 1 : 0.85
        Behavior on scale { NumberAnimation { duration: 300; easing.type: Easing.OutBack } }
        Row {
            anchors.centerIn: parent
            spacing: 16
            Rectangle { width: 16; height: 50; radius: 4; color: "white" }
            Rectangle { width: 16; height: 50; radius: 4; color: "white" }
        }
    }
    // Résumé, au-dessus du bandeau : sans les liens, adresses et hashtags des descriptions YouTube, 3 lignes au plus
    readonly property string overview: (meta.overview || "").replace(/https?:\/\/\S+|www\.\S+|\S+@\S+\.\S+|#\S+/g, "")
        .replace(/\s*[:|\-–—]+\s*(?=\s|$)/g, " ").replace(/\s+/g, " ").trim()
    Text {
        x: 96; width: 1100
        anchors.bottom: parent.bottom; anchors.bottomMargin: 580
        visible: root.overview.length > 20
        text: root.overview
        wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight
        color: "#e8e4ee"; font.pixelSize: 24; lineHeight: 1.15
        layer.enabled: true
        layer.effect: MultiEffect { shadowEnabled: true; shadowColor: "black"; shadowBlur: 0.7; shadowOpacity: 0.9 }
    }
}

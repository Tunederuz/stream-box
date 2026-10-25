// Panneau Infos d'une vidéo (appli Qt) : glisse depuis la droite, miniature ou affiche, titre, chaîne ou série, date,
// puis la description complète (user-data/streambox/meta de remote.py). Ouvert et piloté par stream-box.lua
// (user-data/streambox/info {open, scroll}) : ↑ ↓ font défiler la description, Retour / OK / ≡ ferment.
import QtQuick
import "fmt.js" as Fmt

Item {
    id: root
    anchors.fill: parent
    readonly property var st: { try { return JSON.parse(osd.info || "{}") } catch (e) { return {} } }
    readonly property var meta: { try { return JSON.parse(osd.meta || "{}") } catch (e) { return {} } }
    readonly property var b: { try { return JSON.parse(osd.bar || "{}") } catch (e) { return {} } }
    readonly property bool shown: !!st.open
    readonly property string title: (b.playback || {}).title || ""
    readonly property string details: (meta.source === "youtube" ? [meta.channel, meta.date, meta.views ? Fmt.big(meta.views) + " vues" : ""]
        : meta.source === "jellyfin" ? [meta.series, meta.episode, meta.year, meta.rating ? "★ " + Number(meta.rating).toFixed(1).replace(".", ",") : ""]
        : []).filter(function (t) { return !!t }).join("  ·  ")

    Rectangle {   // voile sur la vidéo
        anchors.fill: parent; color: "black"
        opacity: root.shown ? 0.45 : 0
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }
    Rectangle {
        id: panel
        width: 720; height: parent.height
        x: root.shown ? parent.width - width : parent.width + 20
        Behavior on x { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
        color: "#f2141018"
        Rectangle { width: 1; height: parent.height; color: "#30ffffff" }

        Column {
            id: head
            x: 56; y: 64; width: parent.width - 112
            spacing: 18
            Item {   // miniature (YouTube) ou image de l'épisode (Jellyfin), 16:9
                width: parent.width; height: width * 9 / 16
                visible: !!root.meta.thumb
                Rectangle { anchors.fill: parent; radius: 14; color: "#2a2430" }
                RoundImage { anchors.fill: parent; radius: 14; source: root.meta.thumb || ""; placeholder: "#2a2430" }
            }
            Text {
                width: parent.width; text: root.title
                color: "white"; font.pixelSize: 32; font.bold: true
                wrapMode: Text.WordWrap; maximumLineCount: 3; elide: Text.ElideRight
            }
            Text {
                visible: !!root.details
                width: parent.width; text: root.details
                color: "#c8c0d8"; font.pixelSize: 22; wrapMode: Text.WordWrap
            }
            Rectangle { width: parent.width; height: 1; color: "#30ffffff" }
        }
        // Description : défile par paliers de 4 lignes (↑ ↓), bornée à sa longueur
        Item {
            id: textArea
            x: 56; width: parent.width - 112
            anchors.top: head.bottom; anchors.topMargin: 18
            anchors.bottom: parent.bottom; anchors.bottomMargin: 70
            clip: true
            readonly property real maxScroll: Math.max(0, desc.implicitHeight - height)
            Text {
                id: desc
                width: parent.width
                y: -Math.min(textArea.maxScroll, (root.st.scroll || 0) * desc.font.pixelSize * 1.35 * 4)
                Behavior on y { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
                text: (root.meta.overview || "Pas de description.").replace(/\r/g, "")
                color: "#e8e4ee"; font.pixelSize: 23; lineHeight: 1.35
                wrapMode: Text.Wrap
            }
        }
        Text {   // aide en bas
            x: 56; anchors.bottom: parent.bottom; anchors.bottomMargin: 26
            text: (textArea.maxScroll > 0 ? "▲▼ faire défiler   ·   " : "") + "Retour fermer"
            color: "#8a85a0"; font.pixelSize: 19
        }
    }
}

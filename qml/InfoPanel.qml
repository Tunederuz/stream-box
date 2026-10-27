// Info panel of a video (Qt app): slides in from the right, thumbnail or poster, title, channel or series, date,
// then the full description (user-data/streambox/meta from remote.py). Opened and driven by stream-box.lua
// (user-data/streambox/info {open, scroll}): ↑ ↓ scroll the description, Back / OK / ≡ close.
import QtQuick
import "fmt.js" as Fmt
import "i18n.js" as I18n

Item {
    id: root
    anchors.fill: parent
    function tr(s, a) { return I18n.t(i18n.dict, s, a) }
    readonly property var st: { try { return JSON.parse(osd.info || "{}") } catch (e) { return {} } }
    readonly property var meta: { try { return JSON.parse(osd.meta || "{}") } catch (e) { return {} } }
    readonly property var b: { try { return JSON.parse(osd.bar || "{}") } catch (e) { return {} } }
    readonly property bool shown: !!st.open
    readonly property string title: (b.playback || {}).title || ""
    readonly property string details: (meta.source === "youtube" ? [meta.channel, meta.date, meta.views ? tr("{n} views", { n: Fmt.big(meta.views, tr) }) : ""]
        : meta.source === "jellyfin" || meta.source === "plex" ? [meta.series, meta.episode, meta.year, meta.rating ? "★ " + Fmt.decimal(meta.rating, tr) : ""]
        : []).filter(function (t) { return !!t }).join("  ·  ")

    Rectangle {   // veil over the video
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
            Item {   // thumbnail (YouTube) or episode picture (Jellyfin), 16:9
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
        // Description: scrolls by steps of 4 lines (↑ ↓), bounded by its length
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
                text: (root.meta.overview || root.tr("No description.")).replace(/\r/g, "")
                color: "#e8e4ee"; font.pixelSize: 23; lineHeight: 1.35
                wrapMode: Text.Wrap
            }
        }
        Text {   // help at the bottom
            x: 56; anchors.bottom: parent.bottom; anchors.bottomMargin: 26
            text: (textArea.maxScroll > 0 ? root.tr("▲▼ scroll") + "   ·   " : "") + root.tr("Back close")
            color: "#8a85a0"; font.pixelSize: 19
        }
    }
}

// Comments of a YouTube video (Qt app): slides in from the right like the Info panel; author, date, text, likes and
// replies of each, by relevance. The comments come from youtube.py (user-data/streambox/comments, pages of 20 read as
// the list goes down), the panel's state from stream-box.lua (user-data/streambox/comments_view {open, scroll}):
// ↑ ↓ go from one comment to the next, Back / OK / ≡ close.
import QtQuick
import "i18n.js" as I18n

Item {
    id: root
    anchors.fill: parent
    function tr(s, a) { return I18n.t(i18n.dict, s, a) }
    readonly property var st: { try { return JSON.parse(osd.commentsView || "{}") } catch (e) { return {} } }
    readonly property var c: { try { return JSON.parse(osd.comments || "{}") } catch (e) { return {} } }
    readonly property var b: { try { return JSON.parse(osd.bar || "{}") } catch (e) { return {} } }
    readonly property bool shown: !!st.open
    readonly property var items: c.items || []
    readonly property int scroll: st.scroll || 0
    onScrollChanged: list.positionViewAtIndex(scroll, ListView.Beginning)
    onShownChanged: if (shown) list.positionViewAtIndex(0, ListView.Beginning)

    Rectangle {   // veil over the video
        anchors.fill: parent; color: "black"
        opacity: root.shown ? 0.45 : 0
        Behavior on opacity { NumberAnimation { duration: 250 } }
    }
    Rectangle {
        id: panel
        width: 760; height: parent.height
        x: root.shown ? parent.width - width : parent.width + 20
        Behavior on x { NumberAnimation { duration: 300; easing.type: Easing.OutCubic } }
        color: "#f2141018"
        Rectangle { width: 1; height: parent.height; color: "#30ffffff" }

        Column {
            id: head
            x: 56; y: 64; width: parent.width - 112
            spacing: 10
            Text { text: root.tr("Comments"); color: "white"; font.pixelSize: 34; font.bold: true }
            Text {
                width: parent.width; text: (root.b.playback || {}).title || ""
                color: "#c8c0d8"; font.pixelSize: 21; elide: Text.ElideRight
            }
            Item { width: 1; height: 8 }
            Rectangle { width: parent.width; height: 1; color: "#30ffffff" }
        }
        Text {   // waiting for the first page, none, or YouTube unreachable
            x: 56; width: parent.width - 112
            anchors.top: head.bottom; anchors.topMargin: 30
            visible: root.items.length === 0
            text: root.c.error || (root.c.loading || !root.c.id ? root.tr("Loading comments…") : root.tr("No comments."))
            color: "#c8c0d8"; font.pixelSize: 23; wrapMode: Text.WordWrap
        }
        ListView {
            id: list
            x: 56; width: parent.width - 112
            anchors.top: head.bottom; anchors.topMargin: 18
            anchors.bottom: parent.bottom; anchors.bottomMargin: 70
            interactive: false; clip: true; spacing: 30
            model: root.items.length
            delegate: Row {
                readonly property var it: root.items[index] || {}
                width: list.width
                spacing: 18
                opacity: index < root.scroll ? 0.3 : 1
                RoundImage {
                    width: 48; height: 48; radius: 24
                    source: parent.it.avatar || ""; placeholder: "#2a2430"
                }
                Column {
                    width: parent.width - 66
                    spacing: 8
                    Text {
                        width: parent.width; elide: Text.ElideRight
                        text: (parent.parent.it.author || "") + (parent.parent.it.date ? "  ·  " + parent.parent.it.date : "")
                        color: "#b8b0c8"; font.pixelSize: 19; font.bold: true
                    }
                    Text {
                        width: parent.width
                        text: parent.parent.it.text || ""
                        color: "#ece8f2"; font.pixelSize: 23; lineHeight: 1.3
                        wrapMode: Text.Wrap; maximumLineCount: 12; elide: Text.ElideRight
                    }
                    Row {   // likes, replies
                        spacing: 10
                        visible: !!(parent.parent.it.likes || parent.parent.it.replies)
                        PlayerIcon { name: "like"; color: "#a8a0b8"; scale: 0.6; width: 22; height: 22; anchors.verticalCenter: parent.verticalCenter
                                     transformOrigin: Item.TopLeft }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: [parent.parent.parent.it.likes || "",
                                   parent.parent.parent.it.replies ? root.tr("{n} replies", { n: parent.parent.parent.it.replies }) : ""]
                                  .filter(function (t) { return !!t }).join("   ·   ")
                            color: "#a8a0b8"; font.pixelSize: 18
                        }
                    }
                }
            }
            footer: Item {
                width: list.width; height: root.c.loading && root.items.length ? 70 : 0
                Text {
                    visible: parent.height > 0
                    anchors.centerIn: parent
                    text: root.tr("Loading…"); color: "#8a85a0"; font.pixelSize: 20
                }
            }
        }
        Text {   // help at the bottom
            x: 56; anchors.bottom: parent.bottom; anchors.bottomMargin: 26
            text: (root.items.length > 1 ? root.tr("▲▼ scroll") + "   ·   " : "") + root.tr("Back close")
            color: "#8a85a0"; font.pixelSize: 19
        }
    }
}

// Comments of a YouTube video (Qt app): slides in from the right like the Info panel; author, date, text, likes and
// replies of each, by relevance. The comments come from youtube.py (user-data/streambox/comments, pages of 20 read as
// the list goes down; thread: the replies of the comment opened, pages of 10), the panel's state from stream-box.lua
// (user-data/streambox/comments_view {open, scroll, thread, tscroll}): ↑ ↓ go from one comment to the next (framed;
// the list scrolls to keep it in view), OK shows its replies in the same panel (the comment above them), Back goes
// back to the comments, then closes.
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
    readonly property int scroll: st.scroll || 0
    readonly property bool threadMode: shown && !!st.thread
    readonly property var parentComment: (c.items || [])[scroll] || {}
    // the replies of the comment opened, once youtube.py has them (another comment's until then)
    readonly property var thread: c.thread && c.thread.index === scroll ? c.thread : { items: [], loading: true }
    // Shown: the comments, or the comment opened then its replies
    readonly property var items: threadMode ? [parentComment].concat(thread.items || []) : (c.items || [])
    readonly property int sel: threadMode ? (st.tscroll || 0) + 1 : scroll   // framed item
    readonly property bool loading: threadMode ? !!thread.loading : !!c.loading
    // The list scrolls only to keep the selected item in view; from the top on opening (the comments, or the comment
    // opened above its replies), back on the comment opened when leaving its replies
    onSelChanged: list.positionViewAtIndex(sel, ListView.Contain)
    onThreadModeChanged: list.positionViewAtIndex(threadMode ? 0 : sel, threadMode ? ListView.Beginning : ListView.Contain)
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
            Text {
                text: root.threadMode ? root.tr("Replies") : root.tr("Comments")
                color: "white"; font.pixelSize: 34; font.bold: true
            }
            Text {
                width: parent.width; elide: Text.ElideRight
                text: root.threadMode ? root.tr("To {author}", { author: root.parentComment.author || "" })
                                      : (root.b.playback || {}).title || ""
                color: "#c8c0d8"; font.pixelSize: 21
            }
            Item { width: 1; height: 8 }
            Rectangle { width: parent.width; height: 1; color: "#30ffffff" }
        }
        Text {   // waiting for the first page, none, or YouTube unreachable
            x: 56; width: parent.width - 112
            anchors.top: head.bottom; anchors.topMargin: 30
            visible: root.shown && !root.threadMode && root.items.length === 0
            text: root.c.error || (root.c.loading || !root.c.id ? root.tr("Loading comments…") : root.tr("No comments."))
            color: "#c8c0d8"; font.pixelSize: 23; wrapMode: Text.WordWrap
        }
        ListView {
            id: list
            x: 40; width: parent.width - 80
            anchors.top: head.bottom; anchors.topMargin: 14
            anchors.bottom: parent.bottom; anchors.bottomMargin: 70
            interactive: false; clip: true; spacing: 12
            Behavior on contentY { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            model: root.items.length
            delegate: Item {
                id: entry
                readonly property var it: root.items[index] || {}
                readonly property bool reply: root.threadMode && index > 0
                readonly property bool foc: index === root.sel
                width: list.width
                height: body.height + 32
                Rectangle {   // selected; the comment opened, above its replies
                    x: entry.reply ? 40 : 0; width: parent.width - x; height: parent.height; radius: 18
                    color: entry.foc ? "#24ffffff" : root.threadMode && index === 0 ? "#10ffffff" : "transparent"
                    border.color: entry.foc ? "#40ffffff" : "transparent"; border.width: 1
                    Behavior on color { ColorAnimation { duration: 120 } }
                }
                Row {
                    id: body
                    x: (entry.reply ? 40 : 0) + 16; y: 16
                    width: parent.width - x - 16
                    spacing: 18
                    RoundImage {
                        width: entry.reply ? 40 : 48; height: width; radius: width / 2
                        source: entry.it.avatar || ""; placeholder: "#2a2430"
                    }
                    Column {
                        width: parent.width - 66
                        spacing: 8
                        Text {
                            width: parent.width; elide: Text.ElideRight
                            text: (entry.it.author || "") + (entry.it.date ? "  ·  " + entry.it.date : "")
                            color: "#b8b0c8"; font.pixelSize: 19; font.bold: true
                        }
                        Text {
                            width: parent.width
                            text: entry.it.text || ""
                            color: "#ece8f2"; font.pixelSize: entry.reply ? 22 : 23; lineHeight: 1.3
                            // the comment opened: a reminder, a few lines
                            wrapMode: Text.Wrap; maximumLineCount: root.threadMode && index === 0 ? 4 : 12; elide: Text.ElideRight
                        }
                        Row {   // likes, replies ("OK · n replies" on the selected comment)
                            spacing: 10
                            visible: !!(entry.it.likes || entry.it.replies)
                            PlayerIcon {
                                name: "like"; color: "#a8a0b8"; scale: 0.6; width: 22; height: 22
                                transformOrigin: Item.TopLeft; anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: [entry.it.likes || "",
                                       entry.it.replies && !root.threadMode
                                           ? (entry.foc ? root.tr("OK · {n} replies", { n: entry.it.replies })
                                                        : root.tr("{n} replies", { n: entry.it.replies })) : ""]
                                      .filter(function (t) { return !!t }).join("   ·   ")
                                color: entry.foc && entry.it.replies && !root.threadMode ? "white" : "#a8a0b8"
                                font.pixelSize: 18; font.bold: entry.foc && !!entry.it.replies && !root.threadMode
                            }
                        }
                    }
                }
            }
            footer: Item {   // the next page coming, or the first replies
                width: list.width; height: root.shown && root.loading && (root.items.length || root.threadMode) ? 70 : 0
                Text {
                    visible: parent.height > 0
                    anchors.centerIn: parent
                    text: root.threadMode && root.items.length === 1 ? root.tr("Loading replies…") : root.tr("Loading…")
                    color: "#8a85a0"; font.pixelSize: 20
                }
            }
        }
        Text {   // help at the bottom
            x: 56; anchors.bottom: parent.bottom; anchors.bottomMargin: 26
            text: (root.items.length > 1 ? root.tr("▲▼ scroll") + "   ·   " : "")
                  + (root.threadMode ? root.tr("Back comments") : root.tr("Back close"))
            color: "#8a85a0"; font.pixelSize: 19
        }
    }
}

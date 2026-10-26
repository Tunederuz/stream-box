// Polls and predictions box (Qt app), top center, away from the chat corners: remaining time, share of
// each choice (animated bars), winner, and the vote or bet made from the box.
import QtQuick
import QtQuick.Effects
import "fmt.js" as Fmt
import "i18n.js" as I18n

Item {
    id: root
    anchors.fill: parent
    function tr(s, a) { return I18n.t(i18n.dict, s, a) }
    readonly property var e: { try { return JSON.parse(osd.polls || "{}") } catch (x) { return {} } }
    readonly property var poll: e.poll || null
    readonly property var pred: e.prediction || null
    readonly property bool shown: osd.eventsOn && JSON.parse(osd.bar || "{}").mode === "twitch" && !!(poll || pred)
    property real now: Date.now() / 1000
    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 250 } }
    Timer { interval: 1000; repeat: true; running: root.visible; onTriggered: root.now = Date.now() / 1000 }

    Column {
        anchors.horizontalCenter: parent.horizontalCenter
        y: 34
        spacing: 14
        Repeater {
            model: [root.poll ? "poll" : "", root.pred ? "pred" : ""].filter(function (k) { return !!k })
            Item {
                readonly property bool isPoll: modelData === "poll"
                readonly property var ev: isPoll ? root.poll : root.pred
                readonly property var rows: isPoll ? ev.choices : ev.outcomes
                readonly property real total: rows.reduce(function (n, r) { return n + (isPoll ? r.votes : r.points) }, 0) || 1
                readonly property real remaining: (ev.ends_at || 0) - root.now
                width: 640
                height: 96 + rows.length * 50
                RectangularShadow { anchors.fill: parent; radius: 24; blur: 40; color: "black"; opacity: 0.5 }
                Rectangle { anchors.fill: parent; radius: 24; color: "#e6150f1e"; border.color: "#2affffff"; border.width: 1 }
                Text { x: 24; y: 18; text: isPoll ? root.tr("POLL") : root.tr("PREDICTION"); color: "#b67bff"; font.pixelSize: 17; font.bold: true; font.letterSpacing: 2 }
                Text {
                    anchors.right: parent.right; anchors.rightMargin: 24; y: 18
                    text: isPoll ? (ev.ended ? root.tr("Results") : remaining > 0 ? Fmt.clock(remaining) : root.tr("Counting…"))
                        : ev.status === "RESOLVED" ? root.tr("Result") : ev.status === "CANCELED" ? root.tr("Canceled")
                        : ev.status === "ACTIVE" && remaining > 0 ? root.tr("Bets: {time}", { time: Fmt.clock(remaining) })
                        : root.tr("Bets closed")
                    color: "#b4afc2"; font.pixelSize: 17
                }
                Text {
                    x: 24; y: 42; width: parent.width - 48; elide: Text.ElideRight
                    text: ev.title || ""; color: "white"; font.pixelSize: 24; font.bold: true
                }
                Repeater {
                    model: rows.length
                    Item {
                        readonly property var r: rows[index]
                        readonly property real share: (isPoll ? r.votes : r.points) / total
                        readonly property bool mine: isPoll ? ev.mine === r.id : !!(ev.mine && ev.mine.outcome === r.id)
                        readonly property bool best: isPoll ? (ev.ended && r.votes === Math.max.apply(null, rows.map(function (x) { return x.votes })))
                                                            : !!r.winner
                        x: 24; y: 84 + index * 50; width: parent.width - 48; height: 40
                        Rectangle { anchors.fill: parent; radius: 10; color: "#14ffffff"; border.color: mine ? "white" : "transparent"; border.width: 2 }
                        Rectangle {
                            height: parent.height; radius: 10
                            width: Math.max(10, parent.width * share)
                            color: isPoll ? "#9146ff" : r.color === "PINK" ? "#f5009b" : "#387aff"
                            opacity: best ? 0.9 : 0.55
                            Behavior on width { NumberAnimation { duration: 600; easing.type: Easing.OutCubic } }
                        }
                        Text {
                            x: 14; anchors.verticalCenter: parent.verticalCenter
                            width: parent.width * 0.55; elide: Text.ElideRight
                            text: (best ? "★ " : mine ? "✓ " : "") + r.title
                            color: "white"; font.pixelSize: 20; font.bold: best || mine
                        }
                        Text {
                            anchors.right: parent.right; anchors.rightMargin: 14; anchors.verticalCenter: parent.verticalCenter
                            text: root.tr("{n}%", { n: Math.round(share * 100) }) + "  ·  "
                                  + (isPoll ? Fmt.big(r.votes, root.tr) : root.tr("{n} pts", { n: Fmt.big(r.points, root.tr) }))
                                  + (mine && !isPoll && ev.mine.points
                                     ? "  ·  " + root.tr("your bet {n}", { n: Fmt.big(ev.mine.points, root.tr) }) : "")
                            color: "white"; font.pixelSize: 18
                        }
                    }
                }
            }
        }
    }
}

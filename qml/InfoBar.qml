// Bottom bar (Qt app), shown when stream-box.lua decides so (OK during a live, ←/→ or pause in a video):
// live (photo, title, game, viewers, live duration, time-shift buffer and "LIVE" or the delay) or playback bar of a
// video (title, channel or series, chapter, position, buffered part, chapter marks, YouTube preview above the
// cursor, seek in progress "+30 s" or scrubbing target, remaining time and end time, row of buttons). Slides up.
import QtQuick
import QtQuick.Effects
import "fmt.js" as Fmt
import "i18n.js" as I18n

Item {
    id: root
    anchors.fill: parent
    function tr(s, a) { return I18n.t(i18n.dict, s, a) }
    readonly property var b: { try { return JSON.parse(osd.bar || "{}") } catch (e) { return {} } }
    readonly property var pb: b.playback || {}
    readonly property bool live: b.mode === "twitch"
    readonly property var info: (b.live || {})[b.channel] || null
    readonly property var board: { try { return JSON.parse(osd.storyboard || "{}") } catch (e) { return {} } }
    readonly property bool shown: !!b.bar && (b.mode === "twitch" || b.mode === "media")
    property var avatars: ({})
    // Bar: in a live, the time-shift buffer (its right end is live); in a video, the duration
    readonly property real span: live ? (pb.window ? pb.window[1] - pb.window[0] : 0) : (pb.duration || 0)
    readonly property real at: live ? (pb.window ? (pb.pos || 0) - pb.window[0] : 0) : scrubbing ? fx.target : (pb.pos || 0)
    readonly property real delay: live && pb.window ? pb.window[1] - (pb.pos || 0) : 0
    // Bar color depending on the source: YouTube red, Jellyfin blue (link to its server: /Videos/…), Plex amber
    // (/library/parts/…), otherwise Twitch purple
    readonly property string source: live ? "twitch" : /youtube\.com|youtu\.be|googlevideo/.test(pb.path || "") ? "youtube"
        : /\/library\/parts\/\d+\//.test(pb.path || "") ? "plex"
        : /\/Videos\/|\/videos\/[0-9a-f]{32}|api_key=|MediaSourceId=/i.test(pb.path || "") ? "jellyfin" : "other"
    readonly property var colors: source === "youtube" ? ["#ff0033", "#ff4e45"]
        : source === "jellyfin" ? ["#1565c0", "#4a90e2"] : source === "plex" ? ["#e5a00d", "#f5c04a"] : ["#8a3ffc", "#b062ff"]
    // Video: info (remote.py: channel, series, episode…), chapters (mpv), buttons and seek (stream-box.lua)
    readonly property var meta: { try { return JSON.parse(osd.meta || "{}") } catch (e) { return {} } }
    readonly property var ctl: { try { return JSON.parse(osd.controls || "{}") } catch (e) { return {} } }
    readonly property var fx: { try { return JSON.parse(osd.seekfx || "{}") } catch (e) { return {} } }
    readonly property var chapters: pb.chapters || []
    readonly property string chapterTitle: {
        var c = chapters[pb.chapter]
        return c && chapters.length > 1 ? tr("Chapter {n}", { n: pb.chapter + 1 }) + (c.title && !/^Chapter \d+$/i.test(c.title) ? " · " + c.title : "") : ""
    }
    readonly property string details: (meta.source === "youtube" ? [meta.channel, meta.date, meta.views ? tr("{n} views", { n: Fmt.big(meta.views, tr) }) : ""]
        : meta.source === "jellyfin" || meta.source === "plex" ? [meta.year, meta.rating ? "★ " + Fmt.decimal(meta.rating, tr) : ""]   // series and episode: already in the title
        : []).concat([chapterTitle]).filter(function (t) { return !!t }).join("  ·  ")
    // Preview and "+30 s" bubble: only while seeking forward or back (not when the bar is just shown). Scrubbing (← →
    // in a video, stream-box.lua): the video is paused, the cursor, preview and offset stay on the target until OK / Back
    readonly property bool scrubbing: !live && fx.target !== undefined
    property bool seeking: false
    property int lastSeekN: -1
    onFxChanged: {
        if (fx.n !== undefined && fx.n !== lastSeekN) { lastSeekN = fx.n; seeking = true; seekEnd.restart() }
        if (!fx.text) seeking = false   // scrubbing over
    }
    Timer { id: seekEnd; interval: 1500; onTriggered: root.seeking = false }
    property date now: new Date()
    Timer { interval: 15000; repeat: true; running: root.visible; triggeredOnStart: true; onTriggered: root.now = new Date() }
    readonly property real remaining: Math.max(0, span - at)
    readonly property string endsAt: Qt.formatTime(new Date(now.getTime() + remaining * 1000), "hh:mm")

    opacity: shown ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { NumberAnimation { duration: 220 } }
    onShownChanged: if (shown && live && !avatars[b.channel]) loadAvatars()

    function loadAvatars() {
        var x = new XMLHttpRequest()
        x.onreadystatechange = function () {
            if (x.readyState === XMLHttpRequest.DONE && x.status === 200)
                try { root.avatars = JSON.parse(x.responseText).avatars || {} } catch (e) {}
        }
        x.open("GET", "http://127.0.0.1:8080/api/state")
        x.send()
    }

    Item {
        id: panel
        width: parent.width
        // In a video, taller: the YouTube preview shows between the title and the bar, buttons and their name below
        height: root.live ? 300 : 560
        y: root.shown ? parent.height - height : parent.height - height + 60
        Behavior on y { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }

        Rectangle {   // fade to black at the bottom of the screen
            anchors.fill: parent
            gradient: Gradient {
                // darker sooner: the title, at the top of the bar, stays readable on a bright picture
                GradientStop { position: 0.0; color: "#00000000" }
                GradientStop { position: 0.22; color: "#99000000" }
                GradientStop { position: 0.55; color: "#cc000000" }
                GradientStop { position: 1.0; color: "#ee000000" }
            }
        }

        // Header: streamer photo (live) or pause symbol (video), title, info line
        Rectangle {   // title selected (↑ from the buttons or the bar): OK opens the Info panel
            visible: opacity > 0
            opacity: !root.live && root.ctl.title ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 160 } }
            x: header.x - 24; y: header.y - 14
            // fitted to the title and the info line (the column itself is 1500 wide)
            width: Math.min(1500, Math.max(titleMetrics.width, detailsMetrics.width)) + 48 + infoHint.width + 40
            TextMetrics { id: titleMetrics; font.pixelSize: 31; font.bold: true; text: root.pb.title || "" }
            TextMetrics { id: detailsMetrics; font.pixelSize: 22; text: root.details }
            height: header.height + 28; radius: 20
            color: "#26ffffff"; border.color: "white"; border.width: 2
            Text {
                id: infoHint
                anchors.right: parent.right; anchors.rightMargin: 24; anchors.verticalCenter: parent.verticalCenter
                text: root.tr("OK · Info"); color: "white"; font.pixelSize: 21; font.bold: true
            }
        }
        Row {
            id: header
            // Video: just above the bar; while seeking, slides up to make room for the preview
            x: 96
            y: root.live ? 70 : preview.visible ? track.y - 22 - preview.height - 46 - height : 222
            Behavior on y { NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
            spacing: 22
            layer.enabled: true   // shadow under the texts, readable whatever the picture behind
            layer.effect: MultiEffect { shadowEnabled: true; shadowColor: "black"; shadowBlur: 0.7; shadowOpacity: 0.9; shadowVerticalOffset: 2 }
            Rectangle {
                visible: root.live
                width: 82; height: 82; radius: 41
                color: root.info ? "#ff4f5e" : "#4a3d5c"
                anchors.verticalCenter: parent.verticalCenter
                RoundImage {
                    anchors.centerIn: parent; width: 74; height: 74; circle: true; placeholder: "#4a3d5c"
                    source: root.avatars[root.b.channel] || ""
                }
            }
            Row {   // pause (video: PauseScreen.qml already shows the big icon)
                visible: false
                spacing: 9
                anchors.verticalCenter: parent.verticalCenter
                Rectangle { width: 12; height: 38; radius: 3; color: "white" }
                Rectangle { width: 12; height: 38; radius: 3; color: "white" }
            }
            Column {
                width: 1500
                anchors.verticalCenter: parent.verticalCenter
                spacing: 4
                Marquee {
                    width: parent.width
                    text: root.live ? (root.b.channel || "") + (root.info && root.info.title ? "  ·  " + root.info.title : "")
                                    : (root.pb.title || "")
                    pixelSize: 31; bold: true; running: root.shown
                }
                Text {   // video: channel or series, episode, chapter
                    visible: !root.live && !!root.details
                    width: parent.width; elide: Text.ElideRight
                    text: root.details
                    color: "#d0c8e0"; font.pixelSize: 22
                }
                Text {
                    visible: root.live && !!root.info
                    text: root.info ? [root.info.game, root.tr("{n} viewers", { n: Fmt.viewers(root.info.viewers, root.tr) }),
                                       root.info.started ? root.tr("live for {duration}", { duration: Fmt.since(root.info.started, root.tr) }) : ""]
                                      .filter(function (t) { return !!t }).join("  ·  ") : ""
                    color: "#d0c8e0"; font.pixelSize: 22
                }
            }
        }

        // Bar
        Item {
            id: track
            x: 96; y: root.live ? 200 : 340
            width: parent.width - 192
            height: 8
            readonly property real played: root.span > 0 ? Math.max(0, Math.min(1, root.at / root.span)) : 0
            Rectangle { anchors.fill: parent; radius: 4; color: "#40ffffff" }
            Rectangle {   // buffered part (video)
                visible: !root.live && root.span > 0 && (root.pb.cached || 0) > root.at
                height: parent.height; radius: 4; color: "#70ffffff"
                width: parent.width * Math.min(1, (root.pb.cached || 0) / Math.max(1, root.span))
            }
            Rectangle {
                height: parent.height; radius: 4
                width: parent.width * track.played
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: root.colors[0] }
                    GradientStop { position: 1; color: root.colors[1] }
                }
                Behavior on width { NumberAnimation { duration: 240 } }
            }
            Repeater {   // chapter marks
                model: root.live || root.span <= 0 ? 0 : root.chapters.length
                Rectangle {
                    visible: index > 0
                    x: track.width * Math.min(1, root.chapters[index].time / root.span) - 2
                    width: 4; height: 16; radius: 2; anchors.verticalCenter: parent.verticalCenter
                    color: "#d0ffffff"
                }
            }
            Rectangle {   // cursor
                width: 22; height: 22; radius: 11; color: "white"
                x: track.width * track.played - width / 2
                anchors.verticalCenter: parent.verticalCenter
                Behavior on x { NumberAnimation { duration: 240 } }
            }
            // YouTube preview above the cursor: one tile of the thumbnail sheet
            Item {
                id: preview
                readonly property var bd: root.board
                readonly property bool ok: !root.live && !!(bd.fragments && bd.fragments.length) && root.span > 0
                readonly property var tile: {
                    if (!ok) return null
                    var t = root.at, start = 0
                    for (var i = 0; i < bd.fragments.length; i++) {
                        var f = bd.fragments[i], d = f.duration || 1
                        if (t < start + d || i === bd.fragments.length - 1) {
                            var per = d / (bd.rows * bd.columns)
                            var idx = Math.min(bd.rows * bd.columns - 1, Math.floor((t - start) / per))
                            return { url: f.url, col: idx % bd.columns, row: Math.floor(idx / bd.columns) }
                        }
                        start += d
                    }
                    return null
                }
                readonly property real s: 280 / Math.max(1, bd.width || 160)
                visible: ok && !!tile && (root.seeking || root.scrubbing)
                width: (bd.width || 160) * s
                height: (bd.height || 90) * s
                x: Math.max(0, Math.min(track.width - width, track.width * track.played - width / 2))
                y: -height - 22   // as close as possible to the bar (the title moves up meanwhile)
                Rectangle { anchors.fill: parent; anchors.margins: -3; radius: 10; color: "white" }
                Item {
                    anchors.fill: parent
                    clip: true
                    Image {
                        source: preview.tile ? preview.tile.url : ""
                        asynchronous: true; cache: true
                        width: (preview.bd.width || 160) * preview.bd.columns * preview.s
                        height: (preview.bd.height || 90) * preview.bd.rows * preview.s
                        x: preview.tile ? -preview.tile.col * preview.width : 0
                        y: preview.tile ? -preview.tile.row * preview.height : 0
                    }
                }
            }
        }
        // Seek in progress above the cursor ("+30 s", total of quick presses), for a moment
        Rectangle {
            id: seekBubble
            property int lastN: -1
            visible: opacity > 0
            opacity: 0
            readonly property real cx: track.x + track.width * (root.span > 0 ? Math.min(1, root.at / root.span) : 0)
            x: Math.max(track.x, Math.min(track.x + track.width - width, cx - width / 2))
            // Sitting on the top edge of the preview, like a label; without a preview, above the title
            y: preview.visible ? track.y - 22 - preview.height - height / 2 : header.y - height - 20
            width: fxText.implicitWidth + 44; height: 58; radius: 29
            color: "#ee17151c"; border.color: root.colors[0]; border.width: 2
            Text { id: fxText; anchors.centerIn: parent; text: root.fx.text || ""; color: "white"; font.pixelSize: 28; font.bold: true }
            Connections {
                target: root
                function onFxChanged() {
                    if (!root.fx.text) { fxHide.stop(); seekBubble.opacity = 0; return }   // scrubbing over
                    if (root.fx.n !== undefined && root.fx.n !== seekBubble.lastN) {
                        seekBubble.lastN = root.fx.n
                        seekBubble.opacity = 1
                        if (root.scrubbing) fxHide.stop(); else fxHide.restart()
                    }
                }
            }
            Timer { id: fxHide; interval: 1100; onTriggered: seekBubble.opacity = 0 }
            Behavior on opacity { NumberAnimation { duration: 200 } }
        }
        Text {
            x: 96; y: track.y + 26
            visible: !root.live
            text: Fmt.clock(root.at) + "  /  " + Fmt.clock(root.span)
            color: "white"; font.pixelSize: 23
        }
        Text {
            anchors.right: track.right; y: track.y + 26
            text: root.live ? (root.delay < 4 ? root.tr("● LIVE") : "−" + Fmt.clock(root.delay))
                            : root.span > 0 ? "−" + Fmt.clock(root.remaining) + "   ·   " + root.tr("ends at {time}", { time: root.endsAt }) : ""
            color: root.live && root.delay < 4 ? "#ff4f5e" : "white"
            font.pixelSize: 23; font.bold: root.live && root.delay < 4
        }
        // Row of buttons (video), centered: ↓ to go there, ← → and OK. Round buttons with drawn icons (PlayerIcon),
        // Play / Pause bigger; the name of the selected button shows below. Dimmed while none is selected
        Item {
            visible: !root.live && (root.ctl.items || []).length > 0
            x: 0; y: track.y + 62
            width: parent.width; height: 140
            opacity: root.ctl.focus >= 0 ? 1 : 0.6
            Behavior on opacity { NumberAnimation { duration: 160 } }
            Row {
                id: buttons
                // Centered on Play / Pause (72-wide buttons, Play / Pause 92, 22 apart), whatever the buttons
                // on either side (Quality, Next episode…)
                readonly property int playIndex: Math.max(0, (root.ctl.items || []).map(function (i) { return i.id }).indexOf("play"))
                x: parent.width / 2 - playIndex * (72 + spacing) - 46
                spacing: 22
                Repeater {
                    model: (root.ctl.items || []).length
                    Item {
                        readonly property var it: root.ctl.items[index] || {}
                        readonly property bool foc: index === root.ctl.focus
                        readonly property bool big: it.id === "play"
                        width: big ? 92 : 72; height: 92
                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width; height: width; radius: width / 2
                            color: parent.foc ? "white" : "#2effffff"
                            border.color: parent.foc ? "white" : "#40ffffff"; border.width: 1
                            scale: parent.foc ? 1.1 : 1
                            Behavior on scale { NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
                            Behavior on color { ColorAnimation { duration: 140 } }
                            PlayerIcon {
                                anchors.centerIn: parent
                                // −10 / +10: thin circle, enlarged to fill the button like the other icons
                                scale: parent.parent.big ? 1.25 : (parent.parent.it.id === "back" || parent.parent.it.id === "fwd") ? 1.4 : 1
                                name: parent.parent.it.id === "play" ? (root.pb.pause ? "play" : "pause") : (parent.parent.it.id || "")
                                color: parent.parent.foc ? "#17151c" : "white"
                            }
                        }
                        Text {   // name of the selected button
                            visible: parent.foc
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: parent.height + 12
                            text: parent.it.label || ""
                            color: "white"; font.pixelSize: 21; font.bold: true
                        }
                    }
                }
            }
            Text {
                visible: root.ctl.focus < 0
                anchors.left: buttons.right; anchors.leftMargin: 26
                anchors.verticalCenter: buttons.verticalCenter
                text: root.tr("↓ controls")
                color: "#a0ffffff"; font.pixelSize: 20
            }
        }
    }
}

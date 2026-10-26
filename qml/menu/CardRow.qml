// Horizontal row of cards (Replays, YouTube, Jellyfin, found channels): card-by-card scrolling, the row staying
// left-aligned (and not the minimal scroll, which left cards cut at the edge of the rail or the screen).
// The caller binds view.model (an item count: the delegate reads the caller's array), view.currentIndex and
// view.delegate directly on the ListView, as before the split: a binding re-evaluated with the same value still
// rewrites currentIndex after the ListView reset it (row changed), which a forwarding property would swallow.
// The delegate hides outside the target window:
//     opacity: index >= ListView.view.first && index < ListView.view.first + ListView.view.fits ? 1 : 0
import QtQuick

Item {   // clip on the left, at the edge of the content: a scrolling card doesn't slide under the rail
    id: root
    // Video cards by default (layout.js: cardH, cardStep). Literal values on purpose, set as soon as the row is created:
    // the caller's currentIndex arrives before the bindings of this file, and a row whose width or step was not
    // known yet fitted no card and lost its first scroll
    property int cardHeight: 363
    property int spacing: 26
    property int step: 482                      // card width and spacing
    property real listY: 50                     // top of the cards: room above for the focus glow
    property alias view: list
    x: -28; width: 1512; height: cardHeight + 80; clip: true
    ListView {
        id: list
        y: root.listY; x: -12; width: 1460; height: root.cardHeight   // 3 cards up to 40 px from the right edge
        orientation: ListView.Horizontal; spacing: root.spacing; interactive: false; clip: false
        leftMargin: 40
        property int first: 0
        readonly property int fits: Math.floor((width - leftMargin + spacing) / root.step)
        onCurrentIndexChanged: {
            // -1 while the row reloads (empty list): ignored, otherwise the row stayed shifted by one card
            if (currentIndex < 0 || fits <= 0) return
            if (currentIndex < first) first = currentIndex
            else if (currentIndex >= first + fits) first = currentIndex - fits + 1
            contentX = -leftMargin + first * root.step
        }
        Behavior on contentX { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
    }
}

// TV menu, History tab: videos played on the TV, in a grid of video cards (3 columns, 2 rows on screen)
import QtQuick
import "layout.js" as Layout
import ".."
import "../fmt.js" as Fmt

Item {   // clip: what scrolls stops at the edge of the area (neither over the title nor over the help at the bottom)
    required property var menu
    x: -53; y: 161; width: Layout.contentW + 80; height: menu.height - 85 - 161; clip: true
    SkeletonRows {   // the history not read yet: the grid's first two rows
        visible: menu.tabId === "history" && menu.history === null
        x: 53; y: 55; rows: 2; titles: false; spacing: 400 - Layout.cardH
    }
    GridView {
        visible: menu.tabId === "history"
        y: 15; x: 40; width: Layout.contentW; height: 2 * 400 + 27
        cellWidth: Layout.cardStep; cellHeight: 400
        interactive: false; clip: false; topMargin: 27
        model: (menu.history || []).length
        currentIndex: menu.histSel
        onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
        Behavior on contentY { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }
        delegate: Item {
            width: Layout.cardStep; height: 400
            readonly property real rel: y - GridView.view.contentY
            opacity: rel > -200 && rel < GridView.view.height - 200 ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 150 } }
            readonly property var e: (menu.history || [])[index] || {}
            VideoCard {
                x: 13; y: 13
                title: e.title || ""
                thumb: e.thumb || ""
                meta: menu.tr(menu.kinds[e.kind] || "") + (e.finished ? " · " + menu.tr("watched")
                      : e.duration > 0 ? " · " + Fmt.clock(e.position) + " / " + Fmt.clock(e.duration) : "")
                progress: e.finished ? 1 : (Fmt.resumable(e.position, e.duration, e.finished) && e.duration > 0 ? e.position / e.duration : 0)
                accent: menu.accent
                focused: menu.area === "content" && index === menu.histSel
            }
        }
    }
}

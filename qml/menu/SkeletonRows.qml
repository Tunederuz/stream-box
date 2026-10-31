// Rows of video cards while a tab or a row loads (skeleton) instead of a "Loading…" text: `rows` rows of 3 cards,
// each with the bar of its title when `titles` (the row's own title not known yet), placed like CardRow's cards
import QtQuick
import "layout.js" as Layout
import ".."

Column {
    id: root
    property int rows: 1
    property bool titles: true
    spacing: Layout.rowH - Layout.cardH - (titles ? 50 : 0)
    Repeater {
        model: root.rows
        Column {
            spacing: 28
            Rectangle { visible: root.titles; width: 260; height: 22; radius: 11; color: "#2a2034"; opacity: 0.8 }
            Row {
                spacing: Layout.cardStep - Layout.cardW
                Repeater { model: 3; SkeletonCard { delay: index * 150 } }
            }
        }
    }
}

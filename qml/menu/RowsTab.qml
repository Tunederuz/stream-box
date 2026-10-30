// TV menu, Settings tab: list of rows (section titles, switches, values changed with ◀ ▶), from menu.settingsRows():
// the list of sections (narrower: box status and QR code beside it, SystemStatus) or the open section's rows
import QtQuick
import ".."

Item {   // clip: what scrolls stops at the edge of the area (neither over the title nor over the help at the bottom)
    required property var menu
    readonly property int listW: menu.section ? 980 : 810
    visible: menu.tabId === "settings"
    x: -40; y: 165; width: listW + 80; height: 830; clip: true
    ListView {
        id: rowsView
        visible: menu.tabId === "settings"
        readonly property var rows: !visible ? [] : menu.settingsRows()
        readonly property var sel: menu.selectable(rows)
        readonly property int focusedRow: menu.area === "content" ? (sel[menu.setSel] ?? -1) : -1
        readonly property string section: menu.section
        y: 15; x: 40; width: parent.listW; height: 800   // stops above the help at the bottom
        spacing: 10; interactive: false; clip: false; topMargin: 30
        model: rows.length
        onFocusedRowChanged: if (focusedRow >= 0) positionViewAtIndex(focusedRow, ListView.Contain)
        onSectionChanged: positionViewAtIndex(Math.max(0, focusedRow), ListView.Contain)   // the page changed
        Behavior on contentY { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        delegate: SettingRow {
            width: rowsView.width
            readonly property real rel: y - rowsView.contentY
            // a row cut at the top would cover the subtitle: hidden; at the bottom, shown while half of it is in view
            opacity: rel > -4 && rel + height / 2 < rowsView.height ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 150 } }
            row: rowsView.rows[index] || {}
            pal: menu.pal
            focused: index === rowsView.focusedRow
        }
    }
}

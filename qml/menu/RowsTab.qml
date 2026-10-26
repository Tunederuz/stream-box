// TV menu, Settings and System tabs: list of rows (section titles, switches, values changed with ◀ ▶), one
// instance per tab (which: "settings" or "system"; rows from menu.settingsRows() or menu.systemRows())
import QtQuick
import ".."

Item {   // clip: what scrolls stops at the edge of the area (neither over the title nor over the help at the bottom)
    required property var menu
    required property string which
    visible: menu.tabId === which
    x: -40; y: 165; width: (which === "settings" ? 980 : 810) + 80; height: 830; clip: true
    ListView {
        id: rowsView
        visible: menu.tabId === which
        readonly property var rows: !visible ? [] : which === "settings" ? menu.settingsRows() : menu.systemRows()
        readonly property var sel: menu.selectable(rows)
        readonly property int focusedRow: menu.area === "content" ? (sel[which === "settings" ? menu.setSel : menu.sysSel] ?? -1) : -1
        y: 15; x: 40; width: which === "settings" ? 980 : 810; height: 800   // stops above the help at the bottom
        spacing: 10; interactive: false; clip: false; topMargin: 30
        model: rows.length
        onFocusedRowChanged: if (focusedRow >= 0) positionViewAtIndex(focusedRow, ListView.Contain)
        Behavior on contentY { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        delegate: SettingRow {
            width: rowsView.width
            readonly property real rel: y - rowsView.contentY
            opacity: rel > -height / 2 && rel + height / 2 < rowsView.height ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 150 } }
            row: rowsView.rows[index] || {}
            pal: menu.pal
            focused: index === rowsView.focusedRow
        }
    }
}

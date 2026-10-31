// TV menu, YouTube, Jellyfin and Plex tabs (same page, separate state: menu.mRow, mSel…): search row, then horizontal
// rows of cards built by the addons (menu.mediaRows(): GET /api/rows; found channels as round pictures, style
// "channels"); each card brings its info line
import QtQuick
import "layout.js" as Layout
import ".."

Item {
    id: page
    required property var menu
    anchors.fill: parent
    visible: menu.rowsTab
    readonly property var rows: visible ? menu.mediaRows() : []
    // Fixed-height rows; vertical scrolling to keep the chosen row on screen
    readonly property real scrollY: Math.max(0, (menu.mRow - 1) * Layout.rowH)
    Item {   // search row
        y: 200; width: 760; height: 66
        readonly property bool foc: menu.area === "content" && menu.mRow === 0 && !menu.kbOpen
        scale: foc ? 1.03 : 1
        Behavior on scale { NumberAnimation { duration: 160 } }
        FocusFrame { active: parent.foc; radius: 35; glow: menu.accent }
        Rectangle { anchors.fill: parent; radius: 35; color: parent.foc ? menu.pal.surfaceFocus : menu.pal.surface }
        Text {
            x: 34; anchors.verticalCenter: parent.verticalCenter
            text: menu.searchLabel()
            color: "white"; font.pixelSize: 27
        }
    }
    Text {
        visible: menu.libTab ? !!menu.lib.home && !menu.lib.home.configured && !menu.lib.home.error
                            : !!menu.lib.home && !menu.lib.home.channels && !menu.lib.search && !menu.lib.home.authorized
        y: 320; text: menu.tabId === "plex" ? menu.tr("Plex isn't connected to the box: Settings → Accounts and links → Plex.")
                    : menu.libTab ? menu.tr("Jellyfin isn't connected to the box: Settings → Accounts and links → Jellyfin.")
                                 : menu.tr("Add favorite channels: Options on a video, or search.")
        color: "#b4afc2"; font.pixelSize: 27
    }
    Item {   // clip: what scrolls stops at the edge of the area (neither over the title nor over the help at the bottom)
        x: -40; y: 276; width: parent.width + 80; height: menu.height - 85 - 276; clip: true
        Item {   // rows, below the search row
            x: 40; y: 10; width: parent.width - 80; height: menu.height - 286
            SkeletonRows {   // the tab's lists not read yet
                visible: page.visible && !menu.lib.home
                y: 10; rows: 2; shade: menu.pal.surface
            }
            Repeater {
                model: Math.max(0, page.rows.length - 1)
                Item {
                    readonly property int r: index + 1
                    readonly property var row: page.rows[r]
                    y: index * Layout.rowH - page.scrollY
                    Behavior on y { NumberAnimation { duration: 280; easing.type: Easing.OutCubic } }
                    opacity: index >= Math.max(0, menu.mRow - 1) && index < Math.max(0, menu.mRow - 1) + 2 ? 1 : 0   // target rows
                    // Cards created (and thumbnails loaded) only for the target rows and their neighbors
                    readonly property bool near: index >= Math.max(0, menu.mRow - 1) - 1 && index < Math.max(0, menu.mRow - 1) + 3
                    Behavior on opacity { NumberAnimation { duration: 180 } }
                    width: Layout.contentW; height: Layout.rowH
                    Row {
                        spacing: 14
                        RoundImage { visible: !!(row && row.avatar); width: 40; height: 40; circle: true; source: row && row.avatar ? row.avatar : "" }
                        Text { anchors.verticalCenter: parent.verticalCenter; text: row ? row.title : ""; color: "#d0c8e0"; font.pixelSize: 24; font.bold: true }
                    }
                    readonly property bool waiting: !!row && row.items.length === 0 && !!row.loading
                    SkeletonRows { visible: parent.waiting && near; y: 60; titles: false; shade: menu.pal.surface }   // where its cards will be
                    Text {
                        visible: !!row && row.items.length === 0 && !parent.waiting
                        y: 70; text: row && row.key === "search" ? menu.tr("No results")
                                   : row && row.error ? menu.tr("{service} unreachable for now", { service: menu.serviceName })
                                   : menu.tr("Nothing here")
                        color: "#8a85a0"; font.pixelSize: 24
                    }
                    CardRow {   // found channels: round picture, name, info line (subscribers, "favorite": saved)
                            view.visible: !!row && row.style === "channels"
                        y: 10; listY: 40; cardHeight: 302; spacing: 30; step: 270
                        view.model: view.visible && near ? row.items.length : 0
                        view.currentIndex: view.visible ? (menu.mSel[row.key] || 0) : 0
                        view.delegate: Item {
                            readonly property var c: row.items[index] || {}
                            readonly property bool foc: menu.area === "content" && menu.mRow === r && index === (menu.mSel[row.key] || 0)
                            width: 240; height: 302
                            opacity: index >= ListView.view.first && index < ListView.view.first + ListView.view.fits ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: 90 } }
                            z: foc ? 2 : 1
                            Item {
                                x: 30; y: 6; width: 180; height: 180
                                scale: parent.foc ? 1.06 : 1
                                Behavior on scale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
                                FocusFrame { active: parent.parent.foc; radius: 90; glow: menu.accent }
                                RoundImage {
                                    anchors.fill: parent; circle: true; placeholder: "#2a2034"; source: c.thumb || ""
                                    Text { anchors.centerIn: parent; z: -1; text: (c.title || "?").charAt(0).toUpperCase(); color: "#d0c8e0"; font.pixelSize: 64; font.bold: true }
                                }
                            }
                            Text {
                                y: 206; width: parent.width; horizontalAlignment: Text.AlignHCenter; elide: Text.ElideRight
                                text: c.title || ""; color: "white"; font.pixelSize: 25; font.bold: parent.foc
                            }
                            Text {
                                y: 242; width: parent.width; horizontalAlignment: Text.AlignHCenter
                                text: c.meta || ""
                                color: c.saved ? "#ff6b7f" : "#b4afc2"; font.pixelSize: 20
                            }
                        }
                    }
                    CardRow {
                            view.visible: !!row && row.style !== "channels"
                        y: 10
                        view.model: view.visible && near ? row.items.length : 0
                        view.currentIndex: view.visible ? (menu.mSel[row.key] || 0) : 0
                        view.delegate: VideoCard {
                            readonly property var it: row.items[index] || {}
                            opacity: index >= ListView.view.first && index < ListView.view.first + ListView.view.fits ? 1 : 0   // target window
                            Behavior on opacity { NumberAnimation { duration: 90 } }
                            title: it.title || ""
                            thumb: it.thumb || ""
                            meta: menu.cardMeta(row, it)
                            glyph: it.glyph || (it.more ? "+" : "▶")
                            progress: it.progress || 0
                            accent: menu.accent
                            focused: menu.area === "content" && menu.mRow === r && index === (menu.mSel[row.key] || 0)
                        }
                    }
                }
            }
        }
    }
}

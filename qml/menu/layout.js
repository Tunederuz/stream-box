// Layout of the TV menu in 1920x1080, numbers shared by TvMenu.qml and its components (qml/menu/). CardRow.qml keeps
// literal copies of cardH and cardStep (see there).
.pragma library

var contentX = 460      // header and tab content, right of the rail
var contentW = 1460     // tab content: up to the right edge of the screen
var listBottom = 995    // scrolling areas stop above the help at the bottom
var cardW = 456         // VideoCard: 3 per row (Replays, YouTube, Jellyfin, History)
var cardH = 363         // its height: 16:9 thumbnail, title, info
var cardStep = 482      // card and spacing in a row, column of History
var rowH = 430          // row of cards: one full row, the top of the next one showing
var bannerH = 300      // Live tab: banner of the chosen streamer (16:9 picture, then its live)
var cellW = 356         // streamer grid (Live, Following): StreamerCard and its margins
var cellH = 176

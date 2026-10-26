// Interface language for QML (see i18n.py). Each QML file defines
//     function tr(s, a) { return I18n.t(i18n.dict, s, a) }
// so that texts written in English update by themselves when the language changes (i18n.dict is a context property
// set by ui.py). Placeholders: tr("Connected: {login}", { login: name }).
.pragma library

function t(dict, s, a) {
    var out = (dict && dict[s]) || s
    if (a) for (var k in a) out = out.split("{" + k + "}").join(a[k])
    return out
}

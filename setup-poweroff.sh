#!/usr/bin/env bash
# Stream Box : autorise media (la télécommande web) à éteindre la box sans mot de passe,
# même si quelqu'un d'autre est connecté (SSH…). À lancer avec sudo.
set -euo pipefail
cat > /etc/polkit-1/rules.d/50-stream-box.rules << 'RULES'
// Stream Box : le bouton d'extinction de la télécommande (utilisateur media)
polkit.addRule(function (action, subject) {
    if (subject.user == "media" &&
        (action.id == "org.freedesktop.login1.power-off" ||
         action.id == "org.freedesktop.login1.power-off-multiple-sessions" ||
         action.id == "org.freedesktop.login1.power-off-ignore-inhibit")) {
        return polkit.Result.YES;
    }
});
RULES
chmod 644 /etc/polkit-1/rules.d/50-stream-box.rules
echo "Règle polkit installée."

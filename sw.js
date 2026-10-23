// Service worker minimal : Chrome en a besoin pour proposer l'installation (en HTTPS uniquement).
// Pas de cache : la télécommande n'a de sens que quand la box répond.
self.addEventListener("fetch", () => {});

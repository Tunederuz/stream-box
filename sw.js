// Minimal service worker: Chrome needs one to offer installation (HTTPS only).
// No cache: the companion app only makes sense when the box responds.
self.addEventListener("fetch", () => {});

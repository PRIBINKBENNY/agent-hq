# Mobile and desktop apps (updated 2026-10-18)
- Mobile default for a JS/TS developer: React Native with Expo (Expo is now how most React Native is built; the New
  Architecture is standard in current Expo SDKs). Choose Flutter when pixel-identical UI across platforms or
  desktop/web/embedded targets from one codebase matter.
- Desktop: Tauri 2 (small, Rust core, web UI; also targets mobile) or Electron when a Node-heavy stack is needed.
- Free distribution paths: Expo Go / EAS free tier for testing, PWAs for zero-cost installs, GitHub Releases for desktop.
- Always ship: README with run steps, a smoke test, and screenshots for the portfolio.
Sources: pkgpulse.com (React Native vs Flutter vs Expo 2026), groovyweb.co (React Native vs Flutter vs Expo vs Lynx 2026),
softteco.com (React Native vs Flutter 2026). Market-share figures conflict between sources; do not quote them.

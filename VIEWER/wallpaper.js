(function setupBibliographyWallpaper() {
  const storageKey = "bibliography-wallpaper";
  const transparencyKey = "bibliography-wallpaper-transparency";
  const wallpapers = {
    marina: "wallpapers/marina.jpg",
    rpcs: "wallpapers/rpcs.jpeg",
  };

  function wallpaperUrl(value) {
    if (wallpapers[value]) return wallpapers[value];
    if (/^custom\/[a-z0-9_]+\.(?:jpg|png|webp)$/i.test(value || "")) {
      return `wallpapers/${value}`;
    }
    return "";
  }

  function currentWallpaper() {
    try {
      const value = localStorage.getItem(storageKey) || "default";
      return value === "default" || wallpaperUrl(value) ? value : "default";
    } catch (error) {
      return "default";
    }
  }

  function currentTransparency() {
    try {
      const stored = localStorage.getItem(transparencyKey);
      if (stored === null) return 76;
      const value = Number(stored);
      return Number.isFinite(value) && value >= 0 && value <= 95 ? value : 76;
    } catch (error) {
      return 76;
    }
  }

  function applyWallpaper(value) {
    const selected = value === "default" || wallpaperUrl(value) ? value : "default";
    if (selected === "default") {
      document.body.style.removeProperty("background-image");
      document.body.style.removeProperty("background-position");
      document.body.style.removeProperty("background-size");
      document.body.style.removeProperty("background-attachment");
      document.body.style.removeProperty("background-repeat");
      return;
    }
    const overlay = currentTransparency() / 100;
    document.body.style.backgroundImage =
      `linear-gradient(rgba(248, 244, 239, ${overlay}), rgba(248, 244, 239, ${overlay})), url("${wallpaperUrl(selected)}")`;
    document.body.style.backgroundPosition = "center";
    document.body.style.backgroundSize = "cover";
    document.body.style.backgroundAttachment = "fixed";
    document.body.style.backgroundRepeat = "no-repeat";
  }

  function saveWallpaper(value) {
    const selected = value === "default" || wallpaperUrl(value) ? value : "default";
    try {
      localStorage.setItem(storageKey, selected);
    } catch (error) {
      // The visual choice still applies for this page when storage is unavailable.
    }
    applyWallpaper(selected);
  }

  function saveTransparency(value) {
    const selected = Math.min(95, Math.max(0, Number(value) || 0));
    try {
      localStorage.setItem(transparencyKey, String(selected));
    } catch (error) {
      // The visual choice still applies for this page when storage is unavailable.
    }
    applyWallpaper(currentWallpaper());
  }

  window.bibliographyWallpaper = {
    current: currentWallpaper,
    apply: applyWallpaper,
    save: saveWallpaper,
    currentTransparency,
    saveTransparency,
  };
  applyWallpaper(currentWallpaper());
})();

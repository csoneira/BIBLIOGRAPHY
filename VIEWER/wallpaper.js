(function setupBibliographyWallpaper() {
  const storageKey = "bibliography-wallpaper";
  const wallpapers = {
    marina: "wallpapers/marina.jpg",
    rpcs: "wallpapers/rpcs.jpeg",
  };

  function currentWallpaper() {
    try {
      const value = localStorage.getItem(storageKey) || "default";
      return value === "default" || wallpapers[value] ? value : "default";
    } catch (error) {
      return "default";
    }
  }

  function applyWallpaper(value) {
    const selected = value === "default" || wallpapers[value] ? value : "default";
    if (selected === "default") {
      document.body.style.removeProperty("background-image");
      document.body.style.removeProperty("background-position");
      document.body.style.removeProperty("background-size");
      document.body.style.removeProperty("background-attachment");
      document.body.style.removeProperty("background-repeat");
      return;
    }
    document.body.style.backgroundImage =
      `linear-gradient(rgba(248, 244, 239, 0.76), rgba(248, 244, 239, 0.76)), url("${wallpapers[selected]}")`;
    document.body.style.backgroundPosition = "center";
    document.body.style.backgroundSize = "cover";
    document.body.style.backgroundAttachment = "fixed";
    document.body.style.backgroundRepeat = "no-repeat";
  }

  function saveWallpaper(value) {
    const selected = value === "default" || wallpapers[value] ? value : "default";
    try {
      localStorage.setItem(storageKey, selected);
    } catch (error) {
      // The visual choice still applies for this page when storage is unavailable.
    }
    applyWallpaper(selected);
  }

  window.bibliographyWallpaper = {
    current: currentWallpaper,
    apply: applyWallpaper,
    save: saveWallpaper,
  };
  applyWallpaper(currentWallpaper());
})();

const THEME_STORAGE_KEY = "sentinel-theme"


export function loadDarkModePreference() {
  return window.localStorage.getItem(
    THEME_STORAGE_KEY
  ) === "dark"
}


export function saveDarkModePreference(isDarkMode) {
  window.localStorage.setItem(
    THEME_STORAGE_KEY,
    isDarkMode ? "dark" : "light"
  )
}
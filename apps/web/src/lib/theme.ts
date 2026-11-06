export type ThemeMode = "light" | "dark";

export function getTheme(): ThemeMode {
  const attr = document.documentElement.getAttribute("data-theme");
  return attr === "dark" ? "dark" : "light";
}

export function setTheme(mode: ThemeMode) {
  document.documentElement.setAttribute("data-theme", mode);
  try {
    localStorage.setItem("mh_theme", mode);
  } catch {
    /* ignore */
  }
}

export function toggleTheme(): ThemeMode {
  const next = getTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}

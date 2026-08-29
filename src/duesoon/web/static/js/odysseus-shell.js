import themeModule, {
  THEMES,
  applyBgEffectColor,
  applyBgEffectIntensity,
  applyBgEffectSize,
  applyBgPattern,
  applyColors,
  save,
} from "/static/js/theme.js";

const sidebar = document.querySelector("#sidebar");
const iconRail = document.querySelector("#icon-rail");
const hamburger = document.querySelector("#hamburger-btn");
const sidebarToggle = document.querySelector("#sidebar-toggle-btn");
const backdrop = document.querySelector("#mobile-backdrop");

function setSidebarOpen(open) {
  sidebar.classList.toggle("hidden", !open);
  document.body.classList.toggle("sidebar-collapsed", !open);
  iconRail.style.display = open ? "none" : "flex";
  hamburger.style.display = open ? "none" : "grid";
  hamburger.setAttribute("aria-expanded", String(open));
  backdrop.classList.toggle("visible", open && matchMedia("(max-width: 768px)").matches);
}

sidebarToggle.addEventListener("click", () => setSidebarOpen(false));
hamburger.addEventListener("click", () => setSidebarOpen(true));
backdrop.addEventListener("click", () => setSidebarOpen(false));
window.closeDueSoonSidebar = () => {
  if (matchMedia("(max-width: 768px)").matches) setSidebarOpen(false);
};

document.querySelectorAll("[data-section-toggle]").forEach((button) => {
  const section = document.getElementById(button.dataset.sectionToggle)?.closest(".section");
  const items = document.getElementById(button.dataset.sectionToggle);
  const collapse = section?.querySelector(".section-collapse-btn");
  if (!section || !items) return;

  const setExpanded = (expanded) => {
    section.classList.toggle("collapsed", !expanded);
    items.hidden = !expanded;
    button.setAttribute("aria-expanded", String(expanded));
    collapse?.setAttribute("aria-expanded", String(expanded));
    collapse?.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} ${button.textContent.trim()}`);
  };
  const toggle = (event) => {
    event.stopPropagation();
    setExpanded(section.classList.contains("collapsed"));
  };

  button.addEventListener("click", toggle);
  collapse?.addEventListener("click", toggle);
});

const themeButton = document.querySelector("#tool-theme-btn");
const themeSubmenu = document.querySelector("#theme-submenu");
themeButton.addEventListener("click", () => {
  const open = themeSubmenu.hidden;
  themeSubmenu.hidden = !open;
  themeButton.setAttribute("aria-expanded", String(open));
});

document.querySelectorAll("[data-theme]").forEach((button) => {
  button.addEventListener("click", () => {
    const name = button.dataset.theme;
    const colors = THEMES[name];
    if (!colors) return;
    applyColors(colors);
    save(name, colors, { bgPattern: document.body.dataset.bgPattern || "constellations" });
  });
});

document.querySelectorAll("[data-bg-pattern]").forEach((button) => {
  button.addEventListener("click", () => {
    const pattern = button.dataset.bgPattern;
    document.body.dataset.bgPattern = pattern;
    applyBgPattern(pattern);
    const current = themeModule.getSaved();
    if (current?.colors) save(current.name, current.colors, { bgPattern: pattern });
  });
});

const saved = themeModule.getSaved();
if (!saved) {
  applyColors(THEMES.dark);
  applyBgEffectColor("");
  applyBgEffectIntensity(1);
  applyBgEffectSize(1);
  document.body.dataset.bgPattern = "constellations";
  applyBgPattern("constellations");
}

setSidebarOpen(!matchMedia("(max-width: 768px)").matches);

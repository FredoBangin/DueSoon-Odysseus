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

document.querySelectorAll(".section").forEach((section) => {
  const button = section.querySelector("[data-section-toggle], .section-header-flex .section-title");
  const collapse = section.querySelector(".section-collapse-btn");
  const header = section.querySelector(".section-header-flex");
  if (!button || !header) return;
  const label = button.textContent.trim();
  const setExpanded = (expanded) => {
    section.classList.toggle("collapsed", !expanded);
    const target = button.dataset.sectionToggle ? document.getElementById(button.dataset.sectionToggle) : null;
    if (target) target.hidden = !expanded;
    button.setAttribute("aria-expanded", String(expanded));
    collapse?.setAttribute("aria-expanded", String(expanded));
    collapse?.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} ${label}`);
  };
  const toggle = (event) => {
    event.stopPropagation();
    setExpanded(section.classList.contains("collapsed"));
  };
  button.addEventListener("click", toggle);
  if (!button.dataset.sectionToggle) header.addEventListener("click", toggle);
  collapse?.addEventListener("click", toggle);
});

const themeButton = document.querySelector("#tool-theme-btn");
const themeSubmenu = document.querySelector("#theme-submenu");
const themeModal = document.querySelector("#theme-modal");
themeButton?.addEventListener("click", () => {
  if (themeSubmenu) {
    const open = themeSubmenu.hidden;
    themeSubmenu.hidden = !open;
    themeButton.setAttribute("aria-expanded", String(open));
  } else if (themeModal) {
    themeModal.classList.toggle("hidden");
  }
});
document.querySelectorAll("#theme-modal .close-btn, #theme-modal .modal-close").forEach((button) => {
  button.addEventListener("click", () => themeModal?.classList.add("hidden"));
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

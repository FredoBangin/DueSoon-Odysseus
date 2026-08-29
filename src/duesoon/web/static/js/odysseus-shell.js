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
  let transitionTimer;
  const setExpanded = (expanded) => {
    const target = button.dataset.sectionToggle ? document.getElementById(button.dataset.sectionToggle) : null;
    clearTimeout(transitionTimer);
    button.setAttribute("aria-expanded", String(expanded));
    collapse?.setAttribute("aria-expanded", String(expanded));
    collapse?.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} ${label}`);
    if (expanded) {
      if (target) target.hidden = false;
      section.classList.remove("collapsed", "section-just-collapsing");
      section.classList.add("section-just-expanded");
      transitionTimer = setTimeout(() => section.classList.remove("section-just-expanded"), 700);
      return;
    }
    section.classList.remove("section-just-expanded");
    section.classList.add("section-just-collapsing");
    transitionTimer = setTimeout(() => {
      section.classList.add("collapsed");
      section.classList.remove("section-just-collapsing");
      if (target) target.hidden = true;
    }, 330);
  };
  const toggle = (event) => {
    event.stopPropagation();
    setExpanded(section.classList.contains("collapsed"));
  };
  button.addEventListener("click", toggle);
  if (!button.dataset.sectionToggle) header.addEventListener("click", toggle);
  collapse?.addEventListener("click", toggle);
});

document.addEventListener("click", (event) => {
  const themeChoice = event.target.closest("[data-theme]");
  if (themeChoice) {
    const name = themeChoice.dataset.theme;
    const colors = THEMES[name];
    if (!colors) return;
    applyColors(colors);
    save(name, colors, { bgPattern: document.body.dataset.bgPattern || "constellations" });
    return;
  }
  const patternChoice = event.target.closest("[data-bg-pattern]");
  if (patternChoice) {
    const pattern = patternChoice.dataset.bgPattern;
    document.body.dataset.bgPattern = pattern;
    applyBgPattern(pattern);
    const current = themeModule.getSaved();
    if (current?.colors) save(current.name, current.colors, { bgPattern: pattern });
  }
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

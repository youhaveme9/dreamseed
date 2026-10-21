"use strict";

const menuButton = document.querySelector(".menu-toggle");
const navigation = document.querySelector(".navigation-links");

function closeMenu() {
  menuButton.setAttribute("aria-expanded", "false");
  menuButton.setAttribute("aria-label", "Open navigation");
  navigation.classList.remove("open");
}

menuButton.addEventListener("click", () => {
  const expanded = menuButton.getAttribute("aria-expanded") !== "true";
  menuButton.setAttribute("aria-expanded", String(expanded));
  menuButton.setAttribute(
    "aria-label",
    expanded ? "Close navigation" : "Open navigation",
  );
  navigation.classList.toggle("open", expanded);
});
navigation.addEventListener("click", (event) => {
  if (event.target.closest("a")) closeMenu();
});
document.addEventListener("keydown", (event) => {
  if (
    event.key === "Escape" &&
    menuButton.getAttribute("aria-expanded") === "true"
  ) {
    closeMenu();
    menuButton.focus();
  }
});

const tabs = [...document.querySelectorAll("[data-tab]")];
function selectTab(tab) {
  for (const candidate of tabs) {
    const selected = candidate === tab;
    candidate.setAttribute("aria-selected", String(selected));
    candidate.tabIndex = selected ? 0 : -1;
    document.getElementById(candidate.getAttribute("aria-controls")).hidden =
      !selected;
  }
  document.getElementById("copy-install").dataset.copy =
    `install-${tab.dataset.tab}`;
}
for (const tab of tabs) {
  tab.addEventListener("click", () => selectTab(tab));
  tab.addEventListener("keydown", (event) => {
    const index = tabs.indexOf(tab);
    const destinations = {
      ArrowRight: (index + 1) % tabs.length,
      ArrowLeft: (index + tabs.length - 1) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    };
    if (!(event.key in destinations)) return;
    event.preventDefault();
    const next = tabs[destinations[event.key]];
    selectTab(next);
    next.focus();
  });
}

let toastTimer;
function announce(message) {
  const status = document.getElementById("copy-status");
  status.textContent = message;
  status.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => status.classList.remove("visible"), 3200);
}

async function copyText(text) {
  try {
    if (!navigator.clipboard) throw new Error("Clipboard unavailable");
    await navigator.clipboard.writeText(text);
  } catch {
    const previousFocus = document.activeElement;
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.cssText = "position:fixed;left:-9999px;top:0";
    document.body.append(field);
    field.select();
    let copied = false;
    try {
      copied = document.execCommand("copy");
    } finally {
      field.remove();
      previousFocus?.focus({ preventScroll: true });
    }
    if (!copied) throw new Error("Copy blocked");
  }
}

document.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-copy]");
  if (!button) return;
  const source = document.getElementById(button.dataset.copy);
  if (!source) return;
  try {
    await copyText(source.textContent.trim());
    announce(
      button.dataset.copy === "verified-seed"
        ? "Full world seed copied"
        : "Copied to clipboard",
    );
  } catch {
    announce("Copy was blocked. Select the text and copy it manually.");
  }
});

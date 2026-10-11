"""Usability checks run in the browser for every page on desktop and mobile."""
from __future__ import annotations

from pathlib import Path

SCREENSHOTS = Path(".test-tmp/ui-screens")

# Computes layout, tap target, font size, label and contrast findings in the page.
_AUDIT = r"""
(mobile) => {
  const findings = [];
  const doc = document.documentElement;
  if (doc.scrollWidth > window.innerWidth + 1) {
    findings.push(`horizontaler Überlauf: ${doc.scrollWidth}px > ${window.innerWidth}px`);
  }
  if (doc.lang !== "de") findings.push("html lang ist nicht de");
  if (document.querySelectorAll("h1").length !== 1) findings.push("nicht genau eine h1");
  const visible = (element) => {
    const box = element.getBoundingClientRect();
    const style = getComputedStyle(element);
    return box.width > 0 && box.height > 0 && style.visibility !== "hidden" && style.display !== "none";
  };
  const name = (element) => (element.innerText || element.value || element.getAttribute("aria-label")
    || element.id || element.tagName).trim().slice(0, 40);
  for (const element of document.querySelectorAll("a, button, input, textarea, summary, select")) {
    if (!visible(element) || element.type === "hidden") continue;
    const box = element.getBoundingClientRect();
    const minimum = element.matches("p a, li a, .meta a, code a") ? 0 : 40;
    if (mobile && box.height < minimum) {
      findings.push(`Tippfläche zu klein (${Math.round(box.height)}px): ${name(element)}`);
    }
    if (element.matches("input, textarea")) {
      const size = parseFloat(getComputedStyle(element).fontSize);
      if (size < 16) findings.push(`Eingabeschrift < 16px: ${name(element)}`);
      const labelled = element.labels && element.labels.length > 0 || element.getAttribute("aria-label");
      if (!labelled) findings.push(`Eingabe ohne Label: ${name(element)}`);
    }
  }
  for (const image of document.querySelectorAll("img")) {
    if (!image.hasAttribute("alt")) findings.push(`Bild ohne alt: ${image.src}`);
  }
  const parse = (value) => {
    const match = value.match(/rgba?\(([\d.]+), ([\d.]+), ([\d.]+)(?:, ([\d.]+))?\)/);
    return match ? [+match[1], +match[2], +match[3], match[4] === undefined ? 1 : +match[4]] : null;
  };
  const background = (element) => {
    for (let node = element; node; node = node.parentElement) {
      const color = parse(getComputedStyle(node).backgroundColor);
      if (color && color[3] > 0.5) return color;
    }
    return parse(getComputedStyle(document.body).backgroundColor);
  };
  const luminance = (rgb) => {
    const channel = (value) => {
      const c = value / 255;
      return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
  };
  const textNodes = document.querySelectorAll("h1, h2, h3, p, li, label, a, button, summary, span, strong, blockquote, code");
  for (const element of textNodes) {
    if (!visible(element) || !element.innerText.trim()) continue;
    const ownText = [...element.childNodes].some((node) => node.nodeType === 3 && node.textContent.trim());
    if (!ownText) continue;
    const style = getComputedStyle(element);
    const fg = parse(style.color);
    const bg = background(element);
    if (!fg || !bg) continue;
    const [light, dark] = [luminance(fg), luminance(bg)].sort((a, b) => b - a);
    const ratio = (light + 0.05) / (dark + 0.05);
    const large = parseFloat(style.fontSize) >= 24 || (parseFloat(style.fontSize) >= 18.66 && +style.fontWeight >= 700);
    if (ratio < (large ? 3 : 4.5)) {
      findings.push(`Kontrast ${ratio.toFixed(2)}: ${name(element)}`);
    }
  }
  return findings;
}
"""


def audit(page, label: str, mobile: bool) -> list[str]:
    """Take a full-page screenshot and return every usability finding."""
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOTS / f"{label}.png"), full_page=True)
    return page.evaluate(_AUDIT, mobile)


__all__ = ["SCREENSHOTS", "audit"]

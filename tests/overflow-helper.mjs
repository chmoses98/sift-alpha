// Shared by the e2e specs: names the elements that make the page wider than the viewport (outside deliberate scroll containers),
// so a sideways-scroll failure in WebKit says WHICH element caused it instead of only reporting two numbers.
export async function measureOverflow(page) {
  return page.evaluate(() => {
    const vw = window.innerWidth;
    const scrollers = (el) => { for (let n = el.parentElement; n; n = n.parentElement) { const o = getComputedStyle(n).overflowX; if (["auto", "scroll", "hidden", "clip"].includes(o)) return true; } return false; };
    const offenders = [];
    document.querySelectorAll("body *").forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width > 0 && r.right > vw + 0.5 && !scrollers(el)) offenders.push(`${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]} right=${Math.round(r.right)} w=${Math.round(r.width)} "${(el.textContent || "").trim().slice(0, 30)}"`);
    });
    return { scroll: document.documentElement.scrollWidth, view: vw, offenders: offenders.slice(0, 8) };
  });
}

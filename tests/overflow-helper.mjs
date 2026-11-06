// Shared by the e2e specs: when the page is wider than the viewport, say WHICH section / element is responsible instead of only reporting two numbers.
export async function measureOverflow(page) {
  return page.evaluate(() => {
    const vw = window.innerWidth, de = document.documentElement;
    const scrollers = (el) => { for (let n = el.parentElement; n; n = n.parentElement) { const o = getComputedStyle(n).overflowX; if (["auto", "scroll", "hidden", "clip"].includes(o)) return true; } return false; };
    const label = (el) => `${el.tagName.toLowerCase()}.${String(el.className).split(" ")[0]}`;
    const offenders = [];
    document.querySelectorAll("body *").forEach((el) => {
      const r = el.getBoundingClientRect();
      const inner = el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX === "visible";   // content spilling out of its own box (e.g. nowrap text)
      if (!scrollers(el) && ((r.width > 0 && r.right > vw + 0.5) || inner)) offenders.push(`${label(el)} right=${Math.round(r.right)} w=${Math.round(r.width)} sw=${el.scrollWidth} cw=${el.clientWidth}`);
    });
    const scroll = de.scrollWidth;
    // bisect: hide each top-level block in turn; a block is "responsible" if hiding it changes the page's scroll width
    const blocks = [];
    if (scroll > vw) {
      for (const k of document.querySelectorAll(".shell > *, .page > *")) {
        const prev = k.style.display; k.style.display = "none"; const sw = de.scrollWidth; k.style.display = prev;
        if (sw !== scroll) blocks.push(`${label(k)} -> ${sw}`);
      }
      const ir = document.querySelector("section.ir");
      if (ir) { const prev = ir.style.display; ir.style.display = "none"; blocks.push(`WITHOUT input-research section -> ${de.scrollWidth}`); ir.style.display = prev; }
    }
    const detail = [...document.querySelectorAll(".intelligence-filters, .intelligence-filters *")].map((el) => { const r = el.getBoundingClientRect(); return `${label(el)} l=${Math.round(r.left)} r=${Math.round(r.right)} sw=${el.scrollWidth} cw=${el.clientWidth} ox=${getComputedStyle(el).overflowX}`; });
    return { scroll, view: vw, intelligenceFilters: scroll > vw ? detail : [], body: document.body.scrollWidth, offenders: offenders.slice(0, 10), responsibleBlocks: blocks };
  });
}

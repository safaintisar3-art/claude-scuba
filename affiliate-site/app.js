(function () {
  const cfg = window.SITE_CONFIG || {};
  const products = window.PRODUCTS || [];

  // Fill in site-wide text from config.js
  document.querySelectorAll("[data-site-name]").forEach((el) => (el.textContent = cfg.siteName));
  document.querySelectorAll("[data-tagline]").forEach((el) => (el.textContent = cfg.tagline));
  document.querySelectorAll("[data-year]").forEach((el) => (el.textContent = cfg.year));
  document.querySelectorAll("[data-email]").forEach((el) => {
    el.textContent = cfg.contactEmail;
    el.href = "mailto:" + cfg.contactEmail;
  });
  if (document.title && cfg.siteName) document.title = document.title + " | " + cfg.siteName;

  const grid = document.getElementById("grid");
  if (!grid) return; // not the home page

  function amazonLink(p) {
    const base = "https://www." + (cfg.amazonDomain || "amazon.com");
    const tag = encodeURIComponent(cfg.amazonTag || "");
    if (p.asin) return base + "/dp/" + encodeURIComponent(p.asin) + "?tag=" + tag;
    return base + "/s?k=" + encodeURIComponent(p.search || p.name) + "&tag=" + tag;
  }

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  function card(p) {
    const c = el("article", "card");
    if (p.badge) c.appendChild(el("span", "badge", p.badge));
    c.appendChild(el("span", "category", p.category));
    c.appendChild(el("h3", null, p.name));
    if (p.image) {
      const img = document.createElement("img");
      img.src = p.image;
      img.alt = p.name;
      img.loading = "lazy";
      c.insertBefore(img, c.firstChild);
    }
    if (p.why) c.appendChild(el("p", "why", p.why));
    const dl = el("dl");
    if (p.bestFor) { dl.appendChild(el("dt", null, "Best for")); dl.appendChild(el("dd", null, p.bestFor)); }
    if (p.watchOut) { dl.appendChild(el("dt", null, "Watch out")); dl.appendChild(el("dd", null, p.watchOut)); }
    c.appendChild(dl);
    const a = el("a", "btn btn-primary", "Check price on Amazon");
    a.href = amazonLink(p);
    a.target = "_blank";
    a.rel = "sponsored nofollow noopener";
    c.appendChild(a);
    return c;
  }

  // Category filters
  const categories = ["All", ...new Set(products.map((p) => p.category))];
  const filters = document.getElementById("filters");
  const search = document.getElementById("search");
  const empty = document.getElementById("empty");
  let active = "All";

  categories.forEach((cat) => {
    const b = el("button", "chip", cat);
    b.setAttribute("role", "tab");
    b.addEventListener("click", () => { active = cat; render(); });
    filters.appendChild(b);
  });

  function render() {
    const q = search.value.trim().toLowerCase();
    [...filters.children].forEach((b) => b.setAttribute("aria-selected", String(b.textContent === active)));
    const shown = products.filter((p) =>
      (active === "All" || p.category === active) &&
      (!q || [p.name, p.category, p.why, p.bestFor].join(" ").toLowerCase().includes(q))
    );
    grid.replaceChildren(...shown.map(card));
    empty.hidden = shown.length > 0;
  }

  search.addEventListener("input", render);
  render();
})();

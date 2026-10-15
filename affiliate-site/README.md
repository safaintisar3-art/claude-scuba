# Affiliate website (Amazon Associates)

A ready-to-use product recommendation site. Visitors read your picks, click
**Check price on Amazon**, and if they buy something you earn a commission.
It's plain HTML/CSS/JS: no build step and no server, so you can host it free.

## 1. Get your Amazon affiliate tag
1. Sign up at <https://affiliate-program.amazon.com> (you'll need the site's URL, so do step 4 first if you like).
2. Amazon gives you a tracking ID like `yourname-20`.
3. Note: Amazon closes accounts that don't make **3 qualifying sales within 180 days**,
   so plan to get some traffic early.

## 2. Edit `config.js`
Set `siteName`, `tagline`, `amazonTag`, `amazonDomain` and `contactEmail`.

## 3. Edit `products.js`
- Replace the sample products with real ones. Use `asin` (the code after `/dp/` in
  an Amazon URL) to link straight to a product; use `search` to link to a search page.
- Optional `image`: a path to an image you're allowed to use, e.g. `images/desk.jpg`.
- Write honest `why`, `bestFor` and `watchOut` text. That's what makes people trust you.
- Don't type in prices or star ratings; Amazon's rules don't allow hard-coded prices.

The niche (home office) and the buying guide in `index.html` are just a starting
point. Change them to whatever you know about: fitness, gaming, baby gear, kitchen,
camping...

## 4. Put it online (free)
**GitHub Pages:** in the repo on GitHub go to *Settings → Pages*, choose this branch,
and set the folder. GitHub Pages only serves from the root or `/docs`, so either move
this folder's files to `/docs` or put them in their own repository.

**Netlify / Cloudflare Pages:** drag the `affiliate-site` folder onto
<https://app.netlify.com/drop>. It's live in seconds.

Preview locally: `python -m http.server` inside this folder, then open <http://localhost:8000>.

## 5. Get traffic (the actual hard part)
The site earns nothing without visitors. What works:
- **Write articles** that answer specific searches: "best standing desk under $300",
  "X vs Y". Copy `disclosure.html` as a starting template for new pages.
- **Pinterest, YouTube Shorts, TikTok, Reddit**: show the product in use and link to your page
  (follow each community's rules on self-promotion).
- Be patient: search traffic usually takes 3–6 months to build.

## Rules to stay on the right side of
- Keep the affiliate disclosure (the top bar and `disclosure.html`); the FTC requires it.
- Links use `rel="sponsored"`, which Google requires for paid links.
- Don't put affiliate links in emails or PDFs (Amazon forbids it), and don't click your own links.

## About "Amazon dropshipping"
Buying from Amazon and having it shipped to customers who ordered from your store
goes against Amazon's policies and gets seller accounts banned. Affiliate marketing (this
site) is the legitimate, low-risk version: you don't hold inventory, handle shipping or
deal with returns.

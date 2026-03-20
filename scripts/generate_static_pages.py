import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


ROOT_URL = "https://eltabasqueno.com"


@dataclass(frozen=True)
class Item:
    brand: str
    model: str
    trim: str
    price: Optional[int]
    currency: str
    source_url: str
    image: Optional[str]


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def slugify(value: str) -> str:
    v = (value or "").strip().lower()
    v = v.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    v = re.sub(r"[^a-z0-9]+", "-", v)
    v = re.sub(r"-+", "-", v).strip("-")
    return v or "item"


def read_catalog(path: Path) -> tuple[dict[str, Any], list[Item]]:
    if not path.exists():
        return {"items": []}, []
    data = json.loads(path.read_text(encoding="utf-8"))
    items: list[Item] = []
    for x in data.get("items", []) or []:
        brand = str(x.get("brand") or "").strip()
        model = str(x.get("model") or "").strip()
        trim = str(x.get("trim") or "").strip()
        price = x.get("price")
        price_int: Optional[int]
        try:
            price_int = int(price) if price is not None else None
        except Exception:
            price_int = None
        currency = str(x.get("currency") or "MXN").strip() or "MXN"
        source_url = str(x.get("source_url") or "").strip()
        images = x.get("images") or []
        image = str(images[0]).strip() if isinstance(images, list) and images else None
        if brand and model and source_url:
            items.append(
                Item(
                    brand=brand,
                    model=model,
                    trim=trim,
                    price=price_int,
                    currency=currency,
                    source_url=source_url,
                    image=image,
                )
            )
    return data, items


def html_escape(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def render_page(title: str, description: str, canonical: str, body: str, og_image: Optional[str]) -> str:
    og_img = og_image or f"{ROOT_URL}/og.png"
    return f"""<!doctype html>
<html lang=\"es\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>{html_escape(title)}</title>
  <meta name=\"description\" content=\"{html_escape(description)}\" />
  <meta name=\"robots\" content=\"index,follow,max-image-preview:large,max-snippet:-1,max-video-preview:-1\" />
  <link rel=\"canonical\" href=\"{html_escape(canonical)}\" />

  <meta property=\"og:type\" content=\"website\" />
  <meta property=\"og:site_name\" content=\"eltabasqueño.com\" />
  <meta property=\"og:title\" content=\"{html_escape(title)}\" />
  <meta property=\"og:description\" content=\"{html_escape(description)}\" />
  <meta property=\"og:url\" content=\"{html_escape(canonical)}\" />
  <meta property=\"og:locale\" content=\"es_MX\" />
  <meta property=\"og:image\" content=\"{html_escape(og_img)}\" />

  <meta name=\"twitter:card\" content=\"summary_large_image\" />
  <meta name=\"twitter:title\" content=\"{html_escape(title)}\" />
  <meta name=\"twitter:description\" content=\"{html_escape(description)}\" />
  <meta name=\"twitter:image\" content=\"{html_escape(og_img)}\" />

  <link rel=\"stylesheet\" href=\"/styles.css\" />
</head>
<body>
  <main class=\"container\" style=\"padding: 24px 0 44px;\">
    {body}
  </main>
</body>
</html>
"""


def build_model_page(item: Item, last_updated: str) -> tuple[str, str]:
    brand_slug = slugify(item.brand)
    model_slug = slugify(f"{item.model}-{item.trim}" if item.trim else item.model)
    path = f"modelos/{brand_slug}/{model_slug}.html"
    canonical = f"{ROOT_URL}/{path}"

    display_title = f"{item.brand} {item.model}" + (f" {item.trim}" if item.trim else "")
    title = f"{display_title} | eltabasqueño.com"

    price_text = "—" if item.price is None else f"${item.price:,} {item.currency}".replace(",", ",")
    description = f"{display_title}. Precio referencial: {price_text}. Última actualización: {last_updated}."

    img_html = ""
    if item.image:
        img_html = f"<div style=\"margin-top:16px\"><img src=\"{html_escape(item.image)}\" alt=\"{html_escape(display_title)}\" style=\"max-width:100%; height:auto; border-radius:14px; border:1px solid rgba(255,255,255,0.14); background: rgba(255,255,255,0.02);\" loading=\"lazy\"/></div>"

    offer_json = ""
    if item.price is not None:
        offer_json = f"\n      \"offers\": {{\"@type\": \"Offer\", \"priceCurrency\": \"{html_escape(item.currency)}\", \"price\": \"{item.price}\"}}"

    json_ld = f"""
<script type=\"application/ld+json\">{{
  \"@context\": \"https://schema.org\",
  \"@type\": \"Product\",
  \"name\": \"{html_escape(display_title)}\",
  \"brand\": {{\"@type\": \"Brand\", \"name\": \"{html_escape(item.brand)}\"}},
  \"image\": {json.dumps([item.image] if item.image else [])},
  \"url\": \"{html_escape(canonical)}\"{offer_json}
}}</script>
""".strip()

    body = f"""
<a class=\"btn btn--ghost btn--sm\" href=\"/index.html\">Volver</a>
<h1 style=\"margin:14px 0 6px\">{html_escape(display_title)}</h1>
<div class=\"meta\">Última actualización: {html_escape(last_updated)}</div>
<div style=\"margin-top:12px\" class=\"price\">{html_escape(price_text)}</div>
<div class=\"meta\">Precio referencial</div>
<div style=\"margin-top:14px\">
  <a class=\"btn btn--ghost\" href=\"{html_escape(item.source_url)}\" target=\"_blank\" rel=\"noopener noreferrer\">Ver fuente</a>
</div>
{img_html}
{json_ld}
""".strip()

    return path, render_page(title=title, description=description, canonical=canonical, body=body, og_image=item.image)


def build_brand_page(brand: str, items: list[Item], last_updated: str) -> tuple[str, str]:
    brand_slug = slugify(brand)
    path = f"marcas/{brand_slug}.html"
    canonical = f"{ROOT_URL}/{path}"

    title = f"{brand} | Catálogo | eltabasqueño.com"
    description = f"Catálogo {brand}. Última actualización: {last_updated}."

    links = []
    for it in items:
        model_slug = slugify(f"{it.model}-{it.trim}" if it.trim else it.model)
        href = f"/{'modelos'}/{brand_slug}/{model_slug}.html"
        display = f"{it.model}" + (f" · {it.trim}" if it.trim else "")
        links.append(f"<li><a href=\"{html_escape(href)}\">{html_escape(display)}</a></li>")

    body = f"""
<a class=\"btn btn--ghost btn--sm\" href=\"/index.html\">Volver</a>
<h1 style=\"margin:14px 0 6px\">{html_escape(brand)}</h1>
<div class=\"meta\">Última actualización: {html_escape(last_updated)}</div>
<ul style=\"margin-top:14px; line-height:1.7\">{''.join(links)}</ul>
""".strip()

    og_image = items[0].image if items and items[0].image else None
    return path, render_page(title=title, description=description, canonical=canonical, body=body, og_image=og_image)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    global ROOT_URL

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Repo root")
    parser.add_argument("--site-url", default=ROOT_URL)
    args = parser.parse_args()
    ROOT_URL = args.site_url.rstrip("/")

    root = Path(args.root).resolve()

    toyota_data, toyota_items = read_catalog(root / "data" / "catalog.json")
    nissan_data, nissan_items = read_catalog(root / "data" / "nissan.json")

    combined = toyota_items + nissan_items

    # Prefer a meaningful last_updated value.
    last_updated = (
        (toyota_data.get("last_updated_at") or toyota_data.get("generated_at"))
        or (nissan_data.get("last_updated_at") or nissan_data.get("generated_at"))
        or now_str()
    )

    # Generate pages
    urls: list[str] = [f"{ROOT_URL}/", f"{ROOT_URL}/index.html"]

    by_brand: dict[str, list[Item]] = {}
    for it in combined:
        by_brand.setdefault(it.brand, []).append(it)

    for brand, items in by_brand.items():
        items_sorted = sorted(items, key=lambda x: (x.model, x.trim))
        rel_path, html = build_brand_page(brand, items_sorted, last_updated)
        write_text(root / rel_path, html)
        urls.append(f"{ROOT_URL}/{rel_path}")

        for it in items_sorted:
            rel_path2, html2 = build_model_page(it, last_updated)
            write_text(root / rel_path2, html2)
            urls.append(f"{ROOT_URL}/{rel_path2}")

    # sitemap.xml
    urlset = "\n".join(
        f"  <url><loc>{html_escape(u)}</loc></url>" for u in sorted(set(urls))
    )
    sitemap = f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">
{urlset}
</urlset>
"""
    write_text(root / "sitemap.xml", sitemap)

    robots = f"""User-agent: *
Allow: /
Sitemap: {ROOT_URL}/sitemap.xml
"""
    write_text(root / "robots.txt", robots)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

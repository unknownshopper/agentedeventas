import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.nissandeportiva.com.mx/"


MIN_REASONABLE_PRICE_MXN = 150_000


@dataclass(frozen=True)
class Listing:
    brand: str
    model: str
    trim: str
    price: Optional[int]
    currency: str
    source_name: str
    source_url: str
    images: list[str]


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def fetch(url: str, timeout_s: int = 25) -> str:
    headers = {
        "User-Agent": "eltabasqueno-catalog-bot/0.1 (+https://eltabasqueno.com)",
    }
    r = requests.get(url, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    return r.text


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    path = re.sub(r"/+", "/", parsed.path)
    return parsed._replace(path=path, query="", fragment="").geturl()


_PRICE_RE = re.compile(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")


def parse_price(text: str) -> Optional[int]:
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "")
    try:
        return int(raw)
    except ValueError:
        return None


def extract_prices_from_text(text: str) -> list[int]:
    prices: list[int] = []
    if not text:
        return prices
    for m in _PRICE_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            value = int(raw)
        except ValueError:
            continue
        if value >= MIN_REASONABLE_PRICE_MXN:
            prices.append(value)
    return prices


def clean_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def model_name_from_title(title: str) -> str:
    t = clean_spaces(title)
    t = re.sub(r"\s*\|\s*Nissan Deportiva\s*\|\s*Villahermosa, Tabasco\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*\|\s*Nissan Deportiva\s*$", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s+\|\s+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    if t.lower().startswith("nissan "):
        return t[len("nissan "):].strip()
    return t


def extract_model_links_from_home(home_html: str) -> list[str]:
    soup = BeautifulSoup(home_html, "lxml")
    links: set[str] = set()

    # Some model URLs are not .html (e.g. /nissan-kicks, /nissan-frontier)
    candidate_anchors = soup.select('a[href*="nissan-"]')

    blacklist_contains = {
        "credinissan",
        "connect",
        "nissan-connect",
        "privacy",
        "aviso",
        "seminuevos",
        "refacciones",
        "servicio",
        "promocion",
        "contacto",
        "citas",
    }

    for a in candidate_anchors:
        href = a.get("href")
        if not href:
            continue
        abs_url = canonical_url(urljoin(BASE_URL, href))
        if not abs_url.startswith(BASE_URL):
            continue

        lower = abs_url.lower()
        if any(bad in lower for bad in blacklist_contains):
            continue

        # Keep only likely model pages.
        # - /nissan-versa.html
        # - /nissan-frontier
        # - /nissan-kicks
        parsed = urlparse(abs_url)
        last = parsed.path.rstrip("/").split("/")[-1]
        if not last.startswith("nissan-"):
            continue
        if last.endswith(".aspx"):
            continue

        links.add(abs_url)

    return sorted(links)


def scrape_model_page(url: str) -> Listing:
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")

    title = soup.title.string.strip() if soup.title and soup.title.string else url
    model = model_name_from_title(title)

    image_url = None
    for meta in (
        soup.find("meta", attrs={"property": "og:image"}),
        soup.find("meta", attrs={"property": "og:image:url"}),
        soup.find("meta", attrs={"name": "twitter:image"}),
    ):
        if meta and meta.get("content"):
            image_url = meta.get("content").strip()
            break

    if not image_url:
        # Fallback: first non-trivial image.
        for img in soup.select("img[src]"):
            src = (img.get("src") or "").strip()
            if not src:
                continue
            lower = src.lower()
            if any(x in lower for x in ("logo", "icon", "sprite")):
                continue
            image_url = urljoin(BASE_URL, src)
            break

    # Prefer extracting from the "Versiones" section to avoid unrelated monetary values.
    prices: list[int] = []

    versiones_header = soup.find(
        lambda tag: tag.name in {"h1", "h2", "h3"}
        and "version" in tag.get_text(" ", strip=True).lower()
    )
    if versiones_header:
        section_text_parts: list[str] = []
        for sib in versiones_header.find_all_next():
            if sib is versiones_header:
                continue
            if sib.name in {"h1", "h2"}:
                # Stop when next major section begins.
                if "version" not in sib.get_text(" ", strip=True).lower():
                    break
            section_text_parts.append(sib.get_text("\n", strip=True))

        section_text = "\n".join(section_text_parts)
        prices.extend(extract_prices_from_text(section_text))
    else:
        # Fallback: scan whole page but apply sanity threshold.
        text = soup.get_text("\n", strip=True)
        prices.extend(extract_prices_from_text(text))

    price = min(prices) if prices else None

    return Listing(
        brand="Nissan",
        model=model,
        trim="",
        price=price,
        currency="MXN",
        source_name="nissandeportiva.com.mx",
        source_url=url,
        images=[image_url] if image_url else [],
    )


def to_item(l: Listing) -> dict:
    return {
        "brand": l.brand,
        "model": l.model,
        "trim": l.trim,
        "price": l.price,
        "currency": l.currency,
        "source_name": l.source_name,
        "source_url": l.source_url,
        "images": l.images,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/nissan.json")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    home_html = fetch(BASE_URL)
    urls = extract_model_links_from_home(home_html)
    if args.limit and args.limit > 0:
        urls = urls[: args.limit]

    items: list[Listing] = []
    seen_models: set[str] = set()
    for url in urls:
        try:
            listing = scrape_model_page(url)
        except Exception:
            continue
        if not listing.model:
            continue
        # De-dupe by model name (home repeats links).
        key = listing.model.lower()
        if key in seen_models:
            continue
        seen_models.add(key)
        items.append(listing)

    payload = {
        "generated_at": now_str(),
        "last_updated_at": now_str(),
        "items": [to_item(x) for x in items],
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

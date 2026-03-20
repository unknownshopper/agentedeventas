import argparse
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


BASE_URL = "https://toyotatabasco.com.mx/"
AUTOS_NUEVOS_URL = urljoin(BASE_URL, "autos-nuevos/")


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
        "User-Agent": "eltabasqueno-catalog-bot/0.1 (+https://eltabasqueno.com)"
    }
    r = requests.get(url, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    return r.text


def extract_model_links(autos_nuevos_html: str) -> list[str]:
    soup = BeautifulSoup(autos_nuevos_html, "lxml")

    links: set[str] = set()
    for a in soup.select('a[href]'):
        href = a.get("href")
        if not href:
            continue
        abs_url = urljoin(BASE_URL, href)
        if "/autos-nuevos/" in abs_url and abs_url.rstrip("/") != AUTOS_NUEVOS_URL.rstrip("/"):
            links.add(abs_url.split("#")[0])

    return sorted(links)


_PRICE_RE = re.compile(r"\$\s*([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)")


def _text_price_candidates(text: str) -> Iterable[int]:
    for m in _PRICE_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            yield int(raw)
        except ValueError:
            continue


def extract_og(soup: BeautifulSoup, prop: str) -> Optional[str]:
    tag = soup.find("meta", attrs={"property": prop})
    if not tag:
        return None
    content = tag.get("content")
    return content.strip() if content else None


def parse_title_to_model_trim(title: str) -> tuple[str, str]:
    t = title.strip()
    t = re.sub(r"\s*\|\s*Toyota Tabasco\s*$", "", t, flags=re.IGNORECASE)

    m = re.search(r"\b(20\d{2})\b", t)
    if m:
        year = m.group(1)
        model = re.sub(r"\b20\d{2}\b", "", t).strip(" -—")
        return model, year

    return t, ""


def scrape_model_page(url: str) -> Listing:
    html = fetch(url)
    soup = BeautifulSoup(html, "lxml")

    og_title = extract_og(soup, "og:title")
    title = og_title or (soup.title.string.strip() if soup.title and soup.title.string else url)

    model, trim = parse_title_to_model_trim(title)

    og_image = extract_og(soup, "og:image")
    images = [og_image] if og_image else []

    text = soup.get_text(" ", strip=True)
    price = None
    for candidate in _text_price_candidates(text):
        price = candidate
        break

    return Listing(
        brand="Toyota",
        model=model or "",
        trim=trim or "",
        price=price,
        currency="MXN",
        source_name="toyotatabasco.com.mx",
        source_url=url,
        images=images,
    )


def parse_price_mxn(text: str) -> Optional[int]:
    for candidate in _text_price_candidates(text or ""):
        return candidate
    return None


def _clean_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def canonical_model_url(url: str) -> str:
    """Normalize model URLs and drop non-catalog variants (e.g. /Cotizacion/)."""
    parsed = urlparse(url)
    path = parsed.path
    path = re.sub(r"/Cotizacion/?$", "", path, flags=re.IGNORECASE)
    path = re.sub(r"/+", "/", path).rstrip("/")
    return parsed._replace(path=path, query="", fragment="").geturl()


def model_trim_from_slug(url: str) -> tuple[str, str]:
    """Derive model name + year from URL slug like 'rav4-hev-25'."""
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1]
    slug = re.sub(r"(?i)cotizacion$", "", slug)
    parts = [p for p in slug.split("-") if p]

    year = ""
    if parts and re.fullmatch(r"\d{2}", parts[-1]):
        yy = int(parts[-1])
        year = str(2000 + yy)
        parts = parts[:-1]
    elif parts and re.fullmatch(r"\d{4}", parts[-1]):
        year = parts[-1]
        parts = parts[:-1]

    def prettify(token: str) -> str:
        t = token.strip()
        if not t:
            return t
        if t.lower() in {"hev", "hybrid"}:
            return "HEV"
        if t.lower() == "gr":
            return "GR"
        if t.lower() == "rav4":
            return "RAV4"
        if t.lower() == "prius":
            return "Prius"
        return t[:1].upper() + t[1:]

    model = " ".join(prettify(p) for p in parts).strip()
    return model, year


def extract_listings_playwright(limit: int = 0) -> list[Listing]:
    """Scrape model cards from the dynamically rendered catalog page.

    This targets the card UI where the site shows: Model Year + "Desde $... MN".
    Selectors may change; we keep it resilient by anchoring on URLs and price text.
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="eltabasqueno-catalog-bot/0.1 (+https://eltabasqueno.com)",
            locale="es-MX",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        page.goto(AUTOS_NUEVOS_URL, wait_until="networkidle")

        # Wait for at least one link to a model card to appear.
        try:
            page.wait_for_selector('a[href*="/autos-nuevos/"]', timeout=20000)
        except PlaywrightTimeoutError:
            page.goto(BASE_URL, wait_until="networkidle")
            page.wait_for_selector('a[href*="/autos-nuevos/"]', timeout=20000)

        anchors = page.locator('a[href*="/autos-nuevos/"]')
        count = anchors.count()

        seen: set[str] = set()
        out: list[Listing] = []

        for i in range(count):
            if limit and len(out) >= limit:
                break

            href = anchors.nth(i).get_attribute("href")
            if not href:
                continue
            url = canonical_model_url(urljoin(BASE_URL, href))
            if url.rstrip("/") == AUTOS_NUEVOS_URL.rstrip("/"):
                continue
            if url in seen:
                continue

            # Climb to a reasonable card container.
            card = anchors.nth(i).locator("xpath=ancestor::div[contains(@class,'card') or contains(@class,'swiper-slide') or contains(@class,'col')][1]")
            if card.count() == 0:
                card = anchors.nth(i).locator("xpath=ancestor::div[1]")

            title_text = _clean_spaces(card.locator("xpath=.//h1|.//h2|.//h3|.//p[1]").first.inner_text() if card.count() else "")
            if not title_text:
                title_text = _clean_spaces(anchors.nth(i).inner_text())

            # Prefer deriving model/year from the URL slug (stable). If title looks like a price, ignore it.
            model_from_url, trim_from_url = model_trim_from_slug(url)
            looks_like_price = ("desde" in title_text.lower()) or ("$" in title_text)
            if model_from_url and not looks_like_price:
                model, trim = model_from_url, trim_from_url
            else:
                model, trim = (model_from_url, trim_from_url) if model_from_url else parse_title_to_model_trim(title_text)

            price_text = ""
            if card.count():
                # XPath you provided points to a <p><span> with the price; we search for similar spans.
                price_candidates = card.locator("xpath=.//p//span[contains(.,'$') or contains(.,'MN') or contains(.,'Desde')]")
                if price_candidates.count() > 0:
                    price_text = _clean_spaces(price_candidates.first.inner_text())
                else:
                    price_text = _clean_spaces(card.inner_text())

            price = parse_price_mxn(price_text)

            img_url = None
            if card.count():
                img = card.locator("img").first
                if img.count() > 0:
                    img_url = img.get_attribute("src") or img.get_attribute("data-src")
            images = [urljoin(BASE_URL, img_url)] if img_url else []

            seen.add(url)
            out.append(
                Listing(
                    brand="Toyota",
                    model=model or title_text,
                    trim=trim,
                    price=price,
                    currency="MXN",
                    source_name="toyotatabasco.com.mx",
                    source_url=url,
                    images=images,
                )
            )

        context.close()
        browser.close()

    return out


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
    parser.add_argument(
        "--out",
        default="data/catalog.json",
        help="Output path for catalog JSON (relative to repo root)",
    )
    parser.add_argument(
        "--mode",
        choices=["playwright", "requests"],
        default="playwright",
        help="Scraping mode. Use 'playwright' for dynamic content; 'requests' is best-effort.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional limit of model pages to fetch (0 = no limit)",
    )
    args = parser.parse_args()

    items: list[Listing] = []
    if args.mode == "playwright":
        items = extract_listings_playwright(limit=args.limit)
    else:
        autos_html = fetch(AUTOS_NUEVOS_URL)
        model_urls = extract_model_links(autos_html)

        if args.limit and args.limit > 0:
            model_urls = model_urls[: args.limit]

        for url in model_urls:
            try:
                items.append(scrape_model_page(url))
            except Exception:
                continue

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

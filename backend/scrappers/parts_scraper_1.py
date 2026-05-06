# parts_bootstrap_scraper.py
# Parts 1–3 for PartSelect: collect brand pages, subcategories, and product links
# Works for multiple appliances (Dishwasher, Refrigerator). Results merged in single files.
# - brands.json
# - brand_subcategories.json
# - products.jsonl  (one JSON per line: {appliance, brand, subcategory_name, subcategory_url, product_url})

import json, os, re, time
from pathlib import Path
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import NoSuchElementException, TimeoutException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ──────────────────────────────────────────────────────────────────────────────
# storage
# ──────────────────────────────────────────────────────────────────────────────
DATA_DIR = Path("data/parts1")
DATA_DIR.mkdir(parents=True, exist_ok=True)

BRANDS_JSON = DATA_DIR / "brands.json"
SUBCATS_JSON = DATA_DIR / "brand_subcategories.json"
PRODUCTS_JSONL = DATA_DIR / "products.jsonl"
SUBCAT_INDEX = DATA_DIR / "subcat_index.txt"     # used to skip already scraped subcategory URLs

# ──────────────────────────────────────────────────────────────────────────────
# tiny utils
# ──────────────────────────────────────────────────────────────────────────────
def save_json(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def load_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default

def append_jsonl(path: Path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

def _seen_set(path: Path) -> set[str]:
    return set(path.read_text(encoding="utf-8").splitlines()) if path.exists() else set()

def _mark_seen(path: Path, key: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(key.strip() + "\n")

def human_pause(a=0.20, b=0.40):
    # simple predictable pause (no randomness to keep it deterministic here)
    time.sleep(a)

# ──────────────────────────────────────────────────────────────────────────────
# selenium boilerplate (driver + wait + popup killer)
# ──────────────────────────────────────────────────────────────────────────────
def setup_driver(headless: bool = True) -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,1800")
    opts.add_argument("--lang=en-US,en")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=opts)
    # mask webdriver flag a bit
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"}
        )
    except Exception:
        pass
    return driver

def wait(driver, locator, t=20):
    return WebDriverWait(driver, t).until(EC.presence_of_element_located(locator))

def _try_click_first(driver, *locators):
    """
    Fast, non-blocking click attempt. Uses find_elements (no long waits).
    Returns True if something was clicked.
    """
    for by, sel in locators:
        try:
            els = driver.find_elements(by, sel)
            if not els:
                continue
            el = els[0]
            try:
                el.click()
            except Exception:
                try:
                    driver.execute_script("arguments[0].click();", el)
                except Exception:
                    pass
            return True
        except Exception:
            pass
    return False

def dismiss_popups(driver, max_iframes=4):
    """
    Fast popup dismissal:
    - Try page-level buttons quickly (no long waits).
    - Send ESC once as a cheap fallback.
    - Only scan a few iframes and use non-blocking checks inside them.
    """
    # page-level
    if _try_click_first(
        driver,
        (By.XPATH, "//button[normalize-space()='Decline']"),
        (By.XPATH, "//a[normalize-space()='Decline']"),
        (By.XPATH, "//button[contains(.,'Decline all')]"),
        (By.XPATH, "//button[contains(.,'No thanks')]"),
        (By.CSS_SELECTOR, "button[aria-label='Close'], .mfp-close, .modal .close, .ps-modal .close, .optanon-alert-box-close"),
    ):
        return

    # ESC fallback
    try:
        driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
    except Exception:
        pass

    # iframe fallback (scan a few)
    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for f in frames[:max_iframes]:
            try:
                driver.switch_to.frame(f)
                if _try_click_first(
                    driver,
                    (By.XPATH, "//button[normalize-space()='Decline']"),
                    (By.XPATH, "//a[normalize-space()='Decline']"),
                    (By.CSS_SELECTOR, "button[aria-label='Close'], .mfp-close, .modal .close"),
                ):
                    driver.switch_to.default_content()
                    return
            except Exception:
                pass
            finally:
                driver.switch_to.default_content()
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────────
# core logic (Parts 1–3), parameterized by appliance
# ──────────────────────────────────────────────────────────────────────────────
def appliance_slug(appliance: str) -> str:
    # Page slug is TitleCase with hyphen: 'Dishwasher', 'Refrigerator'
    return appliance.strip().title()

# Part 1: collect brand pages for an appliance
def get_brand_links_for_appliance(driver, appliance: str):
    """
    Returns a list of {appliance, brand, brand_url}.
    Strategy: on /<Appliance>-Parts.htm, grab all anchors whose href ends with '-<Appliance>-Parts.htm'
    """
    base = f"https://www.partselect.com/{appliance_slug(appliance)}-Parts.htm"
    driver.get(base)
    dismiss_popups(driver)
    wait(driver, (By.TAG_NAME, "body"))

    links = driver.find_elements(By.XPATH, f"//a[contains(@href,'-{appliance_slug(appliance)}-Parts.htm')]")
    out = {}
    for a in links:
        href = a.get_attribute("href") or ""
        text = (a.text or "").strip()
        if not href or not text:
            continue
        # require exact "-<Appliance>-Parts.htm" ending (brand list pattern)
        if not href.lower().endswith(f"-{appliance_slug(appliance).lower()}-parts.htm"):
            continue
        brand = re.sub(rf"\s*{appliance_slug(appliance)}\s+Parts\s*$", "", text, flags=re.IGNORECASE).strip()
        if not brand:
            continue
        out[href] = {"appliance": appliance_slug(appliance), "brand": brand, "brand_url": href}
    return list(out.values())

# Part 2: subcategories for a brand page (appliance-sensitive)
def get_subcategories_for_brand_appliance(driver, brand: str, brand_url: str, appliance: str):
    """
    Returns a list[{name, url}] for one brand page.
    Strategy: take all anchors whose href contains '/<Brand>-<Appliance>-'
    and ignore the 'Models'/'View More' items.
    """
    driver.get(brand_url)
    dismiss_popups(driver)
    wait(driver, (By.TAG_NAME, "body"))
    human_pause()

    pattern = f"/{brand.replace(' ','-')}-{appliance_slug(appliance)}-"
    anchors = driver.find_elements(By.XPATH, f"//a[contains(@href, {repr(pattern)})]")
    subs, seen = [], set()
    for a in anchors:
        name = (a.text or "").strip()
        href = a.get_attribute("href") or ""
        if not name or not href:
            continue
        # skip Models, "View More", etc.
        if "Models" in href or "Models" in name or "View More" in name or "View more" in name:
            continue
        key = (name, href)
        if key in seen:
            continue
        seen.add(key)
        subs.append({"name": name, "url": href})
    return subs

# Part 3: collect product URLs for each subcategory (resumable)
def collect_product_links_from_subcategory(driver, subcat_url: str):
    """
    Return a list of absolute product URLs from a subcategory page.
    Product URLs look like: /PS<digits>-Brand-<PartName>.htm
    Handles pagination via in-page "Next" links.
    """
    urls = set()

    def harvest():
        anchors = driver.find_elements(
            By.XPATH,
            "//a[starts-with(@href,'/PS') or starts-with(@href,'https://www.partselect.com/PS')]"
        )
        for a in anchors:
            href = a.get_attribute("href") or ""
            if re.search(r"/PS\d+-.+\.htm", href):
                urls.add(href)

    driver.get(subcat_url)
    dismiss_popups(driver)
    wait(driver, (By.TAG_NAME, "body"))
    human_pause()
    harvest()

    # follow "Next" pagination within the subcategory (if present)
    for _ in range(40):  # safe cap
        next_links = driver.find_elements(By.XPATH, "//a[normalize-space()='Next' and not(@aria-disabled='true')]")
        if not next_links:
            break
        try:
            driver.execute_script("arguments[0].click();", next_links[0])
        except Exception:
            try:
                next_links[0].click()
            except Exception:
                break
        time.sleep(0.5)
        harvest()

    return sorted(urls)

# ──────────────────────────────────────────────────────────────────────────────
# main runner for Parts 1–3 across multiple appliances (merged outputs)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Toggle which parts to run (comment out as you like)
    run_part1 = True
    run_part2 = True
    run_part3 = True

    appliances = ["Dishwasher", "Refrigerator"]

    driver = setup_driver(headless=True)  # set to False to watch
    try:
        # ===== Part 1: collect brand links (merged for all appliances) =====
        if run_part1:
            all_brands = []
            for app in appliances:
                bl = get_brand_links_for_appliance(driver, app)
                print(f"[Part1] {app}: found {len(bl)} brand pages")
                all_brands.extend(bl)
            save_json(BRANDS_JSON, all_brands)
            print(f"[Part1] wrote → {BRANDS_JSON}")

        # ===== Part 2: collect subcategories for each brand (merged) =====
        if run_part2:
            brands_input = load_json(BRANDS_JSON, [])
            brand_subcats = []
            for i, b in enumerate(brands_input, 1):
                print(f"[Part2] [{i}/{len(brands_input)}] {b['appliance']} · {b['brand']}")
                subs = get_subcategories_for_brand_appliance(
                    driver, b["brand"], b["brand_url"], b["appliance"]
                )
                brand_subcats.append({
                    "appliance": b["appliance"],
                    "brand": b["brand"],
                    "brand_url": b["brand_url"],
                    "subcategories": subs,
                })
                time.sleep(0.25)  # polite pacing
            save_json(SUBCATS_JSON, brand_subcats)
            print(f"[Part2] wrote → {SUBCATS_JSON}")

        # ===== Part 3: collect product URLs from each subcategory (resumable) =====
        if run_part3:
            subcats_input = load_json(SUBCATS_JSON, [])
            seen_subcats = _seen_set(SUBCAT_INDEX)

            total_sc = sum(len(x["subcategories"]) for x in subcats_input)
            done = 0
            for b in subcats_input:
                app = b["appliance"]
                brand = b["brand"]
                for sc in b["subcategories"]:
                    done += 1
                    url = sc["url"]
                    if url in seen_subcats:
                        print(f"[Part3] SKIP subcat ({done}/{total_sc}): {brand} · {sc['name']}")
                        continue
                    print(f"[Part3] Subcat ({done}/{total_sc}): {app} · {brand} · {sc['name']}")
                    try:
                        prods = collect_product_links_from_subcategory(driver, url)
                        for pu in prods:
                            append_jsonl(PRODUCTS_JSONL, {
                                "appliance": app,
                                "brand": brand,
                                "subcategory_name": sc["name"],
                                "subcategory_url": url,
                                "product_url": pu,
                            })
                        print(f"         + {len(prods)} products")
                        _mark_seen(SUBCAT_INDEX, url)      # mark this subcat as done (skip next time)
                        seen_subcats.add(url)
                        time.sleep(0.25)
                    except Exception as e:
                        print(f"         ! failed: {e}")

            print(f"[Part3] stream wrote → {PRODUCTS_JSONL}")
            print(f"[Part3] resume index → {SUBCAT_INDEX}")

    finally:
        driver.quit()
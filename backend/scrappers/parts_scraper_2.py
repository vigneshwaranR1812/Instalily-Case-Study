"""
Part 4 – Product details scraper for PartSelect pages.
Pulls all standard fields + Installation Complexity & Time.
"""

import re, os, json, time, traceback
from pathlib import Path
from typing import Union, Optional, List, Dict
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, StaleElementReferenceException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys

# ---------- Paths ----------
DATA_DIR = Path("data/parts1")
PRODUCTS_JSONL = DATA_DIR / "deduplicated_products.jsonl"
DETAILS_JSONL  = DATA_DIR / "product_details.jsonl"
DETAILS_INDEX  = DATA_DIR / "details_index.txt"
FAILED_LIST    = DATA_DIR / "failed_products.txt"

# ---------- Utilities ----------
def _ensure_dir(p: Path): p.parent.mkdir(parents=True, exist_ok=True)

def _load_lines_set(path: Path) -> set[str]:
    if not path.exists(): return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()}

def clean(s: Optional[str]) -> Optional[str]:
    if not s: return s
    s = re.sub(r"[ \t]+"," ", s)
    s = re.sub(r"\r?\n\s*","\n", s)
    s = re.sub(r"\n{3,}","\n\n", s)
    return s.strip()

def wait(driver, locator, timeout=10):
    WebDriverWait(driver, timeout).until(EC.presence_of_element_located(locator))

def dismiss_popups(driver):
    """Safely close any site popups."""
    for sel in [".ps-tooltip-close",".modal.show .close"]:
        for e in driver.find_elements(By.CSS_SELECTOR, sel):
            try:
                e.click()
                time.sleep(0.2)
            except Exception:
                pass

def get_dt_dd(driver, labels: List[str]) -> Optional[str]:
    for lab in labels:
        xp = f"//dt[normalize-space(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'))={repr(lab.lower())}]/following-sibling::dd[1]"
        els = driver.find_elements(By.XPATH, xp)
        if els:
            t = els[0].text.strip()
            if t: return clean(t)
    return None

def list_after_heading(driver, heads: list[str]) -> list[str]:
    for h in heads:
        xp = f"//*[self::h2 or self::h3 or self::h4][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'), {repr(h.lower())})]"
        for el in driver.find_elements(By.XPATH, xp):
            for listxp in ("following-sibling::ul[1] | following::ul[1]",
                           "following-sibling::ol[1] | following::ol[1]"):
                try:
                    ul = el.find_element(By.XPATH, listxp)
                    items = [clean(li.text) for li in ul.find_elements(By.TAG_NAME, "li")]
                    return [i for i in items if i]
                except NoSuchElementException:
                    pass
    return []

def try_price(driver) -> Optional[str]:
    sels = ["span[itemprop='price']", "meta[itemprop='price']", "span.price", "div.price"]
    for css in sels:
        els = driver.find_elements(By.CSS_SELECTOR, css)
        if not els: continue
        val = (els[0].get_attribute("content") or els[0].text or "").strip()
        if val:
            m = re.search(r"\$?\s*\d[\d,]*\.?\d*", val)
            return m.group(0).replace(" ", "") if m else clean(val)
    return None

def try_availability(driver) -> Optional[str]:
    texts = []
    for css in ("div.availability","span.availability","div.stock-status","div#availability"):
        for el in driver.find_elements(By.CSS_SELECTOR, css):
            t = el.text.strip()
            if t: texts.append(clean(t))
    for el in driver.find_elements(By.XPATH, "//*[contains(.,'In Stock') or contains(.,'On Order') or contains(.,'Backorder')]"):
        t = el.text.strip()
        if t: texts.append(clean(t))
    return min(texts, key=len) if texts else None


def get_part_video_url(driver, timeout: int = 8) -> Optional[str]:
    """
    Return a YouTube watch URL ONLY if it appears in the 'Part Videos' section.
    Prefers an <iframe>, else uses data-yt-init, else extracts from the thumbnail.
    """
    def _normalize_watch(u: str) -> Optional[str]:
        if not u:
            return None
        u = u.strip()
        # iframe embed -> watch
        m = re.search(r"/embed/([A-Za-z0-9_-]{6,})", u)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
        # direct watch/short
        m = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", u)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"
        return None

    # 1) Find the 'Part Videos' trigger and its content container
    try:
        trigger = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((By.ID, "PartVideos"))
        )
    except TimeoutException:
        return None

    # The collapsible content is the next sibling with data-collapsible
    try:
        container = trigger.find_element(
            By.XPATH, "following-sibling::*[@data-collapsible][1]"
        )
    except Exception:
        # Some pages use data-collapse-container instead of data-collapsible
        try:
            container = trigger.find_element(
                By.XPATH, "following-sibling::*[@data-collapse-container][1]"
            )
        except Exception:
            return None

    # Ensure the section is visible/open
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", trigger)
        expanded = (trigger.get_attribute("aria-expanded") or "").lower()
        if expanded in ("false", "0", "no", ""):
            driver.execute_script("arguments[0].click();", trigger)
            time.sleep(0.3)
    except Exception:
        pass

    # 2) If an iframe is already present, use it
    iframes = container.find_elements(By.CSS_SELECTOR, "iframe[src]")
    for fr in iframes:
        src = fr.get_attribute("src") or ""
        if "youtube" in src or "youtu.be" in src:
            w = _normalize_watch(src)
            if w:
                return w

    # 3) If we have a yt-video div with data-yt-init, construct the watch URL
    for div in container.find_elements(By.CSS_SELECTOR, "div.yt-video"):
        vid = div.get_attribute("data-yt-init") or div.get_attribute("data-yt") or ""
        if vid:
            return f"https://www.youtube.com/watch?v={vid}"

    # 4) Fallback: extract from the thumbnail URL
    thumbs = container.find_elements(By.CSS_SELECTOR, "img[src*='img.youtube.com/vi/']")
    for im in thumbs:
        src = im.get_attribute("src") or ""
        m = re.search(r"img\.youtube\.com/vi/([A-Za-z0-9_-]{6,})/", src)
        if m:
            return f"https://www.youtube.com/watch?v={m.group(1)}"

    # 5) Last resort: click the play area (often swaps in the iframe), then re-check
    try:
        clickable = container.find_elements(By.CSS_SELECTOR, ".yt-video, .yt-video__thumb, .i--yt, svg.i.i--yt")
        if clickable:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", clickable[0])
            driver.execute_script("arguments[0].click();", clickable[0])
            time.sleep(0.5)
            iframes = container.find_elements(By.CSS_SELECTOR, "iframe[src]")
            for fr in iframes:
                src = fr.get_attribute("src") or ""
                if "youtube" in src or "youtu.be" in src:
                    w = _normalize_watch(src)
                    if w:
                        return w
    except Exception:
        pass

    return None



def expand_crossref_if_collapsed(driver):
    """Expand the 'Model Cross Reference' accordion on the page if present."""
    candidates = [
        "//div[contains(@data-collapse-trigger,'ModelCrossReference') or contains(., 'Model Cross Reference')]",
        "//*[@id='ModelCrossReference' or @data-handle='ModelCrossReference']",
        "//*[self::h2 or self::h3][contains(., 'Model Cross Reference')]",
    ]
    for xp in candidates:
        els = driver.find_elements(By.XPATH, xp)
        if not els: continue
        el = els[0]
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            # click if aria-expanded suggests collapsed; otherwise try anyway
            expanded = (el.get_attribute("aria-expanded") or "").lower()
            if expanded in ("false","0","no"): driver.execute_script("arguments[0].click();", el)
            else:
                try:
                    btn = el.find_element(By.XPATH, ".//button|.//a")
                    driver.execute_script("arguments[0].click();", btn)
                except Exception:
                    pass
            break
        except Exception:
            continue


def get_partselect_number(driver):
    # primary: itemprop=productID (PS…)
    el = next((e for e in driver.find_elements(By.CSS_SELECTOR, "[itemprop='productID']") if e.text.strip()), None)
    if el: return el.text.strip()
    # fallback: labeled text near "PartSelect Number"
    try:
        el = driver.find_element(By.XPATH, "//*[contains(., 'PartSelect Number')]/following::*[1]")
        t = el.text.strip()
        return t if t.upper().startswith("PS") else None
    except Exception:
        return None

def get_mpn(driver):
    el = next((e for e in driver.find_elements(By.CSS_SELECTOR, "[itemprop='mpn']") if e.text.strip()), None)
    return el.text.strip() if el else get_dt_dd(driver, ["Manufacturer Part Number","Mfr Part Number","MPN"])

def get_manufacturer(driver):
    # e.g. <span itemprop="brand"><span itemprop="name">Whirlpool</span></span>
    try:
        return driver.find_element(By.CSS_SELECTOR, "[itemprop='brand'] [itemprop='name']").text.strip()
    except Exception:
        return get_dt_dd(driver, ["Manufacturer","Brand"])

def get_manufactured_for(driver):
    """
    Reads the full 'Manufactured by ... for ...' line and returns the bit after 'for '.
    Works on pages where the label is a plain text node in a <div class="mb-2">.
    """
    try:
        # The entire line lives in a single mb-2 div
        line = driver.find_element(
            By.XPATH,
            "//div[contains(@class,'mb-2')][contains(normalize-space(.), 'Manufactured by')]"
        ).text.strip()
        # Example: 'Manufactured by Whirlpool for Whirlpool, Maytag, Amana, KitchenAid'
        m = re.search(r"\bfor\s+(.+)$", line, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
        # Fallback: if they omitted 'for', but still listed brands after the manufacturer
        # remove leading 'Manufactured by <brand>' and return the rest if it looks like a list
        line_no_prefix = re.sub(r"^Manufactured by\s+\S+\s*", "", line, flags=re.IGNORECASE).strip()
        if "," in line_no_prefix:
            return line_no_prefix
    except Exception:
        pass
    return None

def _expand_section_by_title_or_handle(driver, title_text="Product Description", handle="contentDesc"):
    """
    Expands the 'Product Description' accordion:
    - either by data-handle="contentDesc"
    - or by visible title text containing 'Product Description'
    """
    # Prefer match by data-handle (more stable)
    hdr = None
    try:
        hdr = driver.find_element(By.XPATH, f"//*[@data-handle={repr(handle)} and @data-collapse-trigger]")
    except Exception:
        pass
    if not hdr:
        # Fallback: match by section title text
        try:
            hdr = driver.find_element(
                By.XPATH,
                f"//*[contains(@class,'section-title') and contains(normalize-space(.), {repr(title_text)})]"
            )
        except Exception:
            return None, None

    # The content container is the first following sibling with data-collapse-container
    try:
        container = hdr.find_element(By.XPATH, "following-sibling::*[@data-collapse-container][1]")
    except Exception:
        container = None

    # Expand if needed
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", hdr)
        expanded = (hdr.get_attribute("aria-expanded") or "").lower()
        if expanded in ("false", "0", "no", ""):
            driver.execute_script("arguments[0].click();", hdr)
            time.sleep(0.25)
    except Exception:
        pass

    return hdr, container

def get_description(driver):
    """
    Robustly extract Product Description across PartSelect layouts.
    Order:
      1) Any visible [itemprop='description']
      2) Next sibling container of the 'Product Description' trigger
      3) Left column inside a pd__description block
      4) Generic paragraph fallback
    Returns cleaned text or None.
    """
    # 1) Any visible itemprop='description'
    try:
        for el in driver.find_elements(By.XPATH, "//*[@itemprop='description' and normalize-space()]"):
            if el.is_displayed():
                txt = el.text.strip()
                if txt:
                    return clean(txt)
    except Exception:
        pass

    # 2) Anchor on the 'Product Description' trigger (by handle or title),
    #    then read its collapse container sibling
    trigger = None
    for xp in (
        "//*[@id='ProductDescription']",
        "//*[@data-handle='contentDesc' and @data-collapse-trigger]",
        "//*[contains(@class,'section-title') and contains(normalize-space(.), 'Product Description')]",
    ):
        els = driver.find_elements(By.XPATH, xp)
        if els:
            trigger = els[0]
            break
    container = None
    if trigger:
        try:
            container = trigger.find_element(
                By.XPATH,
                "following-sibling::*[@data-collapse-container or @data-collapsible][1]"
            )
        except Exception:
            container = None

    if container:
        try:
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", container)
        except Exception:
            pass

        # prefer a dedicated description node inside the container
        try:
            node = container.find_element(By.XPATH, ".//*[@itemprop='description' and normalize-space()]")
            txt = node.text.strip()
            if txt:
                return clean(re.split(r"(?i)\bwhy buy\b", txt)[0])
        except Exception:
            pass

        # try left text column (commonly .col-lg-8)
        try:
            left = container.find_element(By.CSS_SELECTOR, ".col-lg-8, .col-md-8, .col-8")
            txt = left.text.strip()
            if txt:
                return clean(re.split(r"(?i)\bwhy buy\b", txt)[0])
        except Exception:
            pass

        # whole container as a last attempt
        txt = container.text.strip()
        if txt:
            return clean(re.split(r"(?i)\bwhy buy\b", txt)[0])

    # 3) If we didn’t find the trigger/container, try any pd__description block
    try:
        block = driver.find_element(By.CSS_SELECTOR, ".pd__description, .pd_description, .pd__description__col_wrap")
        # prefer itemprop inside it
        try:
            node = block.find_element(By.XPATH, ".//*[@itemprop='description' and normalize-space()]")
            txt = node.text.strip()
            if txt:
                return clean(txt)
        except Exception:
            pass
        # otherwise, the block text
        txt = block.text.strip()
        if txt:
            return clean(re.split(r"(?i)\bwhy buy\b", txt)[0])
    except Exception:
        pass

    # 4) Generic fallback: first substantial paragraph on page
    paras = [p.text.strip() for p in driver.find_elements(By.CSS_SELECTOR, "article p, .pd__description p, .description p") if p.text.strip()]
    if paras:
        # pick the longest early paragraph, trim marketing sections
        txt = max(paras[:6], key=len)
        return clean(re.split(r"(?i)\bwhy buy\b", txt)[0])

    return None

def extract_symptoms_and_replaces(driver) -> dict:
    """
    Returns:
      {
        "symptoms": List[str] | None,
        "replaces": List[str] | None
      }

    Targets the Troubleshooting section layout:
      <div id="Troubleshooting" ... data-collapse-trigger>
      <div class="pd__wrap row" data-collapsible> ... </div>
    """
    out = {"symptoms": None, "replaces": None}

    def _norm(s: str) -> str:
        if not s: return ""
        s = s.replace("\xa0", " ")
        return re.sub(r"[ \t]+", " ", s).strip()

    # 1) Find the "Troubleshooting" section container
    container = None
    # Prefer: ID anchor + next sibling with data-collapsible
    try:
        trig = driver.find_element(By.XPATH, "//*[@id='Troubleshooting' and @data-collapse-trigger]")
        container = trig.find_element(By.XPATH, "following-sibling::*[@data-collapsible][1]")
    except Exception:
        # Fallback: any row wrapper with data-collapsible and the 'This part fixes...' header
        try:
            container = driver.find_element(
                By.XPATH,
                "//div[contains(@class,'pd__wrap') and contains(@class,'row') and @data-collapsible]"
            )
        except Exception:
            return out  # leave Nones if the section doesn't exist on this page

    # Make sure it's in view (some pages lazy-render bits)
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", container)
    except Exception:
        pass

    # 2) Symptoms list: UL right after the 'This part fixes...' bold heading
    try:
        ul = container.find_element(
            By.XPATH,
            ".//div[contains(@class,'bold') and contains(normalize-space(.), 'fixes the following symptoms')]/following-sibling::ul[1]"
        )
        items = [ _norm(li.text) for li in ul.find_elements(By.TAG_NAME, "li") if _norm(li.text) ]
        out["symptoms"] = items or None
    except Exception:
        # secondary: any list-disc on left half
        pass

    # 3) Replaces list: text inside the div following the 'replaces these:' heading
    try:
        rep_block = container.find_element(
            By.XPATH,
            ".//div[contains(@class,'bold') and contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'replaces these')]/following-sibling::*[1]"
        )
        txt = _norm(rep_block.text)
        # Some pages put it inside a data-collapse-container; same text extraction works
        if not txt:
            txt = _norm(rep_block.get_attribute("textContent") or "")
        if txt:
            # split on commas/space; keep tokens that look like part numbers
            tokens = [t.strip(" ,") for t in re.split(r"[,\s]+", txt) if t.strip()]
            parts = [t for t in tokens if re.search(r"[A-Za-z]\d", t)]
            # de-dupe preserving order
            seen, uniq = set(), []
            for p in parts:
                if p not in seen:
                    seen.add(p); uniq.append(p)
            out["replaces"] = uniq or None
    except Exception:
        pass

    return out


def parse_cross_reference_inline(driver):
    """
    Extract *all* model cross-ref rows from the in-page section.
    Handles internal infinite scroll + optional 'Next' pagination.
    Returns: [{brand, model_number, description}, ...] or None.
    """
    def harvest(scope):
        rows = scope.find_elements(By.CSS_SELECTOR, ".row")
        items = []
        for r in rows:
            try:
                brand = ""
                b = r.find_elements(By.CSS_SELECTOR, ".col-6.col-md-3")
                if b:
                    brand = b[0].text.strip()

                try:
                    model = r.find_element(By.CSS_SELECTOR, "a[href*='/Models/']").text.strip()
                except Exception:
                    model = ""

                desc = ""
                d = r.find_elements(By.CSS_SELECTOR, ".col.col-md-6.col-lg-7, .col-md-6.col-lg-7")
                if d:
                    desc = d[0].text.strip()

                if model:
                    items.append({
                        "brand": brand or None,
                        "model_number": model,
                        "description": desc or None
                    })
            except Exception:
                continue
        return items

    results = []
    seen_keys = set()

    # anchor -> container -> list
    try:
        trigger = driver.find_element(By.CSS_SELECTOR, "#ModelCrossReference")
        container = trigger.find_element(By.XPATH, "following-sibling::*[contains(@class,'pd__crossref') or contains(@class,'js-resultsRenderer')][1]")
        list_el = container.find_element(By.CSS_SELECTOR, ".pd__crossref_list, .js-dataContainer")
    except Exception:
        # fallback: table layout
        rows = driver.find_elements(By.XPATH, "//table//tr[td]")
        out = []
        for r in rows:
            tds = r.find_elements(By.TAG_NAME, "td")
            if len(tds) >= 3:
                brand = tds[0].text.strip() or None
                try:
                    model = tds[1].find_element(By.TAG_NAME, "a").text.strip()
                except Exception:
                    model = tds[1].text.strip()
                desc = tds[2].text.strip() or None
                if model:
                    out.append({"brand": brand, "model_number": model, "description": desc})
        return out or None

    # ensure list is in view
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", list_el)
    except Exception:
        pass

    # scroll the internal container until growth stops
    stagnant = 0
    last_count = -1
    max_loops = 40           # hard stop
    for _ in range(max_loops):
        # harvest current
        for item in harvest(list_el):
            key = (item["brand"], item["model_number"])
            if key not in seen_keys:
                seen_keys.add(key)
                results.append(item)

        # growth check
        if len(results) == last_count:
            stagnant += 1
        else:
            stagnant = 0
        last_count = len(results)
        if stagnant >= 3:   # 3 consecutive no-growth cycles
            break

        # scroll internal list to bottom (not the window)
        try:
            driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollHeight;", list_el
            )
        except Exception:
            break
        time.sleep(0.35)

    # optional in-section pagination: click 'Next' 1–2 times and harvest again
    for _ in range(2):
        try:
            next_btns = container.find_elements(By.XPATH, ".//a[normalize-space()='Next' and not(@aria-disabled='true')]")
            if not next_btns:
                break
            driver.execute_script("arguments[0].click();", next_btns[0])
            time.sleep(0.6)
            # after clicking, repeat a short scroll-harvest loop
            stagnant = 0
            last_count = -1
            for __ in range(12):
                for item in harvest(list_el):
                    key = (item["brand"], item["model_number"])
                    if key not in seen_keys:
                        seen_keys.add(key)
                        results.append(item)
                if len(results) == last_count:
                    stagnant += 1
                else:
                    stagnant = 0
                last_count = len(results)
                if stagnant >= 3:
                    break
                try:
                    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", list_el)
                except Exception:
                    break
                time.sleep(0.3)
        except Exception:
            break

    return results or None

def extract_installation_meta(driver, timeout: int = 8) -> dict:
    """
    Reads 'Very Easy' and '15 - 30 mins' from the repair-rating block.
    Works with BEM classes: pd__repair-rating__container, etc.
    """
    out = {"installation_complexity": None, "installation_time": None}

    def _norm(s: str) -> str:
        if not s: return ""
        s = s.replace("\xa0", " ").replace("–", "-").replace("—", "-")
        return re.sub(r"[ \t]+", " ", s).strip()

    # wait for the container to exist
    try:
        container = WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "div.pd__repair-rating__container")
            )
        )
    except TimeoutException:
        return out  # leave Nones

    # bring it into view (some layouts populate as you scroll)
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", container)
    except Exception:
        pass

    # read the two bold <p> in order
    ps = container.find_elements(By.CSS_SELECTOR, "p.bold")
    vals = [_norm(p.text) for p in ps if _norm(p.text)]
    if vals:
        out["installation_complexity"] = vals[0]
    if len(vals) > 1:
        out["installation_time"] = vals[1]
    return out

def get_reviews_summary(driver):
    """
    Extract rating value (e.g. 4.8) and number of reviews (e.g. 394).
    Returns None if not found.
    """
    rating_value = None
    try:
        el = driver.find_element(By.CSS_SELECTOR, ".pd__cust-review__header__rating__chart--border")
        raw = (el.text or "").strip() or (el.get_attribute("textContent") or "").strip()
        m = re.search(r"\d+(\.\d+)?", raw)
        if m:
            rating_value = float(m.group(0))
    except Exception:
        pass

    # Fallback: compute from stars width (e.g., 96% -> 4.8)
    if rating_value is None:
        try:
            upper = driver.find_element(By.CSS_SELECTOR, ".rating__stars__upper[style*='width']")
            style = upper.get_attribute("style") or ""
            m = re.search(r"width\s*:\s*([\d.]+)\s*%", style)
            if m:
                rating_value = round(float(m.group(1)) / 100.0 * 5.0, 1)
        except Exception:
            pass
    
    rating_count = None
    try:
        span = driver.find_element(By.CSS_SELECTOR, ".pd__cust-review__header__rating .rating__count")
        m = re.search(r"\d[\d,]*", (span.text or "").strip())
        if m:
            rating_count = int(m.group(0).replace(",", ""))
    except Exception:
        pass

    return {"rating_value": rating_value, "rating_count": rating_count}



def parse_product_page(driver, url: str) -> Dict[str, Union[str, Optional[str], Optional[List[str]], Optional[List[Dict[str, Optional[str]]]]]]:
    driver.get(url)
    dismiss_popups(driver)
    wait(driver, (By.TAG_NAME, "body"))

    # title
    name = None
    for css in ("h1.product-title","h1#page-title","h1[itemprop='name']","h1"):
        els = driver.find_elements(By.CSS_SELECTOR, css)
        if els: name = clean(els[0].text); break

    ps_num    = get_partselect_number(driver)
    mpn       = get_mpn(driver)
    manuf     = get_manufacturer(driver)
    manuf_for = get_manufactured_for(driver)
    price     = try_price(driver)
    availability = try_availability(driver)
    desc      = get_description(driver)
    video     = get_part_video_url(driver)
    # crossref  = parse_cross_reference_inline(driver)
    # crossref = parse_cross_reference_fast(driver)
    install   = extract_installation_meta(driver)
    sym = extract_symptoms_and_replaces(driver)
    reviews = get_reviews_summary(driver)

    return {
        "product_url": url,
        "name": name,
        "price": price,
        "availability": availability,
        "partselect_number": ps_num,
        "manufacturer_part_number": mpn,
        "manufacturer": manuf,
        "manufactured_for": manuf_for,
        "description": desc,
        "replaces": sym["replaces"],
        "video_url": video,
        # "model_cross_reference": crossref or None,
        "installation_complexity": install["installation_complexity"],
        "installation_time": install["installation_time"],
        "symptoms": sym["symptoms"],
        "rating_value": reviews["rating_value"],
        "rating_count": reviews["rating_count"]
    }


def setup_driver(headless=True):
    """Create Chrome driver."""
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1366,768")
    return webdriver.Chrome(options=opts)


def trial_product(url: str):
    drv = setup_driver(headless=False)
    try:
        rec = parse_product_page(drv, url)
        print(json.dumps(rec, indent=2, ensure_ascii=False))
    finally:
        drv.quit()

try:
    DATA_DIR
except NameError:
    DATA_DIR = Path("data/parts1/parts.jsonl")
PRODUCTS_JSONL = DATA_DIR / "deduplicated_products.jsonl"
DETAILS_JSONL  = DATA_DIR / "product_details.jsonl"
DETAILS_INDEX  = DATA_DIR / "details_index.txt"
FAILED_LIST    = DATA_DIR / "failed_products.txt"

def _existing_done_from_outfile(out_path: Path) -> set[str]:
    done = set()
    if not out_path.exists(): return done
    with out_path.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                u = (obj.get("product_url") or "").strip()
                if u: done.add(u)
            except Exception:
                pass
    return done

def _iter_product_urls(jsonl_path: Path):
    if not jsonl_path.exists():
        log(f"❌ Input file not found: {jsonl_path}")
        return
    with jsonl_path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line: 
                log(f"␀ Skipping empty line {i}")
                continue
            try:
                obj = json.loads(line)
            except Exception:
                log(f"⚠️  Non-JSON line {i}: {line[:120]}…")
                continue
            url = (obj.get("product_url") or "").strip()
            if not url:
                log(f"⚠️  No product_url on line {i}")
                continue
            yield url

# ---- Tiny logger
def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

def run_part4_batch(
    in_jsonl: Path = PRODUCTS_JSONL,
    out_jsonl: Path = DETAILS_JSONL,
    idx_path: Path = DETAILS_INDEX,
    failed_path: Path = FAILED_LIST,
    headless: bool = False,          # <<< show the browser for now
    inject_io_patch: bool = True,
    rotate_every: int = 40,
    pause_s: float = 0.10,
    limit: Optional[int] = None        # process only first N for debugging
):
    _ensure_dir(out_jsonl)
    _ensure_dir(idx_path)
    _ensure_dir(failed_path)

    seen_idx = _load_lines_set(idx_path)
    seen_out = _existing_done_from_outfile(out_jsonl)
    already_ok = seen_idx | seen_out

    log(f"🟡 Starting Part4 batch")
    log(f"    Input:   {in_jsonl}")
    log(f"    Output:  {out_jsonl}")
    log(f"    Index:   {idx_path}")
    log(f"    Failed:  {failed_path}")
    log(f"    Headless={headless}  IO_patch={inject_io_patch}  rotate_every={rotate_every}  limit={limit}")

    # Build driver
    drv = _new_driver(headless, inject_io_patch)

    total_in = total_new = total_skip = 0
    t0 = time.time()

    try:
        with out_jsonl.open("a", encoding="utf-8") as fout, \
             idx_path.open("a", encoding="utf-8") as findex, \
             failed_path.open("a", encoding="utf-8") as ffail:

            for url in _iter_product_urls(in_jsonl):
                if limit is not None and total_in >= limit:
                    log("🔵 Reached limit; stopping.")
                    break

                total_in += 1
                if url in already_ok:
                    total_skip += 1
                    log(f"⏭️  SKIP [{total_in}] {url}")
                    continue

                # rotate driver periodically
                if rotate_every and total_new > 0 and total_new % rotate_every == 0:
                    log("♻️  Rotating browser…")
                    try: drv.quit()
                    except Exception: pass
                    drv = _new_driver(headless, inject_io_patch)

                log(f"➡️  START [{total_in}] {url}")
                start = time.time()
                try:
                    rec = parse_product_page(drv, url)     # <-- your existing function
                    elapsed = time.time() - start

                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n"); fout.flush()
                    findex.write(url + "\n"); findex.flush()

                    total_new += 1
                    log(f"✅ OK   [{total_in}] {elapsed:.2f}s → written")
                except Exception as e:
                    elapsed = time.time() - start
                    ffail.write(url + "\n"); ffail.flush()
                    log(f"❌ FAIL [{total_in}] {elapsed:.2f}s → {type(e).__name__}: {e}")
                    traceback.print_exc()
                finally:
                    if pause_s: time.sleep(pause_s)

    finally:
        try: drv.quit()
        except Exception: pass
        log(f"🏁 Done. processed_new={total_new} skipped={total_skip} total_seen={total_in} in {time.time()-t0:.1f}s")

def _new_driver(headless: bool, inject_io_patch: bool):
    log(f"🧩 launching Chrome (headless={headless})…")
    d = setup_driver(headless=headless)  # <-- your existing driver factory
    # pre-inject the IO patch for future documents
    if inject_io_patch:
        try:
            d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": IO_PATCH})
            log("🔧 IO patch pre-injected for future pages")
        except Exception as e:
            log(f"⚠️  IO pre-inject failed: {e}")
    return d


# ========== PARALLEL PART-4 RUNNER (sharded -> merged JSONL) ==========
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import json, time, os


def _iter_product_urls(jsonl_path: Path):
    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            url = (obj.get("product_url") or "").strip()
            if url:
                yield url

def _existing_done(out_jsonl: Path) -> set[str]:
    """URLs already present in central JSONL -> skip (resume)."""
    done = set()
    if not out_jsonl.exists():
        return done
    with out_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                u = (json.loads(line).get("product_url") or "").strip()
                if u:
                    done.add(u)
            except Exception:
                pass
    return done

def _shard_round_robin(items, workers: int):
    buckets = [[] for _ in range(workers)]
    for i, it in enumerate(items):
        buckets[i % workers].append(it)
    return buckets

# --- Worker entrypoint (one Chrome per process; writes a shard file)
def _worker_run(sid: int, urls: list[str], out_dir: Path, headless: bool = True):
    """
    Each worker:
      - creates its own driver
      - iterates its slice of URLs
      - writes results to product_details.part{sid}.jsonl
    """
    # Late import inside subprocess is safer on some OSes
    import json, time, random
    from pathlib import Path

    shard_path = out_dir / f"product_details.part{sid}.jsonl"
    # Optional: per-worker Chrome profile (helps with cookie persistence)
    profile_dir = f".chrome_profile_worker_{sid}"

    drv = setup_driver(headless=headless)  # your existing driver
    try:
        with shard_path.open("a", encoding="utf-8") as fout:
            for u in urls:
                try:
                    rec = parse_product_page(drv, u)   # your existing parser
                    if rec:
                        fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                        fout.flush()
                except Exception:
                    # If you have a FAILED_LIST per worker, you can log here
                    pass
                # small jitter keeps things polite
                time.sleep(0.05 + random.random() * 0.15)
    finally:
        try:
            drv.quit()
        except Exception:
            pass

def _merge_shards(out_dir: Path, central: Path):
    """Append shards into the central JSONL (idempotent)."""
    _ensure_dir(central)
    shards = sorted(out_dir.glob("product_details.part*.jsonl"))
    if not shards:
        return
    with central.open("a", encoding="utf-8") as fout:
        for p in shards:
            with p.open("r", encoding="utf-8") as fin:
                for line in fin:
                    fout.write(line)

def _dedupe_central(central: Path):
    """Optional: dedupe central JSONL by product_url (safe for ~6.5k)."""
    if not central.exists():
        return
    seen = set()
    tmp = central.with_suffix(".dedup.tmp.jsonl")
    with central.open("r", encoding="utf-8") as fin, tmp.open("w", encoding="utf-8") as fout:
        for line in fin:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            u = (obj.get("product_url") or "").strip()
            if not u or u in seen:
                continue
            seen.add(u)
            fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    tmp.replace(central)

def run_part4_parallel(
    in_jsonl: Path = PRODUCTS_JSONL,
    central_out: Path = DETAILS_JSONL,
    workers: int = 6,
    headless: bool = True,
):
    _ensure_dir(central_out)

    # Resume: skip URLs already in central file
    done = _existing_done(central_out)
    remaining = [u for u in _iter_product_urls(in_jsonl) if u not in done]
    if not remaining:
        print("Nothing to do: all URLs already present in central JSONL.")
        return

    # Shard remaining URLs and launch processes
    buckets = _shard_round_robin(remaining, workers)
    out_dir = central_out.parent

    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = []
        for sid, bucket in enumerate(buckets):
            if not bucket: 
                continue
            futures.append(ex.submit(_worker_run, sid, bucket, out_dir, headless))
        for f in as_completed(futures):
            # will raise if any worker crashed
            f.result()

    # Merge shards -> central, then dedupe just in case
    _merge_shards(out_dir, central_out)
    _dedupe_central(central_out)

    dt = time.time() - t0
    print(f"Parallel scrape done in {dt:.1f}s | workers={workers} | processed={len(remaining)}")


if __name__ == "__main__":
    # Start modest; bump workers if stable (e.g., to 6–8)
    run_part4_parallel(
        in_jsonl=PRODUCTS_JSONL,
        central_out=DETAILS_JSONL,
        workers=8,
        headless=False
    )
import json
import re
import time
import argparse
import shutil
import pathlib
from urllib.parse import urlparse, urljoin

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

BASE = "https://www.partselect.com"
ROOT = f"{BASE}/Repair/Dishwasher/"

SKIP_HEADING_PHRASES = {
    "how to fix a", "start your repair", "need help finding",
    "symptom list", "related", "other symptoms"
}

def setup_driver(headless: bool = False) -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()
    if headless:
        # New-headless so sites treat it like real Chrome
        opts.add_argument("--headless=new")
    # Make us look like a real browser
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,1000")
    opts.add_argument("--lang=en-US,en")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"
    )
    driver = webdriver.Chrome(options=opts)

    # A little stealth: remove webdriver flag (helps against 403/blocks)
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """},
        )
    except Exception:
        pass
    return driver

def wait_for(driver, locator, timeout=20):
    return WebDriverWait(driver, timeout).until(EC.presence_of_element_located(locator))

def get_symptom_links(driver) -> list[str]:
    """Get all symptom page links from the current ROOT."""
    driver.get(ROOT)
    wait_for(driver, (By.TAG_NAME, "body"))
    
    # Get path like "/Repair/Dishwasher/" from current ROOT
    root_path = urlparse(ROOT).path
    if not root_path.endswith("/"):
        root_path += "/"

    # Find all links that start with the current root path
    anchors = driver.find_elements(By.CSS_SELECTOR, f"a[href*='{root_path}']")
    links = set()
    
    for a in anchors:
        href = a.get_attribute("href") or ""
        if not href:
            continue
            
        parsed = urlparse(href)
        path = parsed.path.rstrip("/")
        parts = [p for p in path.split("/") if p]
        
        # Keep links with pattern /Repair/<Item>/<Symptom>/
        if (len(parts) >= 3 and 
            parts[0] == "Repair" and
            path.startswith(root_path.rstrip("/"))):
            links.add(urljoin(BASE, path + "/"))
            
    return sorted(links)

def parse_symptom_page(driver, url: str) -> list[dict]:
    """Extract content from a symptom page into item/symptom/part/text records."""
    records = []
    driver.get(url)
    
    try:
        wait_for(driver, (By.CSS_SELECTOR, "body"))
    except TimeoutException:
        return records

    # Ensure lazy-loaded content appears
    driver.execute_script("window.scrollTo(0, 150)")
    time.sleep(0.5)

    # Get item name from current ROOT
    item_name = ROOT.rstrip("/").split("/")[-1].replace("-", " ").title()
    # Get symptom from URL
    symptom = url.rstrip("/").split("/")[-1].replace("-", " ").title()

    # Find all part sections
    desc_blocks = driver.find_elements(By.CSS_SELECTOR, "div.symptom-list__desc")
    for desc in desc_blocks:
        # Try to find heading (h2/h3) that precedes this description
        try:
            heading = desc.find_element(
                By.XPATH, "preceding-sibling::h2[1] | preceding-sibling::h3[1]"
            )
            part = heading.text.strip()
        except NoSuchElementException:
            try:
                heading = desc.find_element(
                    By.XPATH, "ancestor::*/*[self::h2 or self::h3][1]"
                )
                part = heading.text.strip()
            except NoSuchElementException:
                continue

        if not part or is_bad_heading(part):
            continue

        text = gather_desc_text(desc)
        if not text:
            continue

        records.append({
            "item": item_name,
            "symptom": symptom,
            "part": part,
            "text": text
        })
        
    return records

def clean_text(t: str) -> str:
    t = re.sub(r"\r?\n\s*", "\n", t)     # tidy newlines
    t = re.sub(r"[ \t]+", " ", t)        # collapse spaces
    t = re.sub(r"\n{3,}", "\n\n", t)     # limit blank lines
    return t.strip()

def gather_desc_text(desc_el) -> str:
    # Grab text from <p>, <li>, and standalone text nodes in the desc block.
    parts = []
    # paragraphs
    for p in desc_el.find_elements(By.CSS_SELECTOR, "p"):
        txt = p.text.strip()
        if txt:
            parts.append(txt)
    # bullets
    for li in desc_el.find_elements(By.CSS_SELECTOR, "li"):
        txt = li.text.strip()
        if txt:
            parts.append(txt)
    # Fallback: if nothing, just take the whole block’s visible text.
    if not parts:
        block = desc_el.text.strip()
        if block:
            parts.append(block)
    return clean_text("\n".join(parts))

def is_bad_heading(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in SKIP_HEADING_PHRASES)

def scrape(output_path: str, headless: bool):
    driver = setup_driver(headless=headless)
    try:
        all_records = []
        symptom_links = get_symptom_links(driver)
        # (Optional) Keep only classic symptom pages we care about.
        # If you want to restrict, uncomment and list allowed:
        # allowed = {"Noisy","Leaking","Not Cleaning","Not Draining", ...}
        # symptom_links = [u for u in symptom_links if u.rstrip('/').split('/')[-1].replace('-',' ').title() in allowed]

        for i, link in enumerate(symptom_links, 1):
            print(f"[{i}/{len(symptom_links)}] {link}")
            try:
                recs = parse_symptom_page(driver, link)
                all_records.extend(recs)
                # polite delay so we don’t hammer the site
                time.sleep(0.7)
            except Exception as e:
                print(f"  ! Error on {link}: {e}")

        # De-duplicate by (symptom, part, first 80 chars of text)
        seen = set()
        with open(output_path, "w", encoding="utf-8") as f:
            for r in all_records:
                key = (r["symptom"].lower(), r["part"].lower(), r["text"][:80])
                if key in seen:
                    continue
                seen.add(key)
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"Saved {len(seen)} records to {output_path}")
    finally:
        driver.quit()

def merge_jsonl(src_files, out_file):
    out_path = pathlib.Path(out_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total = 0
    with out_path.open("w", encoding="utf-8") as out:
        for s in src_files:
            p = pathlib.Path(s)
            if not p.exists():
                print(f"[warn] missing {p}, skipping")
                continue
            with p.open("r", encoding="utf-8") as f:
                for ln in f:
                    ln = ln.rstrip("\n")
                    if not ln.strip():
                        continue
                    out.write(ln + "\n")
                    total += 1
    print(f"Wrote {total} lines to {out_path}")

if __name__ == "__main__":
    
    def _run_for(root_suffix: str, out_path: str, headless: bool = False):
        global ROOT
        ROOT = f"{BASE}{root_suffix}"
        print(f"Starting scrape for {ROOT} -> {out_path}")
        try:
            scrape(out_path, headless=headless)
        except Exception as e:
            print(f"[error] scrape failed for {ROOT}: {e}")

    # Adjust headless here if you want headless runs
    headless_mode = False

    # 1) Dishwasher
    _run_for("/Repair/Dishwasher/", "data/repair_data/dishwasher_repair.jsonl", headless=headless_mode)

    _run_for("/Repair/Refrigerator/", "data/repair_data/refrigerator_repair.jsonl", headless=headless_mode)


    SRC_FILES = [
        "data/repair_data/dishwasher_repair.jsonl",
        "data/repair_data/refrigerator_repair.jsonl",
    ]
    OUT_FILE = "data/repair_data/repairs.jsonl"

    merge_jsonl(SRC_FILES, OUT_FILE)

import json, time, random, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from tqdm import tqdm
from itertools import islice
from typing import Optional, List, Dict

# ====================== CONFIG ==========================
INPUT_FILE = "data/parts1/product_details.jsonl"
OUTPUT_FILE = "data/parts1/enriched/product_details_with_main_image_and_crossref.jsonl"
MAX_WORKERS = 8
LIMIT = None  # set to None for full run
HEADLESS = False  # set False to watch the browser
# ========================================================

# Thread-local storage for one driver per thread
thread_local = threading.local()

def get_driver():
    """Create or reuse a thread-local Chrome driver."""
    if not hasattr(thread_local, "driver") or thread_local.driver is None:
        options = Options()
        if HEADLESS:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        # You can add a UA if needed:
        # options.add_argument("user-agent=Mozilla/5.0 ...")
        thread_local.driver = webdriver.Chrome(options=options)
    return thread_local.driver

# --------------- Image extraction ---------------

def extract_main_image_from_open_page(driver):
    """Assumes the product page is already loaded in the given driver."""
    try:
        a = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.ID, "MagicZoom-PartImage-Images"))
        )
        return a.get_attribute("href")
    except Exception:
        # fallback selector
        try:
            a = driver.find_element(By.CSS_SELECTOR, ".MagicZoom-PartImage a[href]")
            return a.get_attribute("href")
        except Exception:
            return None

# --------------- Model Cross Reference extraction (no scrolling) ---------------

def _open_crossref(driver, wait_sec: int = 8) -> bool:
    """Ensure the 'Model Cross Reference' accordion is expanded."""
    try:
        title = WebDriverWait(driver, wait_sec).until(
            EC.presence_of_element_located((By.ID, "ModelCrossReference"))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", title)
        expanded = title.get_attribute("aria-expanded")
        if expanded != "true":
            title.click()
            WebDriverWait(driver, wait_sec).until(
                lambda d: title.get_attribute("aria-expanded") == "true"
            )
        return True
    except TimeoutException:
        return False

def _load_all_crossref_by_click(driver, pause: float = 0.25, max_stalls: int = 2, max_pages: Optional[int] = None):
    """
    Load ALL rows by repeatedly clicking the 'Load more...' sentinel (no scrolling).
    Returns the container element or None if not found.
    """
    if not _open_crossref(driver):
        return None

    try:
        container = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, ".pd__crossref__list.js-dataContainer.js-infiniteScroll")
            )
        )
    except TimeoutException:
        return None

    pages_clicked = 0
    stalls = 0
    prev_count = len(container.find_elements(By.CSS_SELECTOR, ":scope > .row"))

    while True:
        try:
            load_more = container.find_element(By.CSS_SELECTOR, ".js-loadNext")
        except NoSuchElementException:
            break  # nothing left to load

        # click via JS (works even if off-screen)
        driver.execute_script("arguments[0].click();", load_more)
        pages_clicked += 1
        if (max_pages is not None) and (pages_clicked >= max_pages):
            break

        time.sleep(pause)

        curr_count = len(container.find_elements(By.CSS_SELECTOR, ":scope > .row"))
        if curr_count <= prev_count:
            stalls += 1
            if stalls >= max_stalls:
                break
        else:
            stalls = 0
            prev_count = curr_count

    return container

def extract_model_cross_reference_fast(driver):
    """
    Parse *all* Model Cross Reference rows on the current product page.
    RETURNS: list of dicts: {brand, model_number, model_url, description}
    """
    try:
        container = _load_all_crossref_by_click(driver, pause=0.25, max_stalls=2, max_pages=None)
        if container is None:
            return []
        data = []
        rows = container.find_elements(By.CSS_SELECTOR, ":scope > .row")
        for row in rows:
            try:
                brand = row.find_element(By.CSS_SELECTOR, ".col-6.col-md-3").text.strip()
            except NoSuchElementException:
                brand = ""
            try:
                a = row.find_element(By.CSS_SELECTOR, "a[rel='nofollow']")
                model_number = a.text.strip()
                model_url = a.get_attribute("href")
            except NoSuchElementException:
                model_number = ""
                model_url = ""
            try:
                desc_el = row.find_element(By.CSS_SELECTOR, ".col.col-md-6.col-lg-7")
                description = " ".join(desc_el.text.split())
            except NoSuchElementException:
                description = ""

            if brand or model_number or description:
                data.append({
                    "brand": brand,
                    "model_number": model_number,
                    "model_url": model_url,
                    "description": description
                })
        return data
    except Exception:
        return []

# --------------- Worker ---------------

def process_product(product):
    url = product.get("product_url")
    if not url:
        product["main_image"] = None
        product["model_cross_reference"] = []
        return product

    driver = get_driver()
    try:
        driver.get(url)
        time.sleep(1.2 + random.random()*0.6)

        # main image
        product["main_image"] = extract_main_image_from_open_page(driver)

        # model cross reference (fast click-only loader)
        product["model_cross_reference"] = extract_model_cross_reference_fast(driver)

    except Exception as e:
        print(f"[WARN] Failed processing {url}: {e}")
        product.setdefault("main_image", None)
        product.setdefault("model_cross_reference", [])
    return product

# --------------- IO + Orchestration ---------------

def load_products(path, limit=None):
    with open(path, "r") as f:
        if limit is not None:
            return [json.loads(line) for line in islice(f, limit)]
        else:
            return [json.loads(line) for line in f]

# --- add these 2 helpers above main() ---
import os, glob, hashlib

def _choose_shard(url: str, n_shards: int) -> str:
    """Deterministically map a URL to a shard name shard-000..(n-1)."""
    h = int(hashlib.md5(url.encode("utf-8")).hexdigest(), 16)
    idx = h % max(1, n_shards)
    return f"shard-{idx:03d}.jsonl"

def _load_processed_urls(shard_dir: str) -> set[str]:
    """Scan existing shard files to build a set of already-processed product_url values."""
    done = set()
    for path in glob.glob(os.path.join(shard_dir, "shard-*.jsonl")):
        try:
            with open(path, "r") as f:
                for line in f:
                    try:
                        u = json.loads(line).get("product_url")
                        if u:
                            done.add(u)
                    except Exception:
                        continue
        except FileNotFoundError:
            continue
    return done

def _iter_jsonl(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                # skip bad lines
                continue

def _load_processed_urls(output_path):
    processed = set()
    if not os.path.exists(output_path):
        return processed
    for row in _iter_jsonl(output_path):
        url = row.get("product_url")
        if url:
            processed.add(url)
    return processed

def _write_shards(items, n_shards, shard_prefix):
    os.makedirs(os.path.dirname(shard_prefix), exist_ok=True)
    # Clear old shards (optional). Comment these two lines if you want to keep old shard files.
    for i in range(n_shards):
        p = f"{shard_prefix}_{i:03d}.jsonl"
        if os.path.exists(p):
            os.remove(p)

    # Round-robin assign to shards to balance sizes
    shard_files = [open(f"{shard_prefix}_{i:03d}.jsonl", "a", encoding="utf-8") for i in range(n_shards)]
    try:
        for idx, item in enumerate(items):
            shard_idx = idx % n_shards
            shard_files[shard_idx].write(json.dumps(item, ensure_ascii=False) + "\n")
    finally:
        for f in shard_files:
            f.close()

def main():
    # 1) Load processed set from OUTPUT_FILE (already-completed product_url)
    processed_urls = _load_processed_urls(OUTPUT_FILE)
    print(f"[resume] Found {len(processed_urls)} already-processed rows in output.")

    # 2) Load input and filter to remaining work
    all_items = []
    for row in _iter_jsonl(INPUT_FILE):
        url = row.get("product_url")
        if not url:
            continue
        if url in processed_urls:
            continue
        all_items.append(row)

    # 2a) Optional LIMIT
    if LIMIT is not None:
        all_items = all_items[:LIMIT]

    print(f"[resume] {len(all_items)} items remain to process after skipping completed ones.")

    if not all_items:
        print("[resume] Nothing to do. Exiting.")
        return

    # 3) Create fresh shards for remaining items only
    #    Reuse your previous shard naming convention; adjust the directory/prefix as needed.
    shard_prefix = "data/parts1/enriched/shard"
    n_shards = max(1, int(MAX_WORKERS))
    _write_shards(all_items, n_shards, shard_prefix)
    print(f"[resume] Wrote {n_shards} shard files for remaining items.")

    # 4) Thread-safe append to OUTPUT_FILE
    write_lock = threading.Lock()
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    # Reuse processed set in-memory for this run too (to avoid accidental dups in concurrent writes)
    processed_urls_local = set(processed_urls)  # copy to allow fast checks

    def worker(shard_idx):
        shard_path = f"{shard_prefix}_{shard_idx:03d}.jsonl"
        count_in = 0
        count_done = 0
        if not os.path.exists(shard_path):
            return (shard_idx, 0, 0, "missing")
        # One driver per thread
        driver = None
        try:
            driver = make_driver(HEADLESS)
            with open(shard_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    count_in += 1
                    url = item.get("product_url")
                    # Double-safety: skip if already processed (from previous runs or earlier in this run)
                    if not url or url in processed_urls_local:
                        continue

                    # Do the actual work
                    try:
                        result = process_one(item, driver)
                        if not result:
                            continue
                    except Exception as e:
                        # Log and continue to next
                        # You could also write failures to a separate failed_shard file
                        continue

                    # Thread-safe append + mark as processed locally
                    with write_lock:
                        # Final guard before writing (race-safe)
                        if url in processed_urls_local:
                            continue
                        with open(OUTPUT_FILE, "a", encoding="utf-8") as out:
                            out.write(json.dumps(result, ensure_ascii=False) + "\n")
                        processed_urls_local.add(url)
                        count_done += 1
        finally:
            if driver:
                try:
                    driver.quit()
                except Exception:
                    pass
        return (shard_idx, count_in, count_done, "ok")

    # 5) Run pool
    with ThreadPoolExecutor(max_workers=n_shards) as ex:
        futures = {ex.submit(worker, i): i for i in range(n_shards)}
        for fut in as_completed(futures):
            idx = futures[fut]
            try:
                shard_idx, count_in, count_done, status = fut.result()
                print(f"[worker {shard_idx:03d}] status={status} read={count_in} wrote={count_done}")
            except Exception as e:
                print(f"[worker {idx:03d}] crashed: {e}")

    print("[resume] All workers complete.")

if __name__ == "__main__":
    main()
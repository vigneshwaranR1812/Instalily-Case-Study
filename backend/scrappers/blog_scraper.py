import csv, json, random, re, time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import pathlib
import time as _time
from typing import Optional, List, Dict

BASE = "https://www.partselect.com"
LIST = f"{BASE}/content/blog"

ARTICLE_WRAPPER_SELECTORS = [
    ".blog__article-page_content",       # most pages
    ".blog__article-page .blog__article-page_content",
    ".blog__article-page",               # parent wrapper
    "main.container article",            # generic fallback
    "article",                           # broadest
]
TITLE_SELECTORS = [
    ".blog__article-page_content h1",
    ".blog__article-page h1",
    "main.container article h1",
    "article h1",
    "h1",
]

# ----------- Config you may tweak ----------
HEADLESS = False
NUM_PAGES = 19
FILTER_KEYWORDS = [
    "fridge", "refrigerator", "freezer",
    "dishwasher", "washer", "washing machine",
    "ice", "cooling", "temperature"
]
CSV_ALL = "data/blog_data/all_blogs.csv"
CSV_FILTERED = "data/blog_data/filtered_blogs.csv"
JSONL_ARTICLES = "data/blog_data/filtered_articles.jsonl"
# -------------------------------------------


# ---------------- Driver ----------------
def make_driver(headless=HEADLESS):
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1280,900")
    opts.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.page_load_strategy = "eager"
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    try:
        driver.execute_cdp_cmd("Network.enable", {})
        driver.execute_cdp_cmd("Network.setBlockedURLs", {"urls": [
            "*.png", "*.jpg", "*.jpeg", "*.gif", "*.webp", "*.svg",
            "*.woff", "*.woff2", "*.ttf", "*.otf", "*.mp4", "*.avi", "*.webm"
        ]})
    except Exception:
        pass
    try:
        driver.execute_script("Object.defineProperty(navigator,'webdriver',{get:() => undefined})")
    except Exception:
        pass
    return driver

# --------------- Small helpers ----------------
def human_pause(a=0.6, b=1.2):
    time.sleep(random.uniform(a, b))

def _timed(label):
    start = _time.perf_counter()
    def done():
        print(f"[timing] {label}: {_time.perf_counter()-start:.2f}s")
    return done

def page_ready(driver, timeout=5):
    t_done = _timed(f"page_ready")
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") == "complete"
    )
    t_done()

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
                # fallback to JS click if normal click fails
                try:
                    driver.execute_script("arguments[0].click();", el)
                except Exception:
                    pass
            return True
        except Exception:
            pass
    return False

def dismiss_popups(driver, max_iframes=5):
    """
    Fast popup dismissal:
    - Try page-level buttons quickly (no long waits).
    - Send ESC once as a cheap fallback.
    - Only scan a few iframes and use non-blocking checks inside them.
    """
    t_done = _timed("dismiss_popups")

    # quick page-level buttons/links
    if _try_click_first(
        driver,
        (By.XPATH, "//button[normalize-space()='Decline']"),
        (By.XPATH, "//a[normalize-space()='Decline']"),
        (By.CSS_SELECTOR, "button[aria-label='Close'], .mfp-close, .modal .close, .ps-modal .close"),
    ):
        t_done()
        return

    # quick ESC fallback (no long sleep)
    try:
        body = driver.find_element(By.TAG_NAME, "body")
        body.send_keys(Keys.ESCAPE)
        human_pause(0.05, 0.12)
    except Exception:
        pass

    # iframe fallback: only inspect a few frames and use fast clicks
    try:
        frames = driver.find_elements(By.TAG_NAME, "iframe")
        for idx, f in enumerate(frames[:max_iframes]):
            try:
                driver.switch_to.frame(f)
                if _try_click_first(
                    driver,
                    (By.XPATH, "//button[normalize-space()='Decline']"),
                    (By.XPATH, "//a[normalize-space()='Decline']"),
                    (By.CSS_SELECTOR, "button[aria-label='Close'], .mfp-close, .modal .close"),
                ):
                    driver.switch_to.default_content()
                    t_done()
                    return
            except Exception:
                pass
            finally:
                driver.switch_to.default_content()
    except Exception:
        pass
    t_done()

def is_access_denied(driver):
    try:
        title = (driver.title or "").lower()
        body = (driver.find_element(By.TAG_NAME, "body").text or "").lower()
        return "access denied" in title or "access denied" in body
    except Exception:
        return False

def safe_get(driver, url, retries=2):
    t_done = _timed(f"safe_get")
    for k in range(retries + 1):
        driver.get(url)
        page_ready(driver)
        dismiss_popups(driver)
        if not is_access_denied(driver):
            return True
        human_pause(0.4, 1.0)
        try:
            driver.execute_script("window.location = arguments[0];", url)
        except Exception:
            pass
        human_pause(0.4, 1.0)

    t_done()
    return False

# -----------Part 3----------------

PUBLISH_RE = re.compile(r"\bPUBLISHED ON\s+(.+)", re.I)

def _debug_snapshot(driver, tag="article"):
    pathlib.Path("debug").mkdir(exist_ok=True)
    try:
        driver.save_screenshot(f"debug/{tag}.png")
        with open(f"debug/{tag}.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"[debug] saved debug/{tag}.png and debug/{tag}.html")
    except Exception:
        pass

def _wait_for_any_selector(driver, selectors, timeout=25):
    def any_found(d):
        for sel in selectors:
            if d.find_elements(By.CSS_SELECTOR, sel):
                return True
        return False
    WebDriverWait(driver, timeout).until(any_found)

# --------- YouTube helpers (section-aware) ---------
_YT_ID_RE = re.compile(r"([a-zA-Z0-9_-]{6,})")

def _youtube_watch_url_from_id(vid: str) -> Optional[str]:
    vid = (vid or "").strip()
    return f"https://www.youtube.com/watch?v={vid}" if vid else None

def _extract_video_url_from_container(container_el):
    """
    Given a node that *may* contain a YouTube video (lazy or iframe),
    return a best-effort primary watch URL, or None.
    Supports:
      - <div class="yt-video" data-yt-init="VIDEO_ID">...</div>
      - <iframe src="https://www.youtube.com/embed/VIDEO_ID?...">
      - <img src="https://img.youtube.com/vi/VIDEO_ID/...">
    """
    # 1) data-yt-init on the container
    try:
        vid = (container_el.get_attribute("data-yt-init") or "").strip()
        if vid and _YT_ID_RE.fullmatch(vid):
            return _youtube_watch_url_from_id(vid)
    except Exception:
        pass

    # 2) descendant iframe embed
    try:
        iframe = container_el.find_element(
            By.CSS_SELECTOR,
            "iframe[src*='youtube.com/embed'],iframe[src*='youtube-nocookie.com/embed']"
        )
        src = (iframe.get_attribute("src") or "")
        m = re.search(r"/embed/([a-zA-Z0-9_-]{6,})", src)
        if m:
            return _youtube_watch_url_from_id(m.group(1))
        if "youtube" in src:
            return src.split("?")[0]  # rare fallback
    except Exception:
        pass

    # 3) descendant thumbnail (img.youtube.com/vi/VIDEO_ID/..)
    try:
        img = container_el.find_element(By.CSS_SELECTOR, "img[src*='img.youtube.com/vi/']")
        src = (img.get_attribute("src") or "")
        m = re.search(r"img\.youtube\.com/vi/([^/]+)/", src)
        if m:
            return _youtube_watch_url_from_id(m.group(1))
    except Exception:
        pass

    return None

def extract_sections_with_videos(driver):
    """
    Split the article into ordered sections by H2/H3/H4.
    For each section, collect paragraph/list text and the *first* YouTube video URL
    found inside that section (or None).
    Returns: list[{"heading": str|None, "text": str, "video": str|None}]
    """
    # find a wrapper that contains the article body
    article = None
    for wrapper_sel in ARTICLE_WRAPPER_SELECTORS:
        try:
            el = driver.find_element(By.CSS_SELECTOR, wrapper_sel)
            if el:
                article = el
                break
        except Exception:
            continue
    if article is None:
        return []

    # gentle scroll to trigger lazy loads
    try:
        driver.execute_script("window.scrollTo(0, 0);")
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        driver.execute_script("window.scrollTo(0, 0);")
    except Exception:
        pass

    # we will iterate the content in DOM order (headings, text blocks, video blocks)
    nodes = article.find_elements(
        By.XPATH,
        ".//*[(self::h1 or self::h2 or self::h3 or self::h4 or "
        "      self::p or self::ol or self::ul or "
        "      (self::div and contains(@class,'yt-video')) or "
        "      (self::div and contains(@style,'position') and contains(@style,'relative')))]"
    )

    sections = []
    current = None

    def _flush():
        nonlocal current
        if current is None:
            return
        # normalize
        current["text"] = re.sub(r"\s+\n", "\n", current["text"]).strip()
        if not current["heading"] and current["text"]:
            current["heading"] = "Introduction"
        # avoid pushing a completely empty shell
        if current["heading"] or current["text"] or current["video"]:
            sections.append(current)
        current = None

    for n in nodes:
        tag = n.tag_name.lower()

        # Start a new section on headings
        if tag in ("h2", "h3", "h4"):
            _flush()
            heading = (n.text or "").strip()
            current = {"heading": heading, "text": "", "video": None}
            continue

        if current is None:
            current = {"heading": None, "text": "", "video": None}

        # text capture
        if tag == "p":
            t = (n.text or "").strip()
            if t:
                current["text"] += (("\n" if current["text"] else "") + t)

        elif tag in ("ol", "ul"):
            try:
                items = [li.text.strip() for li in n.find_elements(By.TAG_NAME, "li")]
                items = [i for i in items if i]
                if items:
                    if current["text"]:
                        current["text"] += "\n"
                    for idx, it in enumerate(items, 1):
                        bullet = f"{idx}. {it}" if tag == "ol" else f"• {it}"
                        current["text"] += (("\n" if current["text"] else "") + bullet)
            except Exception:
                pass

        # video capture: current section only (first video wins)
        if tag == "div" and current.get("video") is None:
            is_yt_block = False
            try:
                cls = (n.get_attribute("class") or "")
                if "yt-video" in cls:
                    is_yt_block = True
                else:
                    # parent wrapper with inline style often surrounds yt-video
                    n.find_element(By.CSS_SELECTOR, "div.yt-video")
                    is_yt_block = True
            except Exception:
                is_yt_block = False

            if is_yt_block:
                url = _extract_video_url_from_container(n)
                if url:
                    current["video"] = url

    _flush()
    return sections

def extract_article(driver, url):
    """Extract article split into heading/text/video sections + page-level video list."""
    if not safe_get(driver, url):
        print("[warn] navigation failed (access denied).")
        return None

    dismiss_popups(driver)

    try:
        _wait_for_any_selector(driver, ARTICLE_WRAPPER_SELECTORS + TITLE_SELECTORS, timeout=25)
    except Exception:
        if is_access_denied(driver):
            if not safe_get(driver, url):
                return None
        else:
            return None

    # Ensure lazy content loads
    human_pause(0.6, 1.0)
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        human_pause(0.5, 0.9)
        driver.execute_script("window.scrollTo(0, 0);")
    except Exception:
        pass

    # Title
    title = ""
    for sel in TITLE_SELECTORS:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            t = el.text.strip()
            if t:
                title = t
                break
        except Exception:
            pass

    # Sectionized content with per-section video
    sections = extract_sections_with_videos(driver)

    if not title and not sections:
        return None

    # Page-level convenience: deduped list of all video URLs on the page
    video_urls = sorted({s["video"] for s in sections if s.get("video")})

    return {
        "url": url,
        "title": title,
        "sections": sections,        # list of {"heading","text","video"}
        "video_urls": video_urls     # page-level deduped list
    }

def scrape_articles_from_csv(csv_path=CSV_FILTERED, headless=HEADLESS, limit=None):
    """Scrape articles from CSV and return list of structured article docs."""
    links = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            links.append((r["title"], r["url"]))

    driver = make_driver(headless=headless)
    docs = []
    try:
        total = len(links) if not limit else min(limit, len(links))
        for i, (_, url) in enumerate(links, start=1):
            if limit and i > limit:
                break
            print(f"[article] {i}/{total} -> {url}")
            doc = extract_article(driver, url)
            if doc:
                docs.append(doc)
            else:
                print(f"[warn] failed to extract: {url}")
            human_pause(0.2, 0.4)
    finally:
        driver.quit()
    return docs

def save_articles_jsonl(docs, path=JSONL_ARTICLES):
    if not docs:
        print("No article docs to save.")
        return
    with open(path, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"✅ Saved {len(docs)} articles to {path}")

# ---------------- Entry point ----------------
if __name__ == "__main__":
    # 1) Scrape list pages -> CSV_ALL
    # all_links = scrape_all_pages(num_pages=NUM_PAGES, headless=HEADLESS)
    # save_links_csv(all_links, CSV_ALL)

    # # # 2) Filter to refrigerator/dishwasher topics -> CSV_FILTERED
    # filtered = filter_links(CSV_ALL, FILTER_KEYWORDS)
    # print(f"Filtered to {len(filtered)} relevant articles")
    # save_links_csv(filtered, CSV_FILTERED)

    # # 3) Open each filtered link and extract article text -> JSONL_ARTICLES
    docs = scrape_articles_from_csv(csv_path=CSV_FILTERED, headless=HEADLESS, limit=None)
    save_articles_jsonl(docs, JSONL_ARTICLES)
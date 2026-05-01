import csv
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://nguyenson.vn"
START_URL = "https://nguyenson.vn/"
OUTPUT_DIR = r"C:\Users\Kieu Doan Dat\VSCode\ChatbotF&B\output_nguyenson"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

REQUEST_DELAY_SECONDS = 1.0

POLICY_URLS = [
    "https://nguyenson.vn/pages/chinh-sach-doi-tra",
    "https://nguyenson.vn/pages/thanh-toan",
    "https://nguyenson.vn/pages/ban-hang",
    "https://nguyenson.vn/pages/chinh-sach-bao-mat-dieu-khoan-su-dung",
    "https://nguyenson.vn/pages/chinh-sach-chat-luong-attp",
]

session = requests.Session()
session.headers.update(HEADERS)


def ensure_output_dir():
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def fetch_html(url: str) -> str:
    response = session.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def get_soup(url: str) -> BeautifulSoup:
    html = fetch_html(url)
    return BeautifulSoup(html, "html.parser")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def clean_url(url: str) -> str:
    if not url:
        return ""
    return url.split("?")[0].strip()


def parse_price_to_int(price_text: str):
    if not price_text:
        return None
    match = re.search(r"(\d[\d,\.]*)\s*[₫đ]", price_text)
    if not match:
        return None
    raw = match.group(1).replace(",", "").replace(".", "")
    try:
        return int(raw)
    except ValueError:
        return None


def save_csv(path: str, rows: list[dict], fieldnames: list[str]):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def save_jsonl(path: str, rows: list[dict]):
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def extract_categories():
    soup = get_soup(START_URL)
    categories = []
    seen = set()

    blacklist = {
        'xem tất cả "sản phẩm"',
        'xem tất cả "liên hệ"',
        "mua ngay",
        "xem thêm",
        "xem ngay",
    }

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        text = normalize_space(a.get_text(" ", strip=True))

        if not href.startswith("/collections/"):
            continue
        if not text:
            continue
        if text.lower() in blacklist:
            continue

        full_url = urljoin(BASE_URL, clean_url(href))
        key = (text, full_url)
        if key in seen:
            continue

        seen.add(key)
        categories.append({
            "category_name": text,
            "category_url": full_url,
            "source_url": START_URL,
        })

    return categories


def extract_product_links_from_collection(collection_url: str):
    soup = get_soup(collection_url)
    links = set()

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if href.startswith("/products/"):
            links.add(urljoin(BASE_URL, clean_url(href)))

    return sorted(links)


def extract_breadcrumb_category(page_text: str) -> str:
    m = re.search(r"1\.\s*Trang chủ\s*2\.\s*(.*?)\s*3\.\s*", page_text, re.S)
    if m:
        return normalize_space(m.group(1))
    return ""


def extract_product_block(page_text: str) -> str:
    """
    Chỉ lấy block sản phẩm thật để tránh dính:
    - TỔNG TIỀN: 0₫
    - giá ở phần sản phẩm liên quan

    Fix:
    - không bắt SKU phải có giá trị
    """
    patterns = [
        r"(SKU:\s*.*?)(?=##\s*Mô tả)",
        r"(SKU:\s*.*?)(?=Sản phẩm liên quan)",
        r"(SKU:\s*.*)",
    ]

    for pattern in patterns:
        m = re.search(pattern, page_text, re.S)
        if m:
            return m.group(1)

    return ""


def normalize_price(product_block: str):
    """
    Rule:
    - có Liên hệ + 0₫ => không phải giá thật
    - 0₫ đơn lẻ cũng xem là chưa công bố giá
    - trả về: price_default, price_default_text, price_status
    """
    block = product_block or ""
    has_contact = "Liên hệ" in block

    m = re.search(r"(\d[\d,\.]*)\s*[₫đ]", block)
    if not m:
        if has_contact:
            return None, "Liên hệ", "contact_required"
        return None, "", "missing"

    price_text = f"{m.group(1)}₫"
    price_value = parse_price_to_int(price_text)

    if price_value == 0:
        return None, "Liên hệ", "contact_required"

    return price_value, price_text, "available"


def extract_variants_from_product_block(product_block: str):
    """
    Ví dụ:
    20 cm - 365,000₫
    28 cm - 615,000₫
    75g - 27,000₫
    Default Title - 0₫
    """
    pattern = r"([0-9A-Za-zÀ-ỹxX\s]+?)\s*-\s*(\d[\d,\.]*[₫đ])"
    matches = re.findall(pattern, product_block or "")

    variants = []
    seen = set()
    has_contact = "Liên hệ" in (product_block or "")

    for variant_name, variant_price_text in matches:
        name = normalize_space(variant_name)
        price_text = normalize_space(variant_price_text).replace("đ", "₫")
        price_value = parse_price_to_int(price_text)

        if not name:
            continue
        if len(name) > 50:
            continue

        if (has_contact and price_value == 0) or price_value == 0:
            price_value = None
            price_text = "Liên hệ"

        key = (name, price_text)
        if key in seen:
            continue
        seen.add(key)

        variants.append({
            "variant_name": name,
            "variant_price_text": price_text,
            "variant_price": price_value,
        })

    return variants


def extract_description(page_text: str) -> str:
    patterns = [
        r"##\s*Mô tả\s*(.*?)\s*##\s*Sản phẩm liên quan",
        r"##\s*Mô tả\s*(.*?)\s*Sản phẩm liên quan",
        r"##\s*Mô tả\s*(.*)",
    ]

    for pattern in patterns:
        m = re.search(pattern, page_text, re.S)
        if m:
            return normalize_space(m.group(1))

    return ""


def looks_like_product_image(url: str) -> bool:
    url_lower = url.lower()

    # bỏ base64 / icon / placeholder / logo / sprite
    bad_keywords = [
        "data:image",
        "logo",
        "icon",
        "sprite",
        "placeholder",
        "loading",
        "favicon",
        "facebook",
        "messenger",
        "zalo",
        "youtube",
        "banner",
    ]
    if any(k in url_lower for k in bad_keywords):
        return False

    # ưu tiên ảnh từ các host quen thuộc của site / shop
    good_keywords = [
        "product.hstatic.net",
        "file.hstatic.net",
        "hstatic.net",
        "cdn.shopify.com",
    ]
    return any(k in url_lower for k in good_keywords)


def extract_product_images(soup: BeautifulSoup, product_url: str):
    """
    Fix:
    - không lọc cứng chỉ product.hstatic.net
    - bắt thêm srcset
    """
    images = []
    seen = set()

    for img in soup.select("img"):
        candidates = [
            img.get("src"),
            img.get("data-src"),
            img.get("data-original"),
            img.get("data-lazyload"),
        ]

        srcset = img.get("srcset")
        if srcset:
            for part in srcset.split(","):
                url_part = part.strip().split(" ")[0]
                if url_part:
                    candidates.append(url_part)

        candidates = [c for c in candidates if c]

        for src in candidates:
            full_src = urljoin(product_url, src)
            full_src = clean_url(full_src)

            if not full_src.startswith("http"):
                continue
            if not looks_like_product_image(full_src):
                continue

            alt = normalize_space(img.get("alt") or "")

            key = (full_src, alt)
            if key in seen:
                continue
            seen.add(key)

            images.append({
                "product_url": product_url,
                "image_url": full_src,
                "image_alt": alt,
                "source_site": "Nguyễn Sơn Bakery",
                "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

    return images


def build_raw_text(
    name: str,
    category: str,
    sku: str,
    price_default_text: str,
    price_status: str,
    variants: list[dict],
    description: str,
    image_count: int,
    product_url: str,
):
    parts = []

    if name:
        parts.append(f"Tên sản phẩm: {name}")
    if category:
        parts.append(f"Danh mục: {category}")
    if sku:
        parts.append(f"SKU: {sku}")

    if price_status == "available" and price_default_text:
        parts.append(f"Giá mặc định: {price_default_text}")
    elif price_status == "contact_required":
        parts.append("Giá: Liên hệ")
    else:
        parts.append("Giá: Chưa có dữ liệu")

    if variants:
        variant_texts = []
        for v in variants:
            v_name = v.get("variant_name", "")
            v_price_text = v.get("variant_price_text", "")
            if v_name and v_price_text:
                variant_texts.append(f"{v_name} - {v_price_text}")
        if variant_texts:
            parts.append(f"Biến thể: {', '.join(variant_texts)}")

    if description:
        parts.append(f"Mô tả: {description}")

    parts.append(f"Số lượng ảnh: {image_count}")
    if product_url:
        parts.append(f"Nguồn: {product_url}")

    return " | ".join(parts)


def extract_product_detail(product_url: str):
    soup = get_soup(product_url)
    page_text = soup.get_text("\n", strip=True)

    name = ""
    h1 = soup.find("h1")
    if h1:
        name = normalize_space(h1.get_text())

    sku = ""
    sku_match = re.search(r"SKU:\s*([A-Za-z0-9\-]+)", page_text)
    if sku_match:
        sku = sku_match.group(1)

    product_block = extract_product_block(page_text)

    price_default, price_default_text, price_status = normalize_price(product_block)
    category = extract_breadcrumb_category(page_text)
    variants = extract_variants_from_product_block(product_block)
    description = extract_description(page_text)
    images = extract_product_images(soup, product_url)

    raw_text = build_raw_text(
        name=name,
        category=category,
        sku=sku,
        price_default_text=price_default_text,
        price_status=price_status,
        variants=variants,
        description=description,
        image_count=len(images),
        product_url=product_url,
    )

    product_row = {
        "name": name,
        "sku": sku,
        "category": category,
        "price_default_text": price_default_text,
        "price_default": price_default,
        "price_status": price_status,
        "variants_json": json.dumps(variants, ensure_ascii=False),
        "description": description,
        "image_count": len(images),
        "product_url": product_url,
        "source_site": "Nguyễn Sơn Bakery",
        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "raw_text": raw_text,
    }

    return product_row, images


def crawl_policy(url: str):
    soup = get_soup(url)
    page_text = soup.get_text("\n", strip=True)

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = normalize_space(h1.get_text())

    content = normalize_space(page_text)

    return {
        "page_title": title,
        "page_url": url,
        "content": content,
        "source_site": "Nguyễn Sơn Bakery",
        "last_checked": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_rag_documents(product_rows: list[dict]):
    docs = []
    for row in product_rows:
        docs.append({
            "id": row["sku"] or row["product_url"],
            "text": row["raw_text"],
            "metadata": {
                "name": row["name"],
                "sku": row["sku"],
                "category": row["category"],
                "price_default_text": row["price_default_text"],
                "price_status": row["price_status"],
                "product_url": row["product_url"],
                "source_site": row["source_site"],
                "last_checked": row["last_checked"],
            }
        })
    return docs


def main():
    ensure_output_dir()

    print("=== BƯỚC 1: Crawl categories ===")
    categories = extract_categories()

    # Nếu muốn test nhanh 1 nhóm, mở dòng dưới:
    # categories = [c for c in categories if c["category_name"].lower() == "bánh công nghiệp"]

    categories_path = os.path.join(OUTPUT_DIR, "categories.csv")
    save_csv(
        categories_path,
        categories,
        ["category_name", "category_url", "source_url"]
    )
    print(f"Saved: {categories_path} ({len(categories)} categories)")

    print("\n=== BƯỚC 2: Lấy product links từ từng category ===")
    all_product_links = set()

    for category in categories:
        category_name = category["category_name"]
        category_url = category["category_url"]

        try:
            links = extract_product_links_from_collection(category_url)
            for link in links:
                all_product_links.add(link)

            print(f"[OK] {category_name}: {len(links)} product links")
        except Exception as e:
            print(f"[ERROR] {category_name} - {category_url} - {e}")

        time.sleep(REQUEST_DELAY_SECONDS)

    all_product_links = sorted(all_product_links)
    print(f"\nTổng số product links unique: {len(all_product_links)}")

    print("\n=== BƯỚC 3: Crawl product detail + images ===")
    products = []
    product_images = []

    for idx, product_url in enumerate(all_product_links, start=1):
        try:
            product_row, images = extract_product_detail(product_url)
            products.append(product_row)
            product_images.extend(images)

            print(
                f"[{idx}/{len(all_product_links)}] OK - "
                f"{product_row['name']} | "
                f"price={product_row['price_default_text']} | "
                f"status={product_row['price_status']} | "
                f"images={len(images)}"
            )
        except Exception as e:
            print(f"[{idx}/{len(all_product_links)}] ERROR - {product_url} - {e}")

        time.sleep(REQUEST_DELAY_SECONDS)

    print("\n=== BƯỚC 4: Crawl policy pages ===")
    policies = []
    for url in POLICY_URLS:
        try:
            policy_row = crawl_policy(url)
            policies.append(policy_row)
            print(f"[OK] Policy - {url}")
        except Exception as e:
            print(f"[ERROR] Policy - {url} - {e}")

        time.sleep(REQUEST_DELAY_SECONDS)

    products_path = os.path.join(OUTPUT_DIR, "products.csv")
    product_images_path = os.path.join(OUTPUT_DIR, "product_images.csv")
    policies_path = os.path.join(OUTPUT_DIR, "policies.csv")
    rag_docs_path = os.path.join(OUTPUT_DIR, "products.jsonl")

    save_csv(
        products_path,
        products,
        [
            "name",
            "sku",
            "category",
            "price_default_text",
            "price_default",
            "price_status",
            "variants_json",
            "description",
            "image_count",
            "product_url",
            "source_site",
            "last_checked",
            "raw_text",
        ]
    )

    save_csv(
        product_images_path,
        product_images,
        [
            "product_url",
            "image_url",
            "image_alt",
            "source_site",
            "last_checked",
        ]
    )

    save_csv(
        policies_path,
        policies,
        [
            "page_title",
            "page_url",
            "content",
            "source_site",
            "last_checked",
        ]
    )

    rag_docs = build_rag_documents(products)
    save_jsonl(rag_docs_path, rag_docs)

    print(f"\nSaved: {products_path} ({len(products)} products)")
    print(f"Saved: {product_images_path} ({len(product_images)} images)")
    print(f"Saved: {policies_path} ({len(policies)} policies)")
    print(f"Saved: {rag_docs_path} ({len(rag_docs)} docs)")
    print("\nHoàn tất.")


if __name__ == "__main__":
    main()
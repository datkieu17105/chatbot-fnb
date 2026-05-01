from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "output_nguyenson"
DATA_OUTPUT_DIR = ROOT_DIR / "data"
OUTPUT_JS = DATA_OUTPUT_DIR / "store-data.js"
OUTPUT_JSON = DATA_OUTPUT_DIR / "store-data.json"

PRODUCTS_CSV = DATA_DIR / "products.csv"
IMAGES_CSV = DATA_DIR / "product_images.csv"
POLICIES_CSV = DATA_DIR / "policies.csv"
CATEGORIES_CSV = DATA_DIR / "categories.csv"


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_space(text: str | None) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def normalize_match(text: str | None) -> str:
    base = normalize_space(text).lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", base)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def slugify(text: str | None) -> str:
    return normalize_match(text).replace(" ", "-")


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = normalize_space(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def parse_price_number(raw_value: str | None, raw_text: str | None) -> int | None:
    direct = normalize_space(raw_value)
    if direct.isdigit():
        return int(direct)

    text = normalize_space(raw_text)
    if not text:
        return None

    match = re.search(r"(\d[\d\.,]*)", text)
    if not match:
        return None

    digits_only = re.sub(r"[^\d]", "", match.group(1))
    if not digits_only:
        return None

    return int(digits_only)


def format_price_label(price_value: int | None, price_status: str, raw_text: str | None) -> str:
    if price_status == "contact_required":
        return "Liên hệ"
    if price_value is None:
        return normalize_space(raw_text) or "Chưa có giá"
    return f"{price_value:,}".replace(",", ".") + "₫"


def parse_variants(raw_variants: str | None) -> list[dict[str, object]]:
    raw = normalize_space(raw_variants)
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []

    variants: list[dict[str, object]] = []
    for item in parsed:
        name = normalize_space(str(item.get("variant_name", "")))
        price_value = item.get("variant_price")
        if isinstance(price_value, str):
            price_value = parse_price_number(price_value, item.get("variant_price_text"))
        elif isinstance(price_value, (int, float)):
            price_value = int(price_value)
        else:
            price_value = parse_price_number("", item.get("variant_price_text"))

        price_status = "available" if price_value else "contact_required"
        variants.append(
            {
                "name": name,
                "priceValue": price_value,
                "priceLabel": format_price_label(
                    price_value,
                    price_status,
                    str(item.get("variant_price_text", "")),
                ),
            }
        )

    return variants


def build_image_lookup(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        product_url = normalize_space(row.get("product_url"))
        image_url = normalize_space(row.get("image_url"))
        if not product_url or not image_url:
            continue
        grouped[product_url].append(
            {
                "url": image_url,
                "alt": normalize_space(row.get("image_alt")),
            }
        )
    return grouped


def score_image_candidate(product_name: str, product_slug: str, image_row: dict[str, str], index: int) -> tuple[int, int]:
    alt_key = normalize_match(image_row.get("alt"))
    url_key = normalize_match(urlparse(image_row.get("url", "")).path.split("/")[-1])
    name_key = normalize_match(product_name)

    score = 0
    if product_slug and product_slug in url_key:
        score += 10
    if name_key and name_key in alt_key:
        score += 8
    if alt_key == name_key:
        score += 6
    if "_master" in image_row.get("url", ""):
        score += 2

    return (score, -index)


def choose_product_images(product_name: str, product_url: str, candidates: list[dict[str, str]]) -> list[str]:
    if not candidates:
        return []

    product_slug = slugify(product_url.rstrip("/").split("/")[-1])
    scored = sorted(
        enumerate(candidates),
        key=lambda item: score_image_candidate(product_name, product_slug, item[1], item[0]),
        reverse=True,
    )

    selected: list[str] = []
    for _, row in scored:
        image_url = normalize_space(row.get("url"))
        if not image_url or image_url in selected:
            continue
        selected.append(image_url)
        if len(selected) == 4:
            break

    return selected


def infer_product_group(name: str, product_url: str) -> str:
    normalized = normalize_match(f"{name} {product_url}")

    if "dong lanh" in normalized or "frozen" in normalized:
        return "Đồ đông lạnh"
    if any(term in normalized for term in ("bo do an", "nen", "phu kien")):
        return "Phụ kiện"
    if any(term in normalized for term in ("banh bao", "banh khao", "banh cha", "quay", "vung vong", "truyen thong")):
        return "Bánh truyền thống"
    if any(term in normalized for term in ("cookie", "cookies", "tuile", "biscotte", "rocher", "almond salt")):
        return "Cookies & snack"
    if any(
        term in normalized
        for term in (
            "croissant",
            "baguette",
            "brioche",
            "sandwich",
            "hamburger",
            "pain aux",
            "pate chaud",
            "banh my",
            "banh mi",
        )
    ):
        return "Bánh mỳ"
    if normalized.startswith("chocolate ") or re.search(r"\bchocolate\s+\d+\b", normalized):
        return "Chocolate"
    if any(
        term in normalized
        for term in (
            "cake",
            "gateaux",
            "gato",
            "mousse",
            "donut",
            "su kem",
            "charlotte",
            "madeleine",
            "bong lan",
            "cheese",
            "delicacy",
            "petit",
        )
    ):
        return "Bánh ngọt"
    return "Khác"


def extract_tokens(*parts: str) -> list[str]:
    raw = normalize_match(" ".join(part for part in parts if part))
    stop_words = {
        "banh",
        "va",
        "voi",
        "loai",
        "set",
        "mix",
        "piece",
        "nguyen",
        "son",
    }
    tokens = [token for token in raw.split() if len(token) > 1 and token not in stop_words]
    return unique_preserve_order(tokens)


def split_sentences(text: str) -> list[str]:
    prepared = normalize_space(text)
    prepared = re.sub(r"\s*-\s*", ". ", prepared)
    prepared = re.sub(r"(?<=[a-zà-ỹ0-9])\s+(?=[A-ZÀ-Ỹ])", ". ", prepared)
    chunks = re.split(r"(?<=[\.\!\?;:])\s+", prepared)

    results: list[str] = []
    for chunk in chunks:
        cleaned = normalize_space(chunk)
        if 20 <= len(cleaned) <= 260:
            results.append(cleaned)
    return results


def sanitize_policy_text(text: str) -> str:
    cleaned = normalize_space(text)
    cleaned = re.sub(
        r"This site is protected by reCAPTCHA and the Google Privacy Policy and Terms of Service apply\.",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"let recaptchaElm=.*?requestSubmit\(formEvent\.submitter\)\}\)\}\)",
        " ",
        cleaned,
        flags=re.IGNORECASE,
    )
    if "Đăng ký nhận tin" in cleaned:
        cleaned = cleaned.split("Đăng ký nhận tin", 1)[0]
    return normalize_space(cleaned)


def find_pattern_matches(text: str, patterns: list[str]) -> list[str]:
    matches: list[str] = []
    seen: set[str] = set()

    for pattern in patterns:
        found = re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE)
        if not found:
            continue
        match_text = normalize_space(found.group(0))
        match_key = normalize_match(match_text)
        if match_key in seen:
            continue
        seen.add(match_key)
        matches.append(match_text)

    return matches


def extract_policy_highlights(title: str, content: str, combined_context: str) -> list[str]:
    normalized_title = normalize_match(title)
    cleaned_content = sanitize_policy_text(content)
    curated_highlights_map = {
        "doi tra": [
            "Khách hàng cần kiểm tra kỹ sản phẩm trước khi mua.",
            "Sản phẩm đã bán ra không nhập lại.",
            "Nếu cần xử lý trường hợp cụ thể, khách nên liên hệ trực tiếp hotline của cửa hàng.",
        ],
        "thanh toan": [
            "Thanh toán tại cửa hàng có hỗ trợ thẻ Visa/Master và thẻ ATM nội địa.",
            "Cửa hàng giao nội thành Hà Nội với đơn hàng trên 200.000VND, phí vận chuyển từ 20.000VND đến 50.000VND.",
            "Giá trên website chưa bao gồm 10% VAT.",
        ],
        "ban hang": [
            "Giờ làm việc các ngày trong tuần là 7:00-19:00.",
            "Đơn hàng nên đặt trước 1 ngày; mốc 15:00 mỗi ngày giúp giao đủ và chính xác hơn.",
            "Đơn cho thứ bảy, chủ nhật và thứ hai cần đặt trước 03:00 ngày thứ Sáu.",
            "Cửa hàng có chính sách ưu đãi theo số lượng và giá trị đơn hàng.",
        ],
        "bao mat": [
            "Nguyễn Sơn Bakery cho biết họ tôn trọng và bảo vệ thông tin cá nhân của khách hàng.",
            "Thông tin được dùng để xử lý yêu cầu, đơn hàng và hỗ trợ dịch vụ khi cần.",
            "Doanh nghiệp nêu rõ không mua bán thông tin cá nhân cho mục đích khuyến mãi.",
            "Website có thể dùng cookie và nhắc tới SSL khi hỗ trợ giao dịch trực tuyến.",
        ],
        "chat luong": [
            "Doanh nghiệp cam kết sản xuất thực phẩm an toàn, chất lượng cao và tuân thủ yêu cầu pháp lý liên quan.",
            "Hệ thống quản lý chất lượng được duy trì theo ISO 22000:2018.",
            "Chính sách nêu việc áp dụng HACCP, kiểm soát chất gây dị ứng và theo dõi nguồn gốc sản phẩm.",
            "Cửa hàng cũng nhấn mạnh quản lý nhà cung cấp và cải tiến liên tục để nâng cao chất lượng.",
        ],
    }

    for title_key, curated_highlights in curated_highlights_map.items():
        if title_key in normalized_title:
            return curated_highlights

    manual_patterns_map = {
        "doi tra": [
            r"Khách hàng xem kỹ sản phẩm trước khi mua, sản phẩm đã bán ra không nhập lại\.",
            r"Không có trường hợp ngoại lệ\.",
        ],
        "thanh toan": [
            r"Chấp nhận tt qua thẻ Visa/Master và thẻ ATM các ngân hàng nội địa",
            r"Nguyễn Sơn Bakery giao hàng ở nội thành Hà Nội với đơn hàng trị giá trên 200\.000VND và áp dụng phí vận chuyển từ 20\.000VND - 50\.000VND\s*\.",
            r"Nguyễn Sơn Bakery sử dụng đội ngũ Vận chuyển chuyên nghiệp để đảm bảo quyền lợi của khách hàng\.",
            r"Giá trên website chưa bao gồm 10% VAT",
        ],
        "ban hang": [
            r"Giờ làm việc Các ngày trong tuần: 7:00-19:00",
            r"Đặt hàng trước 1 ngày, tính từ thời điểm đặt hàng đến thời điểm nhận hàng\.",
            r"Thời gian đặt hàng: 15:00 hàng ngày để đảm bảo việc giao hàng đầy đủ và chính xác",
            r"Đặt hàng cho thứ bảy, chủ nhật và thứ hai phải được đặt trước 03:00 ngày thứ Sáu",
            r"Bạn sẽ được hưởng ưu đãi theo số lượng và giá trị của đơn hàng\.",
            r"Khách hàng xem kỹ sản phẩm trước khi mua, sản phẩm đã bán ra không nhập lại\.",
        ],
        "bao mat": [
            r"Nguyễn Sơn Bakery luôn tôn trọng sự riêng tư của bạn[^.]*\.",
            r"chúng tôi sẽ không cung cấp thông tin này cho một bên thứ ba[^.]*\.",
            r"Nguyễn Sơn Bakery cam kết bảo vệ sự riêng tư của bạn, không mua bán thông tin cá nhân của bạn cho các công ty khác vì các mục đích khuyến mãi\.",
            r"tiêu chuẩn công nghệ được gọi là SSL \(Secure Sockets Layer\)",
        ],
        "chat luong": [
            r"cam kết sản xuất các sản phẩm thực phẩm an toàn và chất lượng cao, đáp ứng hoặc vượt qua mong đợi của khách hàng và tuân thủ tất cả các yêu cầu pháp lý và quy định liên quan\.",
            r"duy trì tính hiệu lực và cập nhật liên tục của hệ thống Quản lý chất lượng theo tiêu chuẩn ISO 22000:2018",
            r"Chính sách HACCP[^.]*\.",
            r"theo dõi nguồn gốc sản phẩm[^.]*\.",
        ],
    }

    manual_patterns: list[str] = []
    for title_key, patterns in manual_patterns_map.items():
        if title_key in normalized_title:
            manual_patterns = patterns
            break

    if manual_patterns:
        manual_matches = find_pattern_matches(f"{cleaned_content} {combined_context}", manual_patterns)
        if manual_matches:
            return manual_matches[:4]

    title_keyword_map = {
        "doi tra": ["doi tra", "khong nhap lai", "khach hang xem ky", "san pham da ban"],
        "thanh toan": ["giao hang", "thanh toan", "noi thanh ha noi", "200 000", "20 000", "50 000", "vat"],
        "ban hang": ["dat hang", "15 00", "thu sau", "03 00", "giao hang", "chiet khau"],
        "bao mat": ["bao mat", "thong tin ca nhan", "email", "cookies"],
        "chat luong": ["an toan", "iso", "haccp", "nguon goc", "chat luong"],
    }

    selected_keywords: list[str] = []
    for title_key, keywords in title_keyword_map.items():
        if title_key in normalized_title:
            selected_keywords = keywords
            break

    sentences = split_sentences(cleaned_content)
    scored: list[tuple[int, int, str]] = []

    for index, sentence in enumerate(sentences):
        normalized_sentence = normalize_match(sentence)
        score = sum(1 for keyword in selected_keywords if keyword in normalized_sentence)
        if title_keyword_map and score == 0:
            continue
        scored.append((score, -index, sentence))

    if not scored:
        return sentences[:4]

    highlights: list[str] = []
    seen: set[str] = set()
    for _, _, sentence in sorted(scored, reverse=True):
        sentence_key = normalize_match(sentence)
        if sentence_key in seen:
            continue
        seen.add(sentence_key)
        highlights.append(sentence)
        if len(highlights) == 4:
            break

    return highlights


def build_policy_summary(highlights: list[str], fallback_title: str) -> str:
    if highlights:
        return " ".join(highlights[:2])
    return f"Thông tin nổi bật từ trang {fallback_title}."


def dedupe_categories(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    categories: list[dict[str, str]] = []
    for row in rows:
        name = normalize_space(row.get("category_name"))
        url = normalize_space(row.get("category_url"))
        if not name or name.startswith("- "):
            continue
        key = (name, url)
        if key in seen:
            continue
        seen.add(key)
        categories.append({"name": name, "url": url})
    return categories


def extract_contact_details(policy_rows: list[dict[str, str]]) -> dict[str, str]:
    combined = " ".join(normalize_space(row.get("content")) for row in policy_rows)

    phone_match = re.search(r"\b0\d{9,10}\b", combined)
    email_match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", combined)
    address_match = re.search(r"(Số\s+\d+[^.]*Hà Nội)", combined)

    return {
        "phone": phone_match.group(0) if phone_match else "02438222228",
        "email": email_match.group(0) if email_match else "info@nguyenson.vn",
        "address": normalize_space(address_match.group(1)) if address_match else "Số 15, hẻm 76 ngách 51, ngõ Linh Quang, Hà Nội",
        "brand": "Nguyễn Sơn Bakery",
    }


def build_site_data() -> dict[str, object]:
    product_rows = read_csv_rows(PRODUCTS_CSV)
    image_rows = read_csv_rows(IMAGES_CSV)
    policy_rows = read_csv_rows(POLICIES_CSV)
    category_rows = read_csv_rows(CATEGORIES_CSV)

    image_lookup = build_image_lookup(image_rows)
    official_categories = dedupe_categories(category_rows)
    contacts = extract_contact_details(policy_rows)
    combined_policy_context = " ".join(normalize_space(row.get("content")) for row in policy_rows)

    products: list[dict[str, object]] = []
    group_counter: Counter[str] = Counter()

    for index, row in enumerate(product_rows, start=1):
        name = normalize_space(row.get("name")) or f"Sản phẩm #{index}"
        product_url = normalize_space(row.get("product_url"))
        price_value = parse_price_number(row.get("price_default"), row.get("price_default_text"))
        price_status = normalize_space(row.get("price_status")) or ("available" if price_value else "contact_required")
        price_label = format_price_label(price_value, price_status, row.get("price_default_text"))
        variants = parse_variants(row.get("variants_json"))
        group = infer_product_group(name, product_url)
        images = choose_product_images(name, product_url, image_lookup.get(product_url, []))
        slug = slugify(product_url.rstrip("/").split("/")[-1] or name)

        product = {
            "id": normalize_space(row.get("sku")) or slug or f"product-{index}",
            "name": name,
            "slug": slug,
            "sku": normalize_space(row.get("sku")),
            "group": group,
            "priceValue": price_value,
            "priceLabel": price_label,
            "priceStatus": price_status,
            "variants": variants,
            "description": normalize_space(row.get("description")),
            "image": images[0] if images else "",
            "images": images,
            "imageCount": int(row.get("image_count") or 0),
            "productUrl": product_url,
            "sourceSite": normalize_space(row.get("source_site")),
            "lastChecked": normalize_space(row.get("last_checked")),
            "keywords": extract_tokens(
                name,
                group,
                " ".join(variant["name"] for variant in variants if isinstance(variant.get("name"), str)),
                slug,
            ),
        }
        product["searchText"] = normalize_match(
            " ".join(
                [
                    product["name"],
                    product["group"],
                    product["sku"],
                    product["description"],
                    " ".join(product["keywords"]),
                ]
            )
        )

        products.append(product)
        group_counter[group] += 1

    policies: list[dict[str, object]] = []
    for row in policy_rows:
        title = normalize_space(row.get("page_title"))
        url = normalize_space(row.get("page_url"))
        content = normalize_space(row.get("content"))
        highlights = extract_policy_highlights(title, content, combined_policy_context)
        policies.append(
            {
                "title": title,
                "url": url,
                "summary": build_policy_summary(highlights, title),
                "highlights": highlights,
                "searchText": normalize_match(" ".join([title, *highlights])),
            }
        )

    products.sort(
        key=lambda item: (
            item["priceValue"] is None,
            item["priceValue"] if item["priceValue"] is not None else 10**12,
            item["name"],
        )
    )

    price_values = [product["priceValue"] for product in products if isinstance(product["priceValue"], int)]
    cheapest = products[:6]
    best_priced = sorted(
        [product for product in products if isinstance(product["priceValue"], int)],
        key=lambda item: item["priceValue"],
    )[:6]

    latest_checked = max(
        (normalize_space(row.get("last_checked")) for row in product_rows if normalize_space(row.get("last_checked"))),
        default="",
    )

    data = {
        "brand": "Nguyễn Sơn Bakery",
        "tagline": "Chatbot F&B cho cửa hàng bánh, dựng từ dữ liệu sản phẩm và chính sách đã crawl.",
        "updatedAt": latest_checked,
        "contacts": contacts,
        "stats": {
            "totalProducts": len(products),
            "pricedProducts": sum(1 for product in products if isinstance(product["priceValue"], int)),
            "contactProducts": sum(1 for product in products if product["priceStatus"] == "contact_required"),
            "groupCount": len(group_counter),
            "priceMin": min(price_values) if price_values else None,
            "priceMax": max(price_values) if price_values else None,
        },
        "groupCounts": dict(sorted(group_counter.items(), key=lambda item: item[0])),
        "officialCategories": official_categories,
        "featured": {
            "cheapest": cheapest,
            "bestPriced": best_priced,
        },
        "policies": policies,
        "products": products,
        "prompts": [
            "Có bánh nào dưới 50k không?",
            "Các món được yêu thích",
            "Ở đây có những loại croissant nào?",
            "Mình chuyển khoản được không?",
            "Cho mình xem vài loại cookies nhé",
        ],
        "notes": [
            "Nhóm sản phẩm trên site là phân loại gợi ý vì file nguồn hiện chưa có mapping chính thức giữa từng sản phẩm và danh mục.",
            "Giá và chính sách lấy từ bộ dữ liệu trong thư mục ChatbotF&B.",
        ],
    }
    return data


def write_output_files(site_data: dict[str, object]) -> None:
    DATA_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    json_payload = json.dumps(site_data, ensure_ascii=False, indent=2)
    OUTPUT_JSON.write_text(json_payload, encoding="utf-8")
    OUTPUT_JS.write_text(f"window.__STORE_DATA__ = {json_payload};\n", encoding="utf-8")


def main() -> None:
    site_data = build_site_data()
    write_output_files(site_data)
    print(f"Built {OUTPUT_JS}")
    print(f"Built {OUTPUT_JSON}")


if __name__ == "__main__":
    main()

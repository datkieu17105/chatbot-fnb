import csv
import json
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
RAW_DATA_DIR = BACKEND_DIR / "data" / "raw" / "nguyenson"
PRODUCTS_CSV = RAW_DATA_DIR / "products.csv"
PRODUCTS_JSONL = RAW_DATA_DIR / "products.jsonl"


def safe_load_variants(text):
    if not text:
        return []
    try:
        return json.loads(text)
    except Exception:
        return []


def should_convert_to_contact(row):
    price_text = (row.get("price_default_text") or "").strip().lower()
    price_val = str(row.get("price_default") or "").strip()

    if price_text in {"", "0₫", "0đ", "0"}:
        return True
    if price_val == "0":
        return True
    return False


def clean_variants(variants):
    cleaned = []

    for v in variants:
        v_price = str(v.get("variant_price", "")).strip()
        v_price_text = str(v.get("variant_price_text", "")).strip().lower()

        if v_price == "0" or v_price_text in {"0₫", "0đ", "0", ""}:
            v["variant_price"] = None
            v["variant_price_text"] = "Liên hệ"

        cleaned.append(v)

    return cleaned


def rebuild_raw_text(row, variants):
    parts = []

    if row.get("name"):
        parts.append(f"Tên sản phẩm: {row['name']}")
    if row.get("category"):
        parts.append(f"Danh mục: {row['category']}")
    if row.get("sku"):
        parts.append(f"SKU: {row['sku']}")

    if row.get("price_status") == "contact_required":
        parts.append("Giá: Liên hệ")
    elif row.get("price_default_text"):
        parts.append(f"Giá mặc định: {row['price_default_text']}")
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

    if row.get("description"):
        parts.append(f"Mô tả: {row['description']}")
    if row.get("image_count"):
        parts.append(f"Số lượng ảnh: {row['image_count']}")
    if row.get("product_url"):
        parts.append(f"Nguồn: {row['product_url']}")

    return " | ".join(parts)


def main():
    with open(PRODUCTS_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    cleaned_rows = []

    for row in rows:
        variants = safe_load_variants(row.get("variants_json", ""))

        if should_convert_to_contact(row):
            row["price_default"] = ""
            row["price_default_text"] = "Liên hệ"
            row["price_status"] = "contact_required"
        else:
            row["price_status"] = "available"

        variants = clean_variants(variants)
        row["variants_json"] = json.dumps(variants, ensure_ascii=False)
        row["raw_text"] = rebuild_raw_text(row, variants)

        cleaned_rows.append(row)

    fieldnames = list(cleaned_rows[0].keys())
    if "price_status" not in fieldnames:
        fieldnames.append("price_status")

    # Ghi đè trực tiếp products.csv
    with open(PRODUCTS_CSV, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(cleaned_rows)

    # Ghi đè trực tiếp products.jsonl
    with open(PRODUCTS_JSONL, "w", encoding="utf-8") as f:
        for row in cleaned_rows:
            doc = {
                "id": row.get("sku") or row.get("product_url"),
                "text": row.get("raw_text", ""),
                "metadata": {
                    "name": row.get("name", ""),
                    "sku": row.get("sku", ""),
                    "category": row.get("category", ""),
                    "price_default_text": row.get("price_default_text", ""),
                    "price_status": row.get("price_status", ""),
                    "product_url": row.get("product_url", ""),
                    "source_site": row.get("source_site", ""),
                    "last_checked": row.get("last_checked", "")
                }
            }
            f.write(json.dumps(doc, ensure_ascii=False) + "\n")

    print("Đã ghi đè trực tiếp:")
    print("-", PRODUCTS_CSV)
    print("-", PRODUCTS_JSONL)


if __name__ == "__main__":
    main()

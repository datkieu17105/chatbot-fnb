from __future__ import annotations

import json
import importlib.util
import os
import re
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parents[2]
STORE_DATA_PATH = BACKEND_DIR / "data" / "processed" / "store-data.json"
ENV_PATH = BACKEND_DIR / ".env"
SYSTEM_PROMPT_PATH = BACKEND_DIR / "app" / "prompts" / "bakery_system_prompt.txt"

DEFAULT_MODEL = "gemini-2.5-flash"
DEFAULT_SCOPE_MODE = "strict_bakery"
VALID_SCOPE_MODES = {"strict_bakery", "hybrid_general"}
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

CHAT_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "string",
            "description": "Vietnamese answer for the customer. Use [S1], [S2] citations inline when grounded sources exist.",
        },
        "scope": {
            "type": "string",
            "description": "One of grounded, partial, out_of_scope, general.",
        },
        "source_ids": {
            "type": "array",
            "items": {
                "type": "string",
            },
        },
    },
    "required": ["answer", "scope", "source_ids"],
}


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize_text(text: str | None) -> str:
    base = (text or "").strip().lower().replace("đ", "d")
    normalized = unicodedata.normalize("NFD", base)
    stripped = "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", stripped).strip()


def unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        cleaned = value.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        output.append(cleaned)
    return output


def load_store_data(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_system_prompt() -> str:
    if SYSTEM_PROMPT_PATH.exists():
        return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()

    return "\n".join(
        [
            "Bạn là trợ lý tư vấn cho Nguyễn Sơn Bakery.",
            "Mục tiêu chính là hỗ trợ khách chọn sản phẩm, giải thích chính sách và trả lời ngắn gọn, rõ ràng.",
            "Ưu tiên dùng dữ liệu được truy xuất từ kho sản phẩm và chính sách của cửa hàng.",
            "Khi có nguồn, hãy trích dẫn bằng mã như [S1], [S2].",
            "Không bịa thông tin về giá, tồn kho, thành phần, khuyến mãi hoặc thời gian giao nếu nguồn không có.",
        ]
    )


def parse_price_token(number_text: str, unit_text: str = "") -> int | None:
    try:
        numeric = float(number_text.replace(",", "."))
    except ValueError:
        return None

    unit = unit_text.lower()
    if unit in {"trieu", "tr"}:
        return int(round(numeric * 1_000_000))
    if unit in {"k", "nghin", "ngan"}:
        return int(round(numeric * 1_000))
    return int(round(numeric))


def extract_price_range(query: str) -> dict[str, int] | None:
    query_norm = normalize_text(query)
    has_price_context = bool(
        re.search(r"\b(gia|duoi|tren|tu|den|khoang|tam|budget|ngan sach|re|dat|toi da|toi thieu)\b", query_norm)
    )
    if not has_price_context:
        return None

    amounts = [
        parse_price_token(match.group(1), match.group(2) or "")
        for match in re.finditer(r"(\d+(?:[.,]\d+)?)\s*(trieu|tr|k|nghin|ngan)?", query_norm)
    ]
    amounts = [value for value in amounts if value is not None]
    if not amounts:
        return None

    if re.search(r"\b(duoi|nho hon|toi da|max)\b", query_norm):
        return {"max": amounts[0]}
    if re.search(r"\b(tren|lon hon|toi thieu|min)\b", query_norm) and not re.search(r"\btu\b.*\bden\b", query_norm):
        return {"min": amounts[0]}
    if re.search(r"\btu\b.*\bden\b", query_norm) or len(amounts) >= 2:
        return {"min": min(amounts[0], amounts[1]), "max": max(amounts[0], amounts[1])}
    if re.search(r"\b(tam|khoang|around)\b", query_norm):
        return {"min": int(amounts[0] * 0.8), "max": int(amounts[0] * 1.2)}
    return None


def guess_query_tokens(query: str) -> list[str]:
    query_norm = normalize_text(query)
    expanded = [query_norm]
    birthday_query = "banh sinh nhat" in query_norm or "birthday cake" in query_norm

    if birthday_query:
        expanded.append("cake mousse charlotte tiramisu velvet forest fruit cheese")
    if "banh quy" in query_norm:
        expanded.append("cookie cookies tuile biscotte rocher")
    if "banh my" in query_norm or "banh mi" in query_norm:
        expanded.append("croissant baguette sandwich brioche pain pate chaud")

    stop_words = {
        "toi",
        "cho",
        "minh",
        "voi",
        "mot",
        "vay",
        "la",
        "co",
        "khong",
        "cua",
        "nay",
        "kia",
        "va",
        "nhung",
        "giup",
        "hoi",
        "gia",
        "san",
        "pham",
        "banh",
        "nao",
        "shop",
        "cac",
        "mon",
        "loai",
        "duoc",
        "yeu",
        "thich",
        "noi",
        "bat",
    }
    if birthday_query:
        stop_words.update({"sinh", "nhat"})
    tokens = [token for token in " ".join(expanded).split() if token and token not in stop_words]
    return unique_preserve_order(tokens)


class BakeryChatbot:
    group_aliases = {
        "Bánh mỳ": ["banh my", "banh mi", "croissant", "baguette", "sandwich", "brioche", "pain", "pate chaud"],
        "Bánh ngọt": ["banh sinh nhat", "cake", "gato", "gateaux", "mousse", "su kem", "donut", "charlotte", "bong lan"],
        "Bánh truyền thống": ["banh bao", "truyen thong", "banh khao", "banh cha", "quay"],
        "Cookies & snack": ["cookie", "cookies", "banh quy", "tuile", "biscotte", "rocher"],
        "Chocolate": ["chocolate", "socola"],
        "Đồ đông lạnh": ["dong lanh", "frozen"],
        "Phụ kiện": ["phu kien", "bo do an", "nen"],
    }

    domain_keywords = {
        "banh",
        "bakery",
        "cookie",
        "chocolate",
        "yeu thich",
        "noi bat",
        "ban chay",
        "mua nhieu",
        "giao hang",
        "thanh toan",
        "doi tra",
        "ban hang",
        "bao mat",
        "attp",
        "gia",
        "mua",
        "dat hang",
        "dat banh",
        "order",
        "tu van",
        "phu kien",
        "sinh nhat",
        "croissant",
        "baguette",
        "sandwich",
        "anh san pham",
        "hinh san pham",
    }

    policy_keywords = {
        "giao hang",
        "ship",
        "van chuyen",
        "thanh toan",
        "chuyen khoan",
        "qr",
        "ma qr",
        "quet ma",
        "doi tra",
        "bao mat",
        "attp",
        "an toan",
        "ban hang",
        "dat truoc",
        "nhan dat truoc",
        "dat hang",
        "dat banh",
        "order",
        "chinh sach",
        "vat",
        "hotline",
        "dia chi",
        "email",
        "lien he",
    }

    policy_title_aliases = {
        "Thanh toán & Giao hàng": ["giao hang", "ship", "van chuyen", "thanh toan", "chuyen khoan", "qr", "ma qr", "quet ma", "vat"],
        "Chính sách đổi trả": ["doi tra", "hoan tien", "tra hang"],
        "Bán hàng": ["ban hang", "dat hang", "dat banh", "order", "gio lam viec", "chiet khau"],
        "Chính sách bảo mật": ["bao mat", "thong tin ca nhan", "cookie", "email"],
        "Chính sách chất lượng ATTP": ["attp", "an toan", "iso", "haccp", "chat luong"],
    }

    @classmethod
    def from_default_store(cls) -> "BakeryChatbot":
        load_env_file(ENV_PATH)
        return cls(load_store_data(STORE_DATA_PATH))

    def __init__(self, store_data: dict[str, Any]) -> None:
        self.store_data = store_data
        self.products = store_data.get("products", [])
        self.policies = store_data.get("policies", [])
        self.contacts = store_data.get("contacts", {})
        self.prompts = unique_preserve_order(
            (store_data.get("prompts") or [])
            + [
                "Cho mình xem ảnh bánh croissant",
                "Mình cần bánh sinh nhật khoảng 300k",
                "Shop giao hàng như thế nào?",
            ]
        )
        self.api_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
        self.timeout_seconds = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "45"))
        self.scope_mode = (os.getenv("CHATBOT_SCOPE_MODE", DEFAULT_SCOPE_MODE).strip() or DEFAULT_SCOPE_MODE)
        if self.scope_mode not in VALID_SCOPE_MODES:
            self.scope_mode = DEFAULT_SCOPE_MODE
        self.system_prompt = load_system_prompt()

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "brand": self.store_data.get("brand", "Bakery Chatbot"),
            "apiConfigured": bool(self.api_key),
            "model": self.model,
            "chatMode": "gemini-grounded" if self.api_key else "local-grounded",
            "workflow": "langgraph" if importlib.util.find_spec("langgraph") else "local-graph",
            "scopeMode": self.scope_mode,
            "prompts": self.prompts[:6],
            "storeInfo": self._store_info(),
            "welcomeMessage": self._welcome_message(),
            "sourceStats": {
                "products": len(self.products),
                "policies": len(self.policies),
            },
        }

    def _extract_opening_hours(self) -> str:
        for policy in self.policies:
            title = policy.get("title", "")
            text_blob = " ".join(
                [
                    title,
                    policy.get("summary", ""),
                    " ".join(policy.get("highlights", [])),
                ]
            )
            match = re.search(r"\b\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}\b", text_blob)
            if match:
                return match.group(0).replace(" ", "")
        return "7:00-19:00"

    def _store_info(self) -> dict[str, str]:
        return {
            "brand": self.store_data.get("brand", "Nguyễn Sơn Bakery"),
            "phone": self.contacts.get("phone", ""),
            "email": self.contacts.get("email", ""),
            "address": self.contacts.get("address", ""),
            "openingHours": self._extract_opening_hours(),
        }

    def _welcome_message(self) -> str:
        return (
            f"Xin chào, mình là trợ lý tư vấn của {self._store_info()['brand']}. "
            "Mình có thể giúp gì cho bạn?"
        )

    def _is_policy_query(self, query_norm: str) -> bool:
        return any(keyword in query_norm for keyword in self.policy_keywords)

    def _is_contact_query(self, query_norm: str) -> bool:
        if any(keyword in query_norm for keyword in ("lien he", "hotline", "so dien thoai", "email", "dia chi", "o dau")):
            return True
        return bool(re.search(r"\bcua hang\b.*\bo dau\b", query_norm))

    def _is_greeting(self, query_norm: str) -> bool:
        return bool(re.search(r"\b(xin chao|hello|hi|chao ban|chao shop)\b", query_norm))

    def _is_store_availability_query(self, query_norm: str) -> bool:
        if not query_norm:
            return False
        if bool(re.search(r"\b(cua hang|ben minh|shop)\b.*\bco\b", query_norm)):
            return True
        return bool(re.search(r"\bco\b.*\bkhong\b", query_norm))

    def _is_popular_products_query(self, query_norm: str) -> bool:
        if not query_norm:
            return False

        strong_markers = (
            "duoc yeu thich",
            "yeu thich",
            "noi bat",
            "ban chay",
            "mua nhieu",
            "pho bien",
        )
        if any(marker in query_norm for marker in strong_markers):
            return True

        if "goi y" in query_norm and any(
            term in query_norm
            for term in ("banh", "mon", "san pham", "cookie", "cookies", "croissant", "cake", "banh my", "banh mi")
        ):
            return True
        return False

    def _assistant_already_greeted(self, history: list[dict[str, str]] | None = None) -> bool:
        for turn in (history or [])[-6:]:
            if turn.get("role") != "assistant":
                continue
            content_norm = normalize_text(turn.get("content", ""))
            if "xin chao" in content_norm or "tro ly tu van" in content_norm:
                return True
        return False

    def _wants_images(self, query_norm: str) -> bool:
        return bool(re.search(r"\b(anh|hinh|photo|picture|image)\b", query_norm)) or "cho xem" in query_norm

    def _is_generic_followup_query(self, query_norm: str) -> bool:
        if not query_norm:
            return False
        if self._is_greeting(query_norm) or self._is_contact_query(query_norm) or self._is_policy_query(query_norm):
            return False
        if self._is_store_availability_query(query_norm):
            return False
        if self._is_popular_products_query(query_norm):
            return False
        if extract_price_range(query_norm) or self._is_birthday_cake_query(query_norm):
            return False
        if self._infer_requested_group(query_norm):
            return False

        tokens = query_norm.split()
        if any(token in {"co", "khong", "nao", "duoc"} for token in tokens):
            return False
        if self._wants_images(query_norm) and len(tokens) <= 10:
            return True
        return len(tokens) <= 6

    def _last_relevant_user_query(self, history: list[dict[str, str]] | None, current_query_norm: str) -> str:
        seen_current = False
        for turn in reversed(history or []):
            if turn.get("role") != "user":
                continue
            content = (turn.get("content") or "").strip()
            if not content:
                continue
            content_norm = normalize_text(content)
            if not seen_current and content_norm == current_query_norm:
                seen_current = True
                continue
            if self._is_greeting(content_norm):
                continue
            if self._is_generic_followup_query(content_norm):
                continue
            return content
        return ""

    def _effective_query(self, query: str, history: list[dict[str, str]] | None = None) -> str:
        query_norm = normalize_text(query)
        if not self._is_generic_followup_query(query_norm):
            return query

        reference_query = self._last_relevant_user_query(history, query_norm)
        if not reference_query:
            return query
        return f"{query} {reference_query}"

    def _infer_requested_group(self, query_norm: str) -> str | None:
        if self._is_birthday_cake_query(query_norm):
            return None
        for group, aliases in self.group_aliases.items():
            if any(alias in query_norm for alias in aliases):
                return group
        return None

    def _is_birthday_cake_query(self, query_norm: str) -> bool:
        if "banh sinh nhat" in query_norm or "birthday cake" in query_norm:
            return True
        return "sinh nhat" in query_norm and any(
            term in query_norm for term in ("banh", "cake", "gateaux", "gato", "mousse", "charlotte")
        )

    def _explicit_product_focus_terms(self, query_norm: str) -> list[str]:
        candidates = [
            "croissant",
            "baguette",
            "sandwich",
            "brioche",
            "cookie",
            "cookies",
            "donut",
            "mousse",
            "tiramisu",
            "charlotte",
            "rainbow",
            "sakura",
            "black forest",
            "cheese cake",
            "cheesecake",
            "red velvet",
            "trung muoi",
            "socola",
            "chocolate",
        ]
        return [term for term in candidates if term in query_norm]

    def _birthday_candidate_score(self, product: dict[str, Any]) -> int:
        haystack = product.get("searchText", "")
        name_norm = normalize_text(product.get("name", ""))
        price_value = product.get("priceValue")
        group = product.get("group", "")

        score = 0
        if isinstance(price_value, int):
            if price_value >= 250_000:
                score += 40
            elif price_value >= 150_000:
                score += 24
            elif price_value <= 120_000:
                score -= 18

        if re.search(r"\b(16|18|20|22|24|26|28)\s*cm\b", haystack):
            score += 18

        whole_cake_markers = (
            "mousse",
            "charlotte",
            "forest cake",
            "velvet",
            "tiramisu",
            "fruit cake",
            "cheese cake",
            "rainbow cake",
            "sakura cake",
            "socola cake",
            "seasonal fruit cake",
            "mango fruit cake",
            "passion fruit chocolate cake",
        )
        if any(marker in haystack or marker in name_norm for marker in whole_cake_markers):
            score += 20

        if "mu sinh nhat" in haystack:
            score -= 50
        if group in {"Phụ kiện", "Cookies & snack", "Bánh mỳ", "Bánh truyền thống"}:
            score -= 35

        small_item_markers = ("piece", "cuon", "mini", "cookie", "tuile", "biscotte", "rocher")
        if any(marker in haystack or marker in name_norm for marker in small_item_markers):
            score -= 24
        if re.search(r"\b\d+\s*g\b", haystack):
            score -= 16
        if any(marker in haystack for marker in (" chiec", " hop", " default title")):
            score -= 12

        return score

    def _looks_in_scope(self, query_norm: str, best_score: int) -> bool:
        if self._is_greeting(query_norm) or self._is_contact_query(query_norm):
            return True
        if self._is_policy_query(query_norm) or self._is_store_availability_query(query_norm):
            return True
        if self._is_popular_products_query(query_norm):
            return True
        if best_score >= 18:
            return True
        return any(keyword in query_norm for keyword in self.domain_keywords)

    def _showcase_product_score(self, product: dict[str, Any], requested_group: str | None = None) -> int:
        group = product.get("group", "")
        haystack = product.get("searchText", "")
        name_norm = normalize_text(product.get("name", ""))
        price_value = product.get("priceValue")
        price_status = product.get("priceStatus")

        score = 0
        if requested_group:
            if group == requested_group:
                score += 30
            else:
                score -= 18

        if product.get("image"):
            score += 16
        if isinstance(price_value, int):
            score += 10
            if 15_000 <= price_value <= 120_000:
                score += 12
            elif price_value <= 220_000:
                score += 5
        else:
            score -= 10
        if price_status == "contact_required":
            score -= 18

        if group in {"Bánh mỳ", "Bánh ngọt", "Cookies & snack", "Chocolate"}:
            score += 10
        if group in {"Bánh truyền thống", "Phụ kiện", "Đồ đông lạnh", "Khác"}:
            score -= 22

        preferred_markers = (
            "croissant",
            "cookie",
            "cookies",
            "madeleine",
            "biscotte",
            "donut",
            "mousse",
            "tiramisu",
            "charlotte",
            "rainbow",
            "sakura",
            "black forest",
            "banana cheese",
            "cheese cake",
            "cheesecake",
            "trung muoi",
            "chocolate",
        )
        matched_markers = sum(1 for marker in preferred_markers if marker in haystack or marker in name_norm)
        score += matched_markers * 7

        if re.search(r"\b(default title|hop|chiec)\b", haystack):
            score -= 6

        return score

    def _curated_recommendation_hits(self, limit: int = 6, requested_group: str | None = None) -> list[dict[str, Any]]:
        scored_products: list[tuple[int, dict[str, Any]]] = []
        for product in self.products:
            score = self._showcase_product_score(product, requested_group=requested_group)
            if score > 0:
                scored_products.append((score, product))

        scored_products.sort(
            key=lambda item: (
                -item[0],
                item[1].get("priceValue") is None,
                item[1].get("priceValue") if item[1].get("priceValue") is not None else 10**12,
                item[1].get("name", ""),
            )
        )

        hits: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        preferred_groups = ["Bánh mỳ", "Bánh ngọt", "Cookies & snack", "Chocolate"]

        def append_product(score: int, product: dict[str, Any]) -> None:
            nonlocal hits
            name_key = normalize_text(product.get("name", ""))
            if not product.get("image") or name_key in seen_names:
                return

            seen_names.add(name_key)
            hits.append(
                {
                    "score": score,
                    "birthdayScore": 0,
                    "kind": "product",
                    "title": product.get("name", "Sản phẩm"),
                    "url": product.get("productUrl", ""),
                    "snippet": self._product_source_snippet(product),
                    "imageUrl": product.get("image", ""),
                    "images": product.get("images", []),
                    "raw": product,
                }
            )

        if requested_group:
            for score, product in scored_products:
                append_product(score, product)
                if len(hits) == limit:
                    break
            return hits

        for group in preferred_groups:
            for score, product in scored_products:
                if product.get("group") != group:
                    continue
                append_product(score, product)
                break
            if len(hits) == limit:
                return hits

        for group in preferred_groups:
            group_added = 0
            for score, product in scored_products:
                if product.get("group") != group:
                    continue
                if normalize_text(product.get("name", "")) in seen_names:
                    continue
                append_product(score, product)
                group_added += 1
                if group_added == 1 or len(hits) == limit:
                    break
            if len(hits) == limit:
                return hits

        for score, product in scored_products:
            append_product(score, product)
            if len(hits) == limit:
                break

        return hits

    def _product_source_snippet(self, product: dict[str, Any], include_group: bool = True) -> str:
        parts = [f"Giá: {product.get('priceLabel', 'Liên hệ')}"]
        if include_group:
            parts.insert(0, f"Nhóm: {product.get('group', 'Chưa rõ')}")
        if product.get("variants"):
            variant_bits = []
            for variant in product["variants"][:3]:
                variant_bits.append(f"{variant.get('name', 'Mặc định')}: {variant.get('priceLabel', 'Liên hệ')}")
            if variant_bits:
                parts.append("Biến thể: " + "; ".join(variant_bits))
        description = (product.get("description") or "").strip()
        if description:
            parts.append(f"Mô tả: {description}")
        return " | ".join(parts)

    def _policy_source_snippet(self, policy: dict[str, Any]) -> str:
        highlights = policy.get("highlights") or []
        if highlights:
            return " ".join(highlights[:2])
        return policy.get("summary", "")

    def _find_policy_source(self, sources: list[dict[str, Any]], *keywords: str) -> dict[str, Any] | None:
        normalized_keywords = [normalize_text(keyword) for keyword in keywords if keyword]
        for source in sources:
            if source.get("kind") != "policy":
                continue
            haystack = normalize_text(" ".join([source.get("title", ""), source.get("snippet", "")]))
            if any(keyword in haystack for keyword in normalized_keywords):
                return source
        return None

    def _build_policy_chat_answer(self, query_norm: str, sources: list[dict[str, Any]]) -> str | None:
        shipping = self._find_policy_source(sources, "giao hang", "thanh toan", "vat")
        returns = self._find_policy_source(sources, "doi tra", "tra hang", "hoan tien")
        sales = self._find_policy_source(sources, "ban hang", "gio lam viec", "dat truoc", "dat hang", "dat banh")
        privacy = self._find_policy_source(sources, "bao mat", "thong tin ca nhan", "cookie")
        quality = self._find_policy_source(sources, "attp", "an toan", "iso", "haccp")

        if any(term in query_norm for term in ("giao hang", "ship", "van chuyen", "thanh toan", "chuyen khoan", "qr", "ma qr", "quet ma", "vat", "hoa don", "the")) and shipping:
            cite = f" [{shipping['id']}]" if shipping.get("id") else ""
            parts: list[str] = []
            if any(term in query_norm for term in ("thanh toan", "the", "visa", "master", "atm")):
                parts.append(f"Bên mình hiện hỗ trợ thanh toán tại cửa hàng bằng thẻ Visa/Master và thẻ ATM nội địa{cite}.")
            if any(term in query_norm for term in ("chuyen khoan", "qr", "ma qr", "quet ma")):
                parts.append("Bên mình có hỗ trợ chuyển khoản qua app ngân hàng và quét mã QR nhé.")
            if any(term in query_norm for term in ("giao hang", "ship", "van chuyen")):
                parts.append(f"Với giao hàng nội thành Hà Nội, đơn trên 200.000đ có phí vận chuyển khoảng 20.000-50.000đ nhé{cite}.")
            if any(term in query_norm for term in ("vat", "hoa don", "thue")):
                parts.append(f"Giá trên website hiện chưa gồm 10% VAT{cite}.")
            return " ".join(parts) if parts else f"Mình có thông tin về giao hàng và thanh toán của cửa hàng rồi nhé{cite}."

        if any(term in query_norm for term in ("doi tra", "tra hang", "hoan tien")) and returns:
            cite = f" [{returns['id']}]" if returns.get("id") else ""
            return (
                "Bên mình nhờ bạn kiểm tra kỹ sản phẩm trước khi nhận giúp nhé. "
                f"Sản phẩm đã bán ra hiện chưa nhận lại; nếu có trường hợp cụ thể, bạn nên gọi hotline để cửa hàng hỗ trợ nhanh hơn{cite}."
            )

        if any(term in query_norm for term in ("gio mo cua", "gio lam viec", "mo cua", "dat truoc", "dat hang", "dat banh", "order", "thu bay", "chu nhat", "thu hai", "15:00")) and sales:
            cite = f" [{sales['id']}]" if sales.get("id") else ""
            parts: list[str] = []
            if any(term in query_norm for term in ("gio mo cua", "gio lam viec", "mo cua", "mấy giờ", "may gio", "gio")):
                parts.append(f"Cửa hàng mở từ 7:00 đến 19:00 mỗi ngày{cite}.")
            if any(term in query_norm for term in ("dat hang", "dat banh", "order")):
                parts.append(
                    "Bạn cho mình biết loại bánh, số lượng và thời gian nhận hoặc giao mong muốn nhé. "
                    "Nếu cần chốt đơn nhanh, bạn có thể liên hệ trực tiếp hotline cửa hàng."
                )
            if any(term in query_norm for term in ("dat truoc", "thu bay", "chu nhat", "thu hai", "15:00", "giao kip", "giao dung", "hom sau")):
                parts.append(
                    "Nếu bạn cần giao đủ và chính xác hơn thì nên đặt trước 1 ngày; "
                    f"riêng đơn cho thứ Bảy, Chủ nhật và thứ Hai thì nên chốt trước 03:00 thứ Sáu{cite}."
                )
            return " ".join(parts) if parts else f"Mình có thể hỗ trợ bạn phần giờ mở cửa và cách đặt đơn trước nhé{cite}."

        if any(term in query_norm for term in ("bao mat", "thong tin ca nhan", "cookie", "ssl")) and privacy:
            cite = f" [{privacy['id']}]" if privacy.get("id") else ""
            return (
                "Bên mình dùng thông tin của bạn chủ yếu để xử lý yêu cầu, đơn hàng và hỗ trợ dịch vụ khi cần. "
                f"Cửa hàng cũng nêu rõ là không mua bán thông tin cá nhân cho mục đích khuyến mãi{cite}."
            )

        if any(term in query_norm for term in ("attp", "an toan", "iso", "haccp", "chat luong", "nguon goc")) and quality:
            cite = f" [{quality['id']}]" if quality.get("id") else ""
            return (
                "Bên mình có cam kết về an toàn thực phẩm và đang duy trì hệ thống ISO 22000:2018. "
                f"Ngoài ra còn có kiểm soát HACCP và theo dõi nguồn gốc sản phẩm{cite}."
            )

        return None

    def _search_products(self, query: str, limit: int = 6) -> list[dict[str, Any]]:
        query_norm = normalize_text(query)
        requested_group = self._infer_requested_group(query_norm)
        birthday_query = self._is_birthday_cake_query(query_norm)
        popular_query = self._is_popular_products_query(query_norm)
        focus_terms = self._explicit_product_focus_terms(query_norm)
        tokens = guess_query_tokens(query)
        price_range = extract_price_range(query)
        wants_contact = any(term in query_norm for term in ("lien he", "bao gia", "contact"))
        wants_cheap = any(term in query_norm for term in ("re", "tiet kiem", "hop ly", "duoi"))

        results: list[dict[str, Any]] = []
        for product in self.products:
            score = 0
            haystack = product.get("searchText", "")
            name_norm = normalize_text(product.get("name", ""))
            birthday_score = 0

            if query_norm and query_norm in haystack:
                score += 80
            if name_norm and query_norm and name_norm in query_norm:
                score += 45
            if requested_group and product.get("group") == requested_group:
                score += 24
            if focus_terms:
                matched_focus_terms = sum(1 for term in focus_terms if term in haystack or term in name_norm)
                if matched_focus_terms:
                    score += matched_focus_terms * 14
                    if matched_focus_terms < len(focus_terms):
                        score -= (len(focus_terms) - matched_focus_terms) * 10
                else:
                    score -= len(focus_terms) * 18
            for token in tokens:
                if token in haystack:
                    score += 6

            price_value = product.get("priceValue")
            if wants_contact and product.get("priceStatus") == "contact_required":
                score += 16

            if price_range:
                if isinstance(price_value, int):
                    if "min" in price_range and price_value >= price_range["min"]:
                        score += 8
                    elif "min" in price_range:
                        score -= 10

                    if "max" in price_range and price_value <= price_range["max"]:
                        score += 10
                    elif "max" in price_range:
                        score -= 10
                else:
                    score -= 12

            if wants_cheap and isinstance(price_value, int):
                if price_value <= 50_000:
                    score += 8
                elif price_value <= 100_000:
                    score += 3

            if birthday_query:
                birthday_score = self._birthday_candidate_score(product)
                score += birthday_score

            if score > 0:
                results.append(
                    {
                        "score": score,
                        "birthdayScore": birthday_score,
                        "kind": "product",
                        "title": product.get("name", "Sản phẩm"),
                        "url": product.get("productUrl", ""),
                        "snippet": self._product_source_snippet(product, include_group=not birthday_query),
                        "imageUrl": product.get("image", ""),
                        "images": product.get("images", []),
                        "raw": product,
                    }
                )

        if birthday_query:
            strong_matches = [item for item in results if item.get("birthdayScore", 0) >= 20]
            if len(strong_matches) >= 3:
                results = strong_matches

        if popular_query:
            curated_hits = self._curated_recommendation_hits(limit=limit, requested_group=requested_group)
            if not results:
                return curated_hits[:limit]

            existing_titles = {normalize_text(item["title"]) for item in results}
            for item in curated_hits:
                title_key = normalize_text(item["title"])
                if title_key in existing_titles:
                    continue
                results.append(item)
                existing_titles.add(title_key)
                if len(results) >= limit:
                    break

        results.sort(key=lambda item: (-item["score"], item["title"]))
        return results[:limit]

    def _search_policies(self, query: str, limit: int = 4) -> list[dict[str, Any]]:
        query_norm = normalize_text(query)
        tokens = guess_query_tokens(query)
        results: list[dict[str, Any]] = []

        for policy in self.policies:
            score = 0
            title = policy.get("title", "")
            haystack = normalize_text(" ".join([title, policy.get("summary", ""), " ".join(policy.get("highlights", []))]))

            if query_norm and query_norm in haystack:
                score += 70
            for token in tokens:
                if token in haystack:
                    score += 7
            if self._is_policy_query(query_norm):
                title_norm = normalize_text(title)
                if any(token in title_norm for token in tokens):
                    score += 10
            for canonical_title, aliases in self.policy_title_aliases.items():
                if title == canonical_title and any(alias in query_norm for alias in aliases):
                    score += 30

            if score > 0:
                results.append(
                    {
                        "score": score,
                        "kind": "policy",
                        "title": title or "Chính sách",
                        "url": policy.get("url", ""),
                        "snippet": self._policy_source_snippet(policy),
                        "imageUrl": "",
                        "images": [],
                        "raw": policy,
                    }
                )

        results.sort(key=lambda item: (-item["score"], item["title"]))
        return results[:limit]

    def _build_context(self, query: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        effective_query = self._effective_query(query, history)
        query_norm = normalize_text(query)
        product_hits = self._search_products(effective_query)
        policy_hits = self._search_policies(effective_query)
        wants_images = self._wants_images(query_norm)
        product_best_score = max([item["score"] for item in product_hits], default=0)
        strong_product_intent = bool(
            self._infer_requested_group(query_norm)
            or self._explicit_product_focus_terms(query_norm)
            or self._is_birthday_cake_query(query_norm)
            or self._is_popular_products_query(query_norm)
            or wants_images
            or extract_price_range(query)
        )

        if product_best_score < 18 and not strong_product_intent:
            product_hits = []
            product_best_score = 0

        raw_sources: list[dict[str, Any]] = []
        if self._is_contact_query(query_norm):
            raw_sources.append(
                {
                    "kind": "contact",
                    "title": "Thông tin liên hệ cửa hàng",
                    "url": "",
                    "snippet": (
                        f"Hotline: {self.contacts.get('phone', '')} | "
                        f"Email: {self.contacts.get('email', '')} | "
                        f"Địa chỉ: {self.contacts.get('address', '')}"
                    ),
                    "imageUrl": "",
                    "images": [],
                    "score": 100,
                    "raw": self.contacts,
                }
            )

        raw_sources.extend(product_hits[:4])
        raw_sources.extend(policy_hits[:3])

        if not raw_sources and self._is_greeting(query_norm):
            raw_sources.append(
                {
                    "kind": "contact",
                    "title": "Phạm vi hỗ trợ",
                    "url": "",
                    "snippet": "Chatbot hỗ trợ tư vấn sản phẩm, giá, chính sách và thông tin liên hệ của Nguyễn Sơn Bakery.",
                    "imageUrl": "",
                    "images": [],
                    "score": 30,
                    "raw": {},
                }
            )

        sources: list[dict[str, Any]] = []
        for index, item in enumerate(raw_sources, start=1):
            sources.append(
                {
                    "id": f"S{index}",
                    "kind": item["kind"],
                    "title": item["title"],
                    "url": item["url"],
                    "snippet": item["snippet"],
                    "imageUrl": item.get("imageUrl", ""),
                    "images": item.get("images", []),
                    "score": item["score"],
                }
            )

        best_score = max([item["score"] for item in raw_sources], default=0)
        return {
            "effectiveQuery": effective_query,
            "queryNorm": query_norm,
            "inScope": self._looks_in_scope(query_norm, best_score),
            "bestScore": best_score,
            "productBestScore": product_best_score,
            "wantsImages": wants_images,
            "productHits": product_hits,
            "policyHits": policy_hits,
            "sources": sources,
        }

    def _build_local_answer(
        self,
        query: str,
        context: dict[str, Any],
        api_note: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        query_norm = context["queryNorm"]
        sources = context["sources"]

        def top_source_ids(kind: str | None = None, limit: int = 3) -> list[str]:
            selected = sources if kind is None else [source for source in sources if source["kind"] == kind]
            return [source["id"] for source in selected[:limit]]

        if self._is_greeting(query_norm):
            if self._assistant_already_greeted(history):
                return {
                    "answer": "Mình đây, bạn cứ nói nhu cầu về bánh, mức giá hoặc loại bạn đang tìm là mình gợi ý ngay.",
                    "scope": "grounded",
                    "source_ids": [],
                }
            return {
                "answer": (
                    "Chào bạn. Mình có thể tư vấn bánh theo nhu cầu, ngân sách, giải thích chính sách "
                    "và gửi ảnh sản phẩm nếu bạn muốn xem."
                ),
                "scope": "grounded",
                "source_ids": [],
            }

        if not context["inScope"]:
            return {
                "answer": (
                    "Mình xin phép chỉ hỗ trợ thông tin liên quan đến Nguyễn Sơn Bakery như sản phẩm, giá, đặt bánh, "
                    "giao hàng, thanh toán và liên hệ cửa hàng thôi nhé. Bạn cần mình tư vấn loại bánh nào không ạ?"
                ),
                "scope": "out_of_scope",
                "source_ids": [],
            }

        if self._is_contact_query(query_norm):
            return {
                "answer": (
                    f"Bạn có thể liên hệ cửa hàng qua hotline {self.contacts.get('phone', '')}, "
                    f"email {self.contacts.get('email', '')} hoặc đến {self.contacts.get('address', '')}."
                ),
                "scope": "grounded",
                "source_ids": top_source_ids(limit=1),
            }

        if self._is_policy_query(query_norm) and context["policyHits"]:
            policy_answer = self._build_policy_chat_answer(query_norm, sources)
            lines = [policy_answer] if policy_answer else []
            if not lines:
                lines.append(
                    "Mình có thông tin về giao hàng, đổi trả, giờ mở cửa, bảo mật và an toàn thực phẩm của cửa hàng. "
                    "Bạn hỏi cụ thể hơn một chút là mình trả lời sát ý ngay."
                )
            if api_note:
                lines.append(api_note)
            return {
                "answer": "\n".join(lines),
                "scope": "grounded",
                "source_ids": top_source_ids(kind="policy", limit=3),
            }

        if context["productHits"]:
            popular_query = self._is_popular_products_query(query_norm)
            intro = "Mình thấy vài lựa chọn khá hợp với nhu cầu của bạn:"
            if popular_query:
                intro = "Nếu bạn muốn tham khảo nhanh thì mình gợi ý vài món nổi bật, dễ chọn của cửa hàng nhé:"
            if context["wantsImages"]:
                intro = "Mình gửi bạn vài mẫu ngay trong khung chat nhé:"
                if popular_query:
                    intro = "Mình gửi bạn vài món nổi bật ngay trong khung chat nhé:"

            lines = [intro]
            product_sources = [source for source in sources if source["kind"] == "product"]
            has_display_cards = any(source.get("imageUrl") for source in product_sources[:3])

            if not context["wantsImages"] and not (popular_query and has_display_cards):
                for source in product_sources[:4]:
                    lines.append(f"- {source['title']}: {source['snippet']} [{source['id']}]")

            if api_note:
                lines.append(api_note)
            return {
                "answer": "\n".join(lines),
                "scope": "grounded",
                "source_ids": top_source_ids(kind="product", limit=6),
            }

        fallback = "Mình chưa tìm thấy dữ liệu đủ sát để trả lời chắc chắn. Bạn có thể nói rõ hơn về loại bánh, ngân sách hoặc nhu cầu."
        if api_note:
            fallback = f"{fallback} {api_note}"
        return {
            "answer": fallback,
            "scope": "partial",
            "source_ids": top_source_ids(limit=2),
        }

    def _build_grounded_prompt(self, query: str, history: list[dict[str, str]], context: dict[str, Any]) -> str:
        history_lines = []
        for turn in history[-6:]:
            role = "Khách" if turn.get("role") == "user" else "Trợ lý"
            content = (turn.get("content") or "").strip()
            if content:
                history_lines.append(f"{role}: {content}")

        source_lines = []
        for source in context["sources"]:
            source_lines.append(
                "\n".join(
                    [
                        f"[{source['id']}] kind={source['kind']}",
                        f"Title: {source['title']}",
                        f"Evidence: {source['snippet']}",
                        f"URL: {source['url'] or 'N/A'}",
                    ]
                )
            )

        return "\n\n".join(
            [
                self.system_prompt,
                "Quy tắc bổ sung:",
                "- Chỉ dùng thông tin trong phần Nguồn dữ liệu được cung cấp.",
                "- Trả lời bằng tiếng Việt, ngắn gọn, rõ ràng, thực dụng.",
                "- Trả lời như một nhân viên tư vấn đang nhắn tin với khách: xưng `mình`, gọi khách là `bạn`.",
                "- Chỉ chào một lần ở đầu đoạn hội thoại; nếu đã chào rồi thì đi thẳng vào hỗ trợ, không chào lại.",
                "- Không mở đầu bằng các cụm như `Theo dữ liệu`, `Theo chính sách`, `Theo nguồn`; hãy diễn đạt lại bằng lời tự nhiên.",
                "- Nếu dữ liệu không đủ, nói rõ là chưa thấy trong dữ liệu và gợi ý khách liên hệ cửa hàng.",
                "- Khi nêu thông tin cụ thể, thêm mã nguồn như [S1], [S2] ngay trong câu.",
                "- Không bịa tồn kho, thành phần, thời gian giao, chi nhánh hay khuyến mãi nếu nguồn không có.",
                "- Nếu khách hỏi xem ảnh, có thể nói ngắn gọn và để frontend hiển thị ảnh từ nguồn sản phẩm.",
                f"Chế độ phạm vi hiện tại: {self.scope_mode}.",
                "Hội thoại gần đây:",
                "\n".join(history_lines) or "Chưa có lịch sử trước đó.",
                "Nguồn dữ liệu:",
                "\n\n".join(source_lines) or "Không có nguồn dữ liệu phù hợp.",
                f"Câu hỏi hiện tại: {query}",
            ]
        )

    def _build_general_prompt(self, query: str, history: list[dict[str, str]]) -> str:
        history_lines = []
        for turn in history[-6:]:
            role = "Người dùng" if turn.get("role") == "user" else "Trợ lý"
            content = (turn.get("content") or "").strip()
            if content:
                history_lines.append(f"{role}: {content}")

        return "\n\n".join(
            [
                "Bạn là trợ lý AI trả lời tự nhiên bằng tiếng Việt.",
                "Nếu câu hỏi không liên quan đến cửa hàng bánh, bạn vẫn có thể trả lời như Gemini thông thường.",
                "Khi đây là trả lời general, không được bịa rằng bạn đang dùng dữ liệu nội bộ của cửa hàng.",
                "Trả lời ngắn gọn, hữu ích, không khoa trương.",
                "Hội thoại gần đây:",
                "\n".join(history_lines) or "Chưa có lịch sử trước đó.",
                f"Câu hỏi hiện tại: {query}",
            ]
        )

    def _parse_gemini_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidates = payload.get("candidates") or []
        if not candidates:
            raise ValueError("Gemini API returned no candidates.")

        parts = (((candidates[0] or {}).get("content") or {}).get("parts") or [])
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)).strip()
        if not text:
            raise ValueError("Gemini API returned an empty text response.")

        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("Gemini JSON output is not an object.")
        return parsed

    def _call_gemini_with_prompt(self, prompt: str) -> dict[str, Any]:
        request_body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.25,
                "maxOutputTokens": 700,
                "responseMimeType": "application/json",
                "responseJsonSchema": CHAT_RESPONSE_SCHEMA,
            },
        }

        request = urllib.request.Request(
            GEMINI_API_URL.format(model=self.model),
            data=json.dumps(request_body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ValueError(f"Gemini HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise ValueError(f"Gemini request failed: {exc.reason}") from exc

        return self._parse_gemini_response(payload)

    def _build_attachments(self, context: dict[str, Any], source_ids: list[str]) -> list[dict[str, str]]:
        source_lookup = {source["id"]: source for source in context["sources"]}
        attachments: list[dict[str, str]] = []
        for source_id in source_ids:
            source = source_lookup.get(source_id)
            if not source or source["kind"] != "product":
                continue

            image_url = source.get("imageUrl") or ""
            if not image_url:
                continue

            attachments.append(
                {
                    "type": "image",
                    "title": source["title"],
                    "imageUrl": image_url,
                    "linkUrl": source.get("url", ""),
                }
            )
        return attachments

    def _friendly_fallback_note(self, exc: Exception | None = None) -> str:
        return ""

    def _answer_denies_images(self, answer: str) -> bool:
        answer_norm = normalize_text(answer)
        denial_markers = (
            "chua co thong tin hinh anh",
            "chua co hinh anh",
            "khong co hinh anh",
            "chua thay hinh anh",
            "ghe tham website",
        )
        return any(marker in answer_norm for marker in denial_markers)

    def _strip_redundant_greeting(self, answer: str, query_norm: str, history: list[dict[str, str]] | None = None) -> str:
        if not answer:
            return answer
        if self._is_greeting(query_norm) and not self._assistant_already_greeted(history):
            return answer.strip()
        if not self._assistant_already_greeted(history):
            return answer.strip()

        cleaned = answer.strip()
        pattern = re.compile(
            r"^\s*(xin chào(?: bạn)?|chào bạn(?: nhé| nha| ạ)?|dạ chào bạn(?: nhé| nha| ạ)?)\s*[,.:!-]*\s*",
            re.IGNORECASE,
        )
        while True:
            updated = pattern.sub("", cleaned, count=1).strip()
            if updated == cleaned:
                break
            cleaned = updated

        if cleaned and cleaned[0].islower():
            cleaned = cleaned[0].upper() + cleaned[1:]
        return cleaned or answer.strip()

    def _finalize_response(
        self,
        raw: dict[str, Any],
        source_lookup: dict[str, dict[str, Any]],
        used_model: str,
        context: dict[str, Any],
        query: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        answer = (raw.get("answer") or "").strip() or "Mình chưa thể tạo câu trả lời phù hợp ở thời điểm này."
        answer = re.sub(r"\s*\[S\d+\]", "", answer).strip()
        scope = (raw.get("scope") or "grounded").strip().lower()
        if scope not in {"grounded", "partial", "out_of_scope", "general"}:
            scope = "grounded"

        raw_source_ids = raw.get("source_ids") or []
        source_ids = [source_id for source_id in raw_source_ids if source_id in source_lookup]
        if scope == "out_of_scope":
            source_ids = []
        elif not source_ids:
            source_ids = list(source_lookup.keys())[:3]
        elif scope in {"grounded", "partial"}:
            product_source_ids = [
                source_id
                for source_id, source in source_lookup.items()
                if source.get("kind") == "product" and source.get("imageUrl")
            ]
            for source_id in product_source_ids:
                if source_id not in source_ids:
                    source_ids.append(source_id)
                if len([item for item in source_ids if source_lookup[item].get("kind") == "product"]) >= 6:
                    break

        sources = [source_lookup[source_id] for source_id in source_ids]
        attachments = self._build_attachments(context, source_ids)
        query_norm = context.get("queryNorm") or normalize_text(query)
        answer = self._strip_redundant_greeting(answer, query_norm, history)

        if attachments and self._answer_denies_images(answer):
            answer = self._build_local_answer(query, context, history=history)["answer"]

        return {
            "answer": answer,
            "scope": scope,
            "sources": sources,
            "attachments": attachments,
            "usedModel": used_model,
        }

    def chat(self, query: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        from app.chatbot.graph import BakeryChatbotGraph

        return BakeryChatbotGraph(self).invoke(query, history or [])

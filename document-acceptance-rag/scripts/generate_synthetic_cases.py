"""
Generate ~500 synthetic Arabic real-estate cases for the historical dataset.

Strategy:
  - ~60% Accepted (MEETS_CRITERIA)
  - ~40% Rejected, distributed across all rejection reason_codes (>=30 each)
  - Deliberate attribute diversity: varied property types, cities, name styles,
    Arabic spelling variants, area ranges. Narrowness here = over-flagging in prod.

Output: data/historical_cases.csv  (ready to paste into Google Sheets)
"""
from __future__ import annotations

import csv
import os
import random
from datetime import date, timedelta

random.seed(42)

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "historical_cases.csv")

# ------------------------------------------------------------------
# Attribute pools — deliberately diverse
# ------------------------------------------------------------------

DOCUMENT_TYPES = ["صك ملكية", "عقد إيجار", "توكيل", "عقد بيع", "صك وراثة"]
PROPERTY_TYPES = ["شقة", "شقه", "فيلا", "أرض", "مكتب", "محل تجاري", "مستودع", "استراحة"]
CITIES = ["الرياض", "جدة", "مكة المكرمة", "المدينة المنورة", "الدمام", "الخبر", "أبها", "تبوك", "حائل", "نجران"]
STREET_NAMES = [
    "شارع الملك فهد", "شارع العليا", "شارع التحلية", "شارع الأمير سلطان",
    "شارع الستين", "شارع الأمير عبدالعزيز", "طريق الملك عبدالله", "شارع الوزير",
]
DISTRICTS = ["العزيزية", "الروضة", "الملقا", "النزهة", "الورود", "الصفا", "الحمراء", "البساتين"]

FIRST_NAMES = [
    "محمد", "أحمد", "عبدالله", "عبدالرحمن", "خالد", "عمر", "علي", "سعد", "فهد",
    "ناصر", "يوسف", "إبراهيم", "حمد", "سلطان", "تركي", "بندر", "ماجد", "وليد",
    "هند", "نورة", "سارة", "مريم", "فاطمة", "عائشة", "منيرة", "ريم", "أسماء",
]
LAST_NAMES = [
    "العتيبي", "القحطاني", "الشمري", "الغامدي", "الزهراني", "الحربي", "الدوسري",
    "السبيعي", "المطيري", "الرشيدي", "العنزي", "البقمي", "الأحمدي", "الشهري",
    # transliterated variants
    "Al-Otaibi", "Al-Qahtani", "Al-Shammari", "Al-Ghamdi",
]


def random_owner_name() -> str:
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def random_valid_owner_id() -> str:
    prefix = random.choice(["1", "2"])
    return prefix + "".join([str(random.randint(0, 9)) for _ in range(9)])


def random_invalid_owner_id() -> str:
    choices = [
        "ABC123",
        "123456",        # too short
        "0" + "".join([str(random.randint(0, 9)) for _ in range(9)]),  # wrong prefix
        "3" + "".join([str(random.randint(0, 9)) for _ in range(9)]),  # wrong prefix
        "",
        "12345678901",   # too long
    ]
    return random.choice(choices)


def random_address() -> str:
    return f"{random.choice(STREET_NAMES)}، {random.choice(DISTRICTS)}"


def random_date_within(years: int) -> date:
    days = random.randint(0, int(years * 365))
    return date.today() - timedelta(days=days)


def random_old_date(min_years: int = 11, max_years: int = 20) -> date:
    days = random.randint(int(min_years * 365), int(max_years * 365))
    return date.today() - timedelta(days=days)


def base_valid_case(case_id: str) -> dict:
    doc_type = random.choice(DOCUMENT_TYPES)
    return {
        "case_id": case_id,
        "document_type": doc_type,
        "owner_name": random_owner_name(),
        "owner_id": random_valid_owner_id(),
        "property_id": f"PROP-{random.randint(10000, 99999)}",
        "property_type": random.choice(PROPERTY_TYPES),
        "area_sqm": round(random.uniform(60, 2000), 1),
        "address": random_address(),
        "city": random.choice(CITIES),
        "notarized": True if doc_type == "صك ملكية" else random.choice([True, False]),
        "owner_signature": True,
        "liens_present": False,
        "registration_date": random_date_within(8).isoformat(),
        "decision": "Accepted",
        "reason_code": "MEETS_CRITERIA",
        "recommendation_en": "All required criteria met. Document accepted.",
        "recommendation_ar": "تم استيفاء جميع المعايير المطلوبة. تم قبول المستند.",
        "source": "validated",
        "added_at": date.today().isoformat(),
        "index_version": "seed_v1",
    }


HEADERS = [
    "case_id", "document_type", "owner_name", "owner_id", "property_id",
    "property_type", "area_sqm", "address", "city", "notarized",
    "owner_signature", "liens_present", "registration_date",
    "decision", "reason_code", "recommendation_en", "recommendation_ar",
    "source", "added_at", "index_version",
]

REJECTION_CONFIGS = {
    "MISSING_OWNER_NAME": lambda c: {**c, "owner_name": "", "decision": "Rejected", "reason_code": "MISSING_OWNER_NAME",
        "recommendation_en": "Owner name is missing.", "recommendation_ar": "اسم المالك مفقود."},
    "MISSING_PROPERTY_ID": lambda c: {**c, "property_id": "", "decision": "Rejected", "reason_code": "MISSING_PROPERTY_ID",
        "recommendation_en": "Property ID is missing.", "recommendation_ar": "رقم العقار مفقود."},
    "MISSING_OWNER_SIGNATURE": lambda c: {**c, "owner_signature": False, "decision": "Rejected", "reason_code": "MISSING_OWNER_SIGNATURE",
        "recommendation_en": "Owner signature is missing.", "recommendation_ar": "توقيع المالك مفقود."},
    "NOT_NOTARIZED": lambda c: {**c, "document_type": "صك ملكية", "notarized": False, "decision": "Rejected", "reason_code": "NOT_NOTARIZED",
        "recommendation_en": "Deed of ownership must be notarized.", "recommendation_ar": "يجب أن يكون صك الملكية موثقاً."},
    "LIEN_PRESENT": lambda c: {**c, "liens_present": True, "decision": "Rejected", "reason_code": "LIEN_PRESENT",
        "recommendation_en": "Liens or restrictions are present.", "recommendation_ar": "يوجد رهون أو قيود على العقار."},
    "INCOMPLETE_ADDRESS": lambda c: {**c, "address": "", "decision": "Rejected", "reason_code": "INCOMPLETE_ADDRESS",
        "recommendation_en": "Address is incomplete.", "recommendation_ar": "العنوان غير مكتمل."},
    "INVALID_AREA": lambda c: {**c, "area_sqm": 0, "decision": "Rejected", "reason_code": "INVALID_AREA",
        "recommendation_en": "Area is invalid or missing.", "recommendation_ar": "المساحة غير صالحة أو مفقودة."},
    "OWNER_ID_MISMATCH": lambda c: {**c, "owner_id": random_invalid_owner_id(), "decision": "Rejected", "reason_code": "OWNER_ID_MISMATCH",
        "recommendation_en": "Owner ID format is invalid.", "recommendation_ar": "صيغة رقم هوية المالك غير صحيحة."},
    "EXPIRED_REGISTRATION": lambda c: {**c, "registration_date": random_old_date().isoformat(), "decision": "Rejected", "reason_code": "EXPIRED_REGISTRATION",
        "recommendation_en": "Registration date is expired.", "recommendation_ar": "تاريخ التسجيل منتهي الصلاحية."},
}


def generate(n_total: int = 500) -> list[dict]:
    cases = []
    n_accepted = int(n_total * 0.6)
    n_rejected_per_code = max(30, (n_total - n_accepted) // len(REJECTION_CONFIGS))

    # Accepted cases
    for i in range(1, n_accepted + 1):
        cases.append(base_valid_case(f"HIST-{i:04d}"))

    # Rejected cases — at least n_rejected_per_code per reason_code
    idx = n_accepted + 1
    for reason_code, mutate in REJECTION_CONFIGS.items():
        for _ in range(n_rejected_per_code):
            base = base_valid_case(f"HIST-{idx:04d}")
            cases.append(mutate(base))
            idx += 1

    random.shuffle(cases)
    return cases


def main():
    os.makedirs(os.path.join(os.path.dirname(__file__), "..", "data"), exist_ok=True)
    cases = generate(500)
    output = os.path.abspath(OUTPUT_PATH)
    with open(output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=HEADERS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(cases)
    print(f"Generated {len(cases)} cases → {output}")
    # Stats
    from collections import Counter
    codes = Counter(c["reason_code"] for c in cases)
    for code, count in sorted(codes.items()):
        print(f"  {code}: {count}")


if __name__ == "__main__":
    main()


import io
import json
import re
import sys
from datetime import date
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


HEADERS = {
    "User-Agent": "Mozilla/5.0 CareerRadarV3/1.0"
}

DATE_PATTERN = (
    r"(20\d{2})\s*[./년-]\s*"
    r"(\d{1,2})\s*[./월-]\s*"
    r"(\d{1,2})\s*일?"
)

RANGE_PATTERN = re.compile(
    DATE_PATTERN + r"\s*(?:~|∼|～|부터|–|—)\s*" + DATE_PATTERN
)

SECTION_LABELS = {
    "duties": [
        "담당업무", "주요업무", "수행업무", "직무내용",
        "직무기술", "업무내용"
    ],
    "requirements": [
        "지원자격", "응시자격", "자격요건", "필수요건",
        "지원 요건"
    ],
    "preferences": [
        "우대사항", "우대조건", "우대요건"
    ],
    "employment": [
        "고용형태", "근로형태", "채용형태"
    ],
    "workplace": [
        "근무지", "근무장소", "근무지역", "근무처"
    ],
}

APPLICATION_LABELS = [
    "접수기간", "서류접수", "지원기간",
    "원서접수", "접수일정", "입사지원"
]


def clean(text):
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_response(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("HTTP 또는 HTTPS 주소만 허용합니다.")

    response = requests.get(
        url, headers=HEADERS, timeout=(10, 25)
    )
    response.raise_for_status()

    if response.encoding in (None, "ISO-8859-1"):
        response.encoding = response.apparent_encoding

    return response


def extract_html(response):
    soup = BeautifulSoup(response.text, "html.parser")

    for element in soup.select(
        "script, style, nav, footer, header"
    ):
        element.decompose()

    main = soup.select_one(
        "article, main, .board-view, .board_view, "
        ".view_cont, .bbs_view, #boardView"
    )

    content = main or soup.body or soup
    text = clean(content.get_text("\n", strip=True))

    attachments = []
    for link in content.select("a[href]"):
        href = urljoin(response.url, link["href"])
        label = link.get_text(" ", strip=True)

        if re.search(r"\.(pdf|hwp|hwpx)(?:\?|$)", href, re.I):
            attachments.append({
                "url": href,
                "label": label,
            })

    return text, attachments


def extract_pdf(response):
    reader = PdfReader(io.BytesIO(response.content))
    pages = []

    for page in reader.pages:
        pages.append(page.extract_text() or "")

    return clean("\n".join(pages))


def parse_date(groups):
    try:
        return date(
            int(groups[0]),
            int(groups[1]),
            int(groups[2])
        ).isoformat()
    except (ValueError, TypeError):
        return None


def extract_application(text):
    lines = text.splitlines()
    candidates = []

    for index, line in enumerate(lines):
        if any(label in line.replace(" ", "") for label in
               APPLICATION_LABELS):
            candidates.append(
                " ".join(lines[index:index + 5])
            )

    for candidate in candidates:
        match = RANGE_PATTERN.search(candidate)
        if not match:
            continue

        start = parse_date(match.groups()[:3])
        end = parse_date(match.groups()[3:])

        if not start or not end or start > end:
            continue

        tail = candidate[match.end():match.end() + 40]
        time_match = re.search(
            r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)",
            tail
        )

        deadline_time = (
            f"{int(time_match.group(1)):02d}:"
            f"{time_match.group(2)}"
            if time_match else None
        )

        return {
            "start": start,
            "deadline": end,
            "deadline_time": deadline_time,
            "evidence": candidate[:500],
        }

    return {
        "start": None,
        "deadline": None,
        "deadline_time": None,
        "evidence": None,
    }


def extract_section(text, labels):
    lines = [line.strip() for line in text.splitlines()]
    all_labels = [
        label
        for group in SECTION_LABELS.values()
        for label in group
    ]
    all_labels += APPLICATION_LABELS + [
        "전형절차", "제출서류", "접수방법",
        "기타사항", "유의사항", "문의처"
    ]

    for index, line in enumerate(lines):
        normalized = re.sub(r"\s+", "", line)

        matched = next(
            (
                label for label in labels
                if normalized.startswith(label.replace(" ", ""))
            ),
            None
        )

        if not matched:
            continue

        collected = []
        for next_line in lines[index:index + 14]:
            if collected and any(
                next_line.replace(" ", "").startswith(
                    label.replace(" ", "")
                )
                for label in all_labels
            ):
                break

            if next_line:
                collected.append(next_line)

        result = clean("\n".join(collected))
        if len(result) > len(matched) + 3:
            return result[:1800]

    return None


def verify(url):
    response = get_response(url)
    content_type = response.headers.get(
        "Content-Type", ""
    ).lower()

    if "pdf" in content_type or re.search(
        r"\.pdf(?:\?|$)", response.url, re.I
    ):
        text = extract_pdf(response)
        attachments = []
        document_type = "pdf"
    else:
        text, attachments = extract_html(response)
        document_type = "html"

    extracted_documents = [{
        "url": response.url,
        "type": document_type,
        "characters": len(text),
    }]
    errors = []

    for attachment in attachments[:8]:
        link = attachment["url"]
        if not re.search(r"\.pdf(?:\?|$)", link, re.I):
            errors.append({
                "url": link,
                "reason": "HWP/HWPX 파서는 아직 미지원",
            })
            continue

        try:
            pdf_response = get_response(link)
            pdf_text = extract_pdf(pdf_response)

            text += "\n" + pdf_text
            extracted_documents.append({
                "url": link,
                "type": "pdf",
                "characters": len(pdf_text),
            })
        except Exception as error:
            errors.append({
                "url": link,
                "reason": str(error),
            })

    application = extract_application(text)
    details = {
        key: extract_section(text, labels)
        for key, labels in SECTION_LABELS.items()
    }

    today = date.today().isoformat()
    deadline = application["deadline"]

    required_fields = [
        "duties", "requirements",
        "employment", "workplace"
    ]

    missing = [
        key for key in required_fields
        if not details[key]
    ]

    if not application["start"] or not deadline:
        missing.append("application_period")

    if deadline and deadline < today:
        status = "expired"
    elif missing:
        status = "needs_verification"
    elif errors:
        status = "needs_verification"
    else:
        status = "extracted_for_review"

    return {
        "source_url": response.url,
        "status": status,
        "application": application,
        "details": details,
        "documents": extracted_documents,
        "attachments": attachments,
        "missing_fields": missing,
        "errors": errors,
        "text_characters": len(text),
        "note": (
            "자동 추출 결과입니다. 공식 원문과의 "
            "대조 전에는 검증 완료로 간주하지 않습니다."
        ),
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "사용법: python verify_v3.py <공식공고URL>"
        )

    result = verify(sys.argv[1])
    print(json.dumps(
        result, ensure_ascii=False, indent=2
    ))

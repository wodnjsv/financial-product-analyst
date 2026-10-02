"""Canonical source-owned text for the bounded personal document query."""


def document_source_lines(row: dict) -> list[str]:
    return [
        f"공시일: {row.get('published_at') or '미확인'}",
        f"공시 링크: {row.get('filing_locator') or '출처 미확인'}",
        f"첨부 원문: {row.get('attachment_locator') or '출처 미확인'}",
        f"구역: {row.get('section_path') or '미확인'}",
        f"저장된 청크 페이지 범위: {row.get('page_start') or '미확인'}~{row.get('page_end') or '미확인'} (정확한 인용 페이지 미검증)",
    ]


def document_answer_text(rows: list[dict]) -> str:
    """Use complete supplied excerpts, without model prose or additional cuts."""
    counts = [row.get("matched_documents") for row in rows]
    if any(value is not None and (type(value) is not int or value < len(rows)) for value in counts):
        raise ValueError("COUNT_INVALID")
    if len({value for value in counts if value is not None}) > 1:
        raise ValueError("COUNT_CONFLICT")
    matched = counts[0] if all(value is not None for value in counts) else None
    datasets = {str(row["dataset_version"]) for row in rows if row.get("dataset_version")}
    if len(datasets) > 1:
        raise ValueError("DOCUMENT_DATASET_CONFLICT")
    lines = [
        f"데이터셋: {next(iter(datasets)) if datasets else '미확인'}",
        f"검색 일치 {matched}개 / 표시 {len(rows)}개" if matched is not None
        else f"검색 일치 건수 미확인 / 표시 {len(rows)}개",
    ]
    for row in rows:
        lines.extend(["", f"[{row['ref_id']}] {row.get('document_title') or '이름 미확인'}",
                      *document_source_lines(row), "원문 근거 (조회 발췌 전체):", row["excerpt"]])
    lines.extend(["", "조회 한계:",
        "복원한 100개 문서의 risk_factor 청크에서 키워드 포함 여부로 검색. 벡터 검색은 실행하지 않음.",
        "문서별 첫 일치 청크를 선택하고 공시일 내림차순으로 요청한 개수 이내에서 반환. 최신 공시 전체를 포괄하지 않음.",
        "2026-08-24까지의 적재 표본. 원문 근거를 표시하며 모델이 작성한 요약 설명은 포함하지 않음.",
        "조회 발췌와의 일치만 검증하며 PDF 추출 품질·전체 문맥·정확한 인용 페이지나 운영 Evidence 승격을 보증하지 않음.",
    ])
    return "\n".join(lines)

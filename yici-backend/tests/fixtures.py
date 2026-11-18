LIBRARY_ARTICLE = (
    "During exam week, the library moved its closing time from eight to ten. "
    "Some students used the extra time to study. "
    "Students who depended on the last bus still left at eight every evening."
)
LIBRARY_SENTENCES = [
    "During exam week, the library moved its closing time from eight to ten.",
    "Some students used the extra time to study.",
    "Students who depended on the last bus still left at eight every evening.",
]
LIBRARY_OPTIONS = [
    {"id": "A", "text": "The last bus began running two hours later."},
    {"id": "B", "text": "All students stayed longer after the library extended its hours."},
    {"id": "C", "text": "Students asked the library to open earlier during exam week."},
    {"id": "D", "text": "Some students took advantage of the later closing time."},
]
LIBRARY_STEM = "Which statement is supported by the report?"

UNKNOWN_ARTICLE = (
    "After the campus cafe introduced a loyalty card, weekday visits rose by fifteen percent. "
    "The manager said the card caused the increase. "
    "However, the same month, a new dormitory opened next door, bringing hundreds of residents within walking distance. "
    "The survey did not separate the two effects."
)
UNKNOWN_OPTIONS = [
    {"id": "A", "text": "The loyalty card caused weekday visits to rise."},
    {"id": "B", "text": "Weekday visits rose after the loyalty card was introduced."},
    {"id": "C", "text": "The new dormitory caused weekday visits to rise."},
    {"id": "D", "text": "The cafe raised its prices after introducing the loyalty card."},
]
UNKNOWN_STEM = "Which conclusion is best supported by the passage?"


def evidence_of(article: str, quote: str) -> dict:
    start = article.find(quote)
    assert start != -1, "fixture quote must exist verbatim in article"
    return {"quote": quote, "start": start, "end": start + len(quote)}


def library_payload(**overrides) -> dict:
    payload = {
        "article_text": LIBRARY_ARTICLE,
        "question_stem": LIBRARY_STEM,
        "options": LIBRARY_OPTIONS,
        "student_choice": "B",
        "compare_choice": "D",
        "answer_basis": "evidence",
        "evidence": [evidence_of(LIBRARY_ARTICLE, LIBRARY_SENTENCES[1])],
        "reference_answer": "D",
        "reference_explanation": "第二句直接支持 D；B 将受益群体扩大至全体，第三句提供反例。",
    }
    payload.update(overrides)
    return payload


def unknown_payload(**overrides) -> dict:
    payload = {
        "article_text": UNKNOWN_ARTICLE,
        "question_stem": UNKNOWN_STEM,
        "options": UNKNOWN_OPTIONS,
        "student_choice": "A",
        "compare_choice": "B",
        "answer_basis": "evidence",
        "evidence": [evidence_of(UNKNOWN_ARTICLE, "The manager said the card caused the increase.")],
        "reference_answer": "B",
    }
    payload.update(overrides)
    return payload
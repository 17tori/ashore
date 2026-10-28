"""Heuristic scam detection for vacancies. Strong signals reject, weak ones become visible risks."""

import re

STRONG = [
    (
        re.compile(
            r"(оплат\w*|внес\w*|купит\w*)\s+(за\s+)?(обучени|стажировк|униформ|форм[уы]|медкнижк|оформлени|пропуск)",
            re.I,
        ),
        "просят оплатить обучение, оформление или форму",
    ),
    (re.compile(r"(сетев\w+\s+маркетинг|\bmlm\b|\bмлм\b|пирамид)", re.I), "сетевой маркетинг"),
    (re.compile(r"(предоплат\w*|первоначальн\w+\s+взнос|вложени\w+\s+от)", re.I), "требуют вложений или предоплату"),
    (re.compile(r"(дроп\w*|обнал\w*|p2p[- ]?арбитраж|арбитраж\w*\s+(крипт|трафик))", re.I), "признаки финансовых схем"),
    (re.compile(r"(передать|предоставить)\s+(данные\s+)?(банковск\w+\s+)?карт", re.I), "просят банковскую карту"),
]

WEAK = [
    (re.compile(r"пассивн\w+\s+доход|доход\s+без\s+(вложений|опыта)\s+от", re.I), "обещания лёгкого дохода"),
    (
        re.compile(r"(пиши|пишите|писать)\s+(сразу\s+)?(в|на)\s+(телеграм|telegram|whatsapp|вотсап|ватсап)", re.I),
        "просят перейти в мессенджер",
    ),
    (re.compile(r"(без\s+собеседовани|работа\s+с\s+телефона\s+\d+\s+час)", re.I), "подозрительно простые условия"),
]


def fraud_signals(
    title: str, description: str, *, salary_from: int | None, experience_id: str | None
) -> tuple[list[str], list[str]]:
    text = f"{title}\n{description}"
    strong = [label for pattern, label in STRONG if pattern.search(text)]
    weak = [label for pattern, label in WEAK if pattern.search(text)]
    if experience_id == "noExperience" and salary_from and salary_from >= 250_000:
        weak.append("нереалистичная зарплата для позиции без опыта")
    return strong, weak



import json
import re


def extract_contacts(hotel_dir, url):

    md_path = (hotel_dir/ "connaissance.md")

    if not md_path.is_file():
        raise FileNotFoundError(
            f"Fichier introuvable : {md_path}"
        )

    text = md_path.read_text(encoding="utf-8")

    text = text.replace(r"**\@**","@")

    # EMAILS
    email_pattern = (r"\b[A-Za-z0-9._%+-]+"r"@[A-Za-z0-9.-]+"r"\.[A-Za-z]{2,}\b")

    emails = re.findall(email_pattern,text)

    emails = list(dict.fromkeys(emails))[:2] 

    # TÉLÉPHONES
    phone_pattern = (
        r"(?<!\d)"
        r"(?:\+33|0)"
        r"[\s.\-()]?"
        r"[1-9]"
        r"(?:[\s.\-()]?\d){8}"
        r"(?!\d)"
    )

    phones_raw = re.findall(
        phone_pattern,
        text
    )


    def normalize_phone(phone):

        digits = re.sub(
            r"\D",
            "",
            phone
        )

        if digits.startswith("33"):
            digits = "0" + digits[2:]

        if len(digits) != 10:
            return None

        if not digits.startswith("0"):
            return None

        return " ".join(
            digits[i:i + 2]
            for i in range(0, 10, 2)
        )


    phones_formatted = []

    for phone in phones_raw:

        phone_formatted = normalize_phone(
            phone
        )

        if phone_formatted is not None:
            phones_formatted.append(
                phone_formatted
            )


    phones_formatted = list(
        dict.fromkeys(
            phones_formatted
        )
    )


    mobile_phones = [
        phone
        for phone in phones_formatted
        if phone.startswith(("06", "07"))
    ]


    fixed_phones = [
        phone
        for phone in phones_formatted
        if phone.startswith(
            (
                "01",
                "02",
                "03",
                "04",
                "05",
                "08",
                "09"
            )
        )
    ]


    phones = (
        mobile_phones
        + fixed_phones
    )[:2]


    contacts = {
        "url": url,
        "emails": emails,
        "phones": phones
    }

    contacts_file = (
        hotel_dir
        / "contacts.json"
    )


    contacts_file.write_text(
        json.dumps(
            contacts,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


    return contacts
import re

from utils.nationalities import normalize_nationality
from utils.passport_numbers import normalize_passport_number


class PassportParser:

    def parse(self, text):
        mrz_lines = self.find_mrz_lines(text)

        if mrz_lines:
            return self.parse_mrz(
                mrz_lines[0],
                mrz_lines[1],
            )

        return {}

    def find_mrz_lines(self, text):
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip()
        ]

        mrz_candidates = []

        for line in lines:
            cleaned = self._clean_mrz_line(line)

            if len(cleaned) > 25 and "<" in cleaned:
                mrz_candidates.append(cleaned)

        if len(mrz_candidates) >= 2:
            return (
                mrz_candidates[-2],
                mrz_candidates[-1],
            )

        return None

    def _clean_mrz_line(self, line):
        cleaned = line.upper()
        cleaned = cleaned.replace(" ", "")
        cleaned = cleaned.replace("«", "<")
        cleaned = cleaned.replace("‹", "<")
        cleaned = cleaned.replace(">", "<")
        cleaned = re.sub(r"[^A-Z0-9<]", "", cleaned)
        return cleaned

    def parse_mrz(self, line1, line2):
        data = {}

        try:
            names_section = line1[5:]
            names_section = names_section.split("<<")

            surname = (
                names_section[0]
                .replace("<", " ")
                .strip()
            )

            given_names = (
                " ".join(names_section[1:])
                .replace("<", " ")
                .strip()
            )

            data["surname"] = surname
            data["given_names"] = given_names
            data["passport_number"] = normalize_passport_number(
                line2[0:9].replace("<", "")
            )
            data["nationality"] = normalize_nationality(line2[10:13])
            data["date_of_birth"] = line2[13:19]
            data["date_of_expiry"] = line2[21:27]

        except Exception:
            pass

        return data

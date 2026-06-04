from services.ocr_service import OCRService
from services.passport_parser import PassportParser


def main():
    ocr = OCRService()

    text = ocr.extract_text(
        "test_output/page_1.png"
    )

    print("\n===== OCR OUTPUT =====\n")
    print(text)

    parser = PassportParser()

    result = parser.parse(text)

    print("\n===== PARSED =====\n")
    print(result)


if __name__ == "__main__":
    main()

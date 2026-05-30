from services.ocr_service import OCRService

ocr = OCRService()

text = ocr.extract_text(
    r"test_output\page_1.png"
)

print("\n" + "=" * 50)
print("OCR RESULT")
print("=" * 50)
print(text)
print("=" * 50)
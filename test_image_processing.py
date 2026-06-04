from services.image_processing_service import (
    ImageProcessingService
)


def main():
    processor = ImageProcessingService()

    processor.process_upload(
        r"C:\Users\PerÃºLimaCentralMissi\Downloads\testingfile.pdf",
        "test_output"
    )


if __name__ == "__main__":
    main()

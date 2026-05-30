from services.image_processing_service import (
    ImageProcessingService
)

processor = ImageProcessingService()

processor.process_upload(
    r"C:\Users\PerúLimaCentralMissi\Downloads\testingfile.pdf",
    "test_output"
)
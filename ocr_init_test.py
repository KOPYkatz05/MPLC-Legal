from paddleocr import PaddleOCR

ocr = PaddleOCR(
    use_angle_cls=True,
    lang="en",
    det_model_dir=r"C:\Local Apps\paddle_models\.paddleocr\whl\det\en\en_PP-OCRv3_det_infer",
    rec_model_dir=r"C:\Local Apps\paddle_models\.paddleocr\whl\rec\en\en_PP-OCRv4_rec_infer",
    cls_model_dir=r"C:\Local Apps\paddle_models\.paddleocr\whl\cls\ch_ppocr_mobile_v2.0_cls_infer",
    show_log=False,
)

print("SUCCESS")
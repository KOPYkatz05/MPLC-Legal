import inspect


def main():
    from paddleocr import PaddleOCR

    print(inspect.signature(PaddleOCR))


if __name__ == "__main__":
    main()

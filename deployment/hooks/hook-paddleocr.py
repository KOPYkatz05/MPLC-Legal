from PyInstaller.utils.hooks import collect_dynamic_libs, get_package_paths


# PaddleOCR 2.x mutates sys.path and imports ppocr/tools/ppstructure from its
# physical package directory. Preserve the complete source tree as data so
# those imports work without attempting to import optional training modules
# during PyInstaller analysis.
_, package_dir = get_package_paths("paddleocr")
datas = [(package_dir, "paddleocr")]
binaries = collect_dynamic_libs("paddleocr")
hiddenimports = []
module_collection_mode = {"paddleocr": "py"}

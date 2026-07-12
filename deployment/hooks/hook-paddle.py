from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs


# Paddle's full submodule collector can crash while importing optional JIT/SOT
# modules. Let normal analysis follow Python imports, and explicitly preserve
# the native runtime plus non-Python package data required by inference.
datas = collect_data_files("paddle")
binaries = collect_dynamic_libs("paddle")
hiddenimports = [
    "paddle.base.core",
    "paddle.base.libpaddle",
    "paddle.inference",
    "paddle.nn.functional",
    "paddle.vision.transforms",
]

from PyInstaller.utils.hooks import collect_data_files


# Paddle imports its C++ extension helper at package import time. Cython then
# reads code-generation templates from Cython/Utility even though this app does
# not compile extensions at runtime.
datas = collect_data_files("Cython")


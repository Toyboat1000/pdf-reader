# PyInstaller build of the app as a folder (fast start, no unpacking at launch).
#
#     uv run pyinstaller packaging/pdf-reader.spec --noconfirm
#
# Usually run through packaging/build.ps1, which also makes the installer.
# The voice model is NOT bundled: the installer (or the app on first run) downloads
# it and checks its SHA-256.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

from pdf_reader.config.constants import APP_NAME, APP_VERSION

ROOT = Path(SPECPATH).parent  # noqa: F821 - defined by PyInstaller.
ICON = ROOT / "src" / "pdf_reader" / "ui" / "assets" / "app.ico"

import espeakng_loader  # noqa: E402 - needed only for its location.

espeak = Path(espeakng_loader.__file__).parent
datas = [
    (str(espeak / "espeak-ng.dll"), "espeakng_loader"),
    (str(espeak / "espeak-ng-data"), "espeakng_loader/espeak-ng-data"),
]
datas += collect_data_files("pdf_reader", includes=["ui/fonts/*", "ui/assets/*"])
datas += collect_data_files("kokoro_onnx")
for package in ("kokoro-onnx", "phonemizer", "onnxruntime", "pymupdf"):
    datas += copy_metadata(package)

hiddenimports = collect_submodules("winrt") + ["lameenc", "truststore"]

# Qt and other modules the app never uses; leaving them out makes the download smaller.
excludes = [
    "tkinter",
    "pytest",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtBluetooth",
    "PySide6.QtPositioning",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
]

numbers = tuple(int(part) for part in APP_VERSION.split(".")[:3]) + (0,)
version = VSVersionInfo(
    ffi=FixedFileInfo(filevers=numbers, prodvers=numbers),
    kids=[
        StringFileInfo(
            [
                StringTable(
                    "040904B0",
                    [
                        StringStruct("CompanyName", "PDF Reader contributors"),
                        StringStruct("FileDescription", APP_NAME),
                        StringStruct("FileVersion", APP_VERSION),
                        StringStruct("InternalName", APP_NAME),
                        StringStruct("LegalCopyright", "GNU AGPL v3.0 or later"),
                        StringStruct("OriginalFilename", f"{APP_NAME}.exe"),
                        StringStruct("ProductName", APP_NAME),
                        StringStruct("ProductVersion", APP_VERSION),
                    ],
                )
            ]
        ),
        VarFileInfo([VarStruct("Translation", [1033, 1200])]),
    ],
)

analysis = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(analysis.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    icon=str(ICON),
    version=version,
    console=False,
    # Compressing executables (UPX) often makes antivirus software flag them: off.
    upx=False,
)
COLLECT(  # noqa: F821
    exe,
    analysis.binaries,
    analysis.datas,
    name=APP_NAME,
    upx=False,
)

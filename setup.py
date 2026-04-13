from setuptools import setup


APP = ["images_to_pdf.py"]
OPTIONS = {
    "argv_emulation": False,
    "includes": [
        "tkinter",
        "tkinter.filedialog",
        "tkinter.scrolledtext",
        "tkinter.ttk",
    ],
    "packages": ["PIL"],
    "plist": {
        "CFBundleDisplayName": "Image to PDF",
        "CFBundleIdentifier": "me.nguyenkz.image-to-pdf",
        "CFBundleName": "ImageToPDF",
        "CFBundleShortVersionString": "1.0.0",
        "CFBundleVersion": "1.0.0",
        "LSMinimumSystemVersion": "12.0",
    },
}


setup(
    name="ImageToPDF",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)

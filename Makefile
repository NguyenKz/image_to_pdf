.PHONY: release relase build zip copy-release clean-release

APP_NAME := ImageToPDF.app
DIST_DIR := dist
APP_PATH := $(DIST_DIR)/$(APP_NAME)
APP_CONTENTS_LIB_DIR := $(APP_PATH)/Contents/lib
ZIP_NAME := App.zip
ZIP_PATH := $(DIST_DIR)/$(ZIP_NAME)
# Default to the existing repo folder, but allow overriding if needed.
RELEASE_DIR ?= releases
RELEASE_PATH := $(RELEASE_DIR)/$(ZIP_NAME)
TCL_TK_LIB_DIR := $(firstword $(wildcard /opt/homebrew/opt/tcl-tk/lib /usr/local/opt/tcl-tk/lib /Library/Frameworks/Python.framework/Versions/*/lib))
TCL_LIBRARY_DIR := $(firstword $(wildcard $(TCL_TK_LIB_DIR)/tcl8.6 $(TCL_TK_LIB_DIR)/tcl8.7))
TK_LIBRARY_DIR := $(firstword $(wildcard $(TCL_TK_LIB_DIR)/tk8.6 $(TCL_TK_LIB_DIR)/tk8.7))
TCL_PACKAGE_DIR := $(firstword $(wildcard $(TCL_TK_LIB_DIR)/tcl8))

ifneq ("$(wildcard .venv/bin/python)","")
PYTHON := .venv/bin/python
else ifneq ("$(wildcard venv/bin/python)","")
PYTHON := venv/bin/python
else
PYTHON := python
endif

release: clean-release build zip copy-release

# Keep a typo-compatible alias for the requested command name.
relase: release

build:
	rm -rf "$(APP_PATH)" "$(DIST_DIR)/Image to PDF.app"
	$(PYTHON) setup.py py2app
	@test -n "$(TCL_LIBRARY_DIR)" || (echo "Could not locate Tcl library directory" && exit 1)
	@test -n "$(TK_LIBRARY_DIR)" || (echo "Could not locate Tk library directory" && exit 1)
	mkdir -p "$(APP_CONTENTS_LIB_DIR)"
	rm -rf "$(APP_CONTENTS_LIB_DIR)/$(notdir $(TCL_LIBRARY_DIR))" "$(APP_CONTENTS_LIB_DIR)/$(notdir $(TK_LIBRARY_DIR))" "$(APP_CONTENTS_LIB_DIR)/tcl8"
	cp -R "$(TCL_LIBRARY_DIR)" "$(APP_CONTENTS_LIB_DIR)/"
	cp -R "$(TK_LIBRARY_DIR)" "$(APP_CONTENTS_LIB_DIR)/"
	@if [ -n "$(TCL_PACKAGE_DIR)" ]; then cp -R "$(TCL_PACKAGE_DIR)" "$(APP_CONTENTS_LIB_DIR)/"; fi

zip:
	rm -f "$(ZIP_PATH)"
	ditto -c -k --sequesterRsrc --keepParent "$(APP_PATH)" "$(ZIP_PATH)"

copy-release:
	mkdir -p "$(RELEASE_DIR)"
	cp -f "$(ZIP_PATH)" "$(RELEASE_PATH)"

clean-release:
	rm -f "$(ZIP_PATH)" "$(RELEASE_PATH)"

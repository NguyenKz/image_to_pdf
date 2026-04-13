.PHONY: release relase build zip copy-release clean-release

APP_NAME := Image to PDF.app
DIST_DIR := dist
APP_PATH := $(DIST_DIR)/$(APP_NAME)
ZIP_NAME := App.zip
ZIP_PATH := $(DIST_DIR)/$(ZIP_NAME)
# Default to the existing repo folder, but allow overriding if needed.
RELEASE_DIR ?= releases
RELEASE_PATH := $(RELEASE_DIR)/$(ZIP_NAME)

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
	$(PYTHON) setup.py py2app

zip:
	rm -f "$(ZIP_PATH)"
	ditto -c -k --sequesterRsrc --keepParent "$(APP_PATH)" "$(ZIP_PATH)"

copy-release:
	mkdir -p "$(RELEASE_DIR)"
	cp -f "$(ZIP_PATH)" "$(RELEASE_PATH)"

clean-release:
	rm -f "$(ZIP_PATH)" "$(RELEASE_PATH)"

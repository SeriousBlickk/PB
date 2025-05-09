#!/bin/bash
# Update pip to the latest version
python -m pip install --upgrade pip
# Install Python dependencies
pip install -r requirements.txt
# Install Playwright and browsers without root
pip install playwright
playwright install --with-deps
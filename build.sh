#!/bin/bash
# Update pip
python -m pip install --upgrade pip
# Install Python dependencies
pip install -r requirements.txt
# Install Playwright
pip install playwright
# Add additional apt sources for newer packages
apt-get update
apt-get install -y software-properties-common
add-apt-repository -y ppa:ubuntu-toolchain-r/test
apt-get update
# Install system dependencies for Playwright
apt-get install -y \
  libglib2.0-0 \
  libnss3 \
  libnspr4 \
  libatk1.0-0 \
  libatk-bridge2.0-0 \
  libcups2 \
  libdrm2 \
  libxkbcommon0 \
  libxcomposite1 \
  libxdamage1 \
  libxfixes3 \
  libxrandr2 \
  libgbm1 \
  libasound2 \
  libpango-1.0-0 \
  libcairo2 \
  libsoup-3.0-0 \
  libgstreamer1.0-0 \
  libgstreamer-gl1.0-0 \
  gstreamer1.0-plugins-bad \
  libenchant-2-2 \
  libsecret-1-0 \
  libmanette-0.2-0 \
  libgles2-mesa \
  libwebkit2gtk-4.1-0 \
  libgtk-3-0 \
  libegl1-mesa \
  libwoff1 \
  libharfbuzz-icu0 \
  libgstreamer-plugins-base1.0-0
# Install Playwright browsers
playwright install
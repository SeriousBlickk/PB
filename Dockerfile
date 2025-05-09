# Use Playwright base image
FROM mcr.microsoft.com/playwright:v1.44.0-jammy

# Set working directory
WORKDIR /app

# Update package lists and install Python dependencies in separate steps
RUN apt-get update || { echo "apt-get update failed"; exit 1; }

RUN apt-get install -y --no-install-recommends \
    python3.10 \
    python3.10-dev \
    python3-pip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* || { echo "apt-get install failed"; exit 1; }

# Create symbolic links for python and pip
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/pip3 /usr/bin/pip || { echo "Symbolic link creation failed"; exit 1; }

# Copy project files
COPY . .

# Install Python dependencies
RUN python -m pip install --upgrade pip || { echo "pip upgrade failed"; exit 1; }
RUN pip install -r requirements.txt || { echo "pip install requirements failed"; exit 1; }

# Expose port for health endpoint
EXPOSE 8000

# Run the bot
CMD ["python", "bot.py"]
# Use Playwright base image
FROM mcr.microsoft.com/playwright:v1.44.0-jammy

# Set working directory
WORKDIR /app

# Install Python and pip
RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-dev && \
    ln -s /usr/bin/python3 /usr/bin/python && \
    ln -s /usr/bin/pip3 /usr/bin/pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Install Python dependencies
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

# Expose port for health endpoint
EXPOSE 8000

# Run the bot
CMD ["python", "bot.py"]
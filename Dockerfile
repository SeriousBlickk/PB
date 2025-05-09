# Use a lightweight Python base image
FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install dependencies
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends && \
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
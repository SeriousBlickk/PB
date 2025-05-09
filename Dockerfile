# Use Playwright's Ubuntu-based image with dependencies
FROM mcr.microsoft.com/playwright:v1.44.0-jammy

# Set working directory
WORKDIR /app

# Install Python 3.10 and dependencies
RUN apt-get update && \
    apt-get install -y python3.10 python3-pip python3.10-venv && \
    ln -s /usr/bin/python3.10 /usr/bin/python

# Copy project files
COPY . .

# Install Python dependencies
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

# Expose port for health endpoint
EXPOSE 8000

# Run the bot
CMD ["python", "bot.py"]
# Use Playwright base image
FROM mcr.microsoft.com/playwright:v1.44.0-jammy

# Set working directory
WORKDIR /app

# Copy project files
COPY . .

# Install Python dependencies
RUN python -m pip install --upgrade pip && \
    pip install -r requirements.txt

# Expose port for health endpoint
EXPOSE 8000

# Run the bot
CMD ["python", "bot.py"]
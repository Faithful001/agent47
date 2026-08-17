FROM python:3.12-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set PYTHONPATH so Python resolves agent47 package in /app/src
ENV PYTHONPATH="/app/src"

# Ensure start.sh is executable and execute it as container entrypoint
RUN chmod +x start.sh
CMD ["./start.sh"]
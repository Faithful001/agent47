FROM python:3.12-slim

# Install railpack
RUN curl -sSL https://railpack.com/install.sh | bash

# Rest of your setup
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

ENV PYTHONPATH="/app/src"
CMD ["celery", "-A", "agent47.infra.queue", "worker", "--loglevel=info"]
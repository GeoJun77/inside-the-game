# Inside the Game - live web app, for Azure Container Apps.
#
# No secret goes into the image: the app reaches Microsoft Foundry with the container's
# managed identity (DefaultAzureCredential) and reads its settings from environment
# variables; the Speech key is a Container Apps secret.
FROM python:3.12-slim

# The Azure Speech SDK needs OpenSSL, ALSA's library and the CA certificates on Linux.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libssl3 libasound2 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app
COPY requirements-app.txt .
RUN pip install --no-cache-dir -r requirements-app.txt

# The code, the trained xG model and the matchsim calibration (see .dockerignore).
COPY agents ./agents
COPY app ./app
COPY matchsim ./matchsim
COPY xg ./xg
COPY models ./models

# The stadium sounds are made once, here, so the first visitor hears the crowd at once.
RUN python -c "import app.server as s; s.build_crowd_samples()"

# Run as a non-root user.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
CMD ["python", "-m", "app.server"]

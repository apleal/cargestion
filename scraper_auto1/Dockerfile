FROM python:3.12-slim

# Google Chrome: el servicio usa Selenium con Chrome, igual que el script que
# ya funcionaba con la cuenta de Auto1. Selenium Manager descarga el chromedriver.
RUN apt-get update \
    && apt-get install -y --no-install-recommends wget gnupg ca-certificates fonts-liberation \
    && wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scraper.py horario.py ajustes.py ./

CMD ["python", "-u", "scraper.py"]

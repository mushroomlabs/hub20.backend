# Start with a Python image.
FROM python:3.8

ENV PYTHONUNBUFFERED 1

# Update image
RUN apt-get update

# Install raiden and dependencies to generate keystore file
RUN pip install --no-cache-dir raiden==2.0.0

RUN pip install eth-keyfile eth-keys toml

COPY ./run_raiden.py /app/run_raiden.py

WORKDIR /app

CMD ["python", "run_raiden.py"]

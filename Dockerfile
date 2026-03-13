# -------------------------------
# Dockerfile: Python scripts only
# -------------------------------
FROM ubuntu:22.04

# Install Python and build dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-venv python3-pip \
    curl unzip build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Make 'python' command available
RUN ln -sf /usr/bin/python3 /usr/bin/python

# Create a Python virtual environment
RUN python3 -m venv /opt/venv

# Upgrade pip inside the virtualenv
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy requirements and install inside the virtualenv
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Copy your Python scripts into /usr/local/bin
COPY bin/ /usr/local/bin/
RUN chmod +x /usr/local/bin/*.py

# Activate virtualenv automatically for all commands
ENV PATH="/opt/venv/bin:/usr/local/bin:$PATH"

# Set working directory
WORKDIR /data

# Flexible execution — no fixed entrypoint
ENTRYPOINT []
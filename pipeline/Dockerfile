FROM ubuntu:22.04

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3 python3-venv python3-pip \
    curl unzip build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Make 'python' command available
RUN ln -sf /usr/bin/python3 /usr/bin/python

# Create virtual environment
RUN python3 -m venv /opt/venv

# Upgrade pip
RUN /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Install OBITools4
RUN curl -L https://raw.githubusercontent.com/metabarcoding/obitools4/master/install_obitools.sh | bash -s -- --version 4.4.29

# Copy your scripts
COPY bin/ /usr/local/bin/
RUN chmod +x /usr/local/bin/*.py

# Activate virtualenv + include OBITools
ENV PATH="/opt/venv/bin:/root/.local/bin:/usr/local/bin:$PATH"

# Set working directory
WORKDIR /data

# No fixed entrypoint (Nextflow-friendly)
ENTRYPOINT []
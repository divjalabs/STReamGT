FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    curl unzip build-essential gcc git python3 python3-pip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PATH="/root/.local/bin:/usr/local/bin:$PATH"

RUN curl -L https://raw.githubusercontent.com/metabarcoding/obitools4/master/install_obitools.sh | bash

WORKDIR /data

ENTRYPOINT []
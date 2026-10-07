FROM alpine:3.22
RUN apk add --no-cache g++ python3 py3-psutil bash coreutils procps util-linux && adduser -D -u 1000 judge
COPY minioj/__init__.py minioj/runner.py minioj/launcher.py /opt/minioj/
COPY scripts/container_exec.py scripts/container_files.py scripts/container_idle.py scripts/container_cleanup.py /opt/
ENV PYTHONDONTWRITEBYTECODE=1 HOME=/workspace TMPDIR=/tmp
USER 1000:1000
WORKDIR /workspace
CMD ["python3", "/opt/container_idle.py"]

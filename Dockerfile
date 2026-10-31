# Runs the study agent in a container.
#
# Build:  docker build -t study-agent .
# Run:    docker run -it --rm -e ANTHROPIC_API_KEY study-agent
# Your own notes (mounted read-only at /data):
#         docker run -it --rm -e ANTHROPIC_API_KEY -v ~/my-notes:/data:ro study-agent /data
#
# The API key is passed in at run time with -e. Never put it in this file
# (for example with ENV): it would be saved into the image's layers, and
# anyone with the image could read it.

FROM python:3.14-slim

# Print output immediately (the agent is interactive), and don't write
# .pyc files into the image.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install dependencies first, in their own layer. Docker caches layers, so
# editing agent.py later won't reinstall packages unless requirements.txt
# changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Then the app itself: the agent, its skills, and the sample folder.
COPY agent.py .
COPY skills/ skills/
COPY sample_docs/ sample_docs/

# Run as an ordinary user, not root, so the agent and any script it runs
# can't modify the app or the rest of the container's system files.
RUN useradd --create-home --uid 1000 agent
USER agent

# `docker run ... study-agent` uses sample_docs; anything after the image
# name replaces it, e.g. `docker run ... study-agent /data`.
ENTRYPOINT ["python", "agent.py"]
CMD ["sample_docs"]

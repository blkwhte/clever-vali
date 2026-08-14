# ---------------------------------------------------------------------------
# Clever Vali — Dockerfile
# ---------------------------------------------------------------------------
# We use the official Microsoft Playwright image as our base rather than a
# plain Python image. This is the most important decision in this file —
# Playwright requires a specific set of system libraries and browser binaries
# that are painful to install manually. The Playwright base image has all of
# that pre-configured, including Chromium, so we don't have to.
#
# The tag pins us to a specific Playwright version. When you update the
# playwright version in requirements.txt, update this tag to match.
# Find available tags at: https://mcr.microsoft.com/en-us/artifact/mar/playwright/python
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

# Set the working directory inside the container.
# All subsequent commands run from here, and this is where your files live.
WORKDIR /app

# ---------------------------------------------------------------------------
# Install Python dependencies
# ---------------------------------------------------------------------------
# We copy requirements.txt first and install dependencies before copying
# the rest of the code. This is a Docker best practice — it means Docker
# can cache the dependency layer and skip reinstalling packages on every
# build as long as requirements.txt hasn't changed. Only code changes won't
# bust the cache.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Install Playwright browsers
# ---------------------------------------------------------------------------
# The base image includes Playwright's system dependencies but not the
# browser binaries themselves. We install only Chromium since that's all
# Vali uses — installing all browsers would add unnecessary image size.
RUN playwright install chromium

# ---------------------------------------------------------------------------
# Copy application code
# ---------------------------------------------------------------------------
# Now we copy everything else. Files listed in .dockerignore are excluded.
COPY . .

# ---------------------------------------------------------------------------
# Runtime configuration
# ---------------------------------------------------------------------------
# Tell Flask to listen on all interfaces (0.0.0.0) rather than just
# localhost — this is required for the port to be accessible from outside
# the container. Without this, the server starts but you can't reach it.
ENV FLASK_RUN_HOST=0.0.0.0

# Expose port 5000 — this documents which port the app uses. The actual
# port mapping (host:container) is done at runtime with -p 5000:5000.
EXPOSE 5000

# ---------------------------------------------------------------------------
# Playwright sandbox flag
# ---------------------------------------------------------------------------
# Chromium inside a Docker container requires --no-sandbox because the
# container's Linux environment doesn't support the kernel namespacing
# that Chromium's sandbox relies on. We set this as an environment variable
# that vali_core.py reads when launching the browser.
#
# NOTE: vali_core.py needs to pass this flag to chromium.launch() —
# see the comment in vali_core.py's browser launch calls.
ENV PLAYWRIGHT_CHROMIUM_SANDBOX=false

# ---------------------------------------------------------------------------
# Start the dashboard
# ---------------------------------------------------------------------------
CMD ["python3", "dashboard.py"]

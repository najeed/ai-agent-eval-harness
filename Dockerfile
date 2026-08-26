# [P1.6/V05] UI build stage: the Visual Suite is built from source so images
# never depend on CDN-loaded prototypes and air-gapped deploys get the full UX.
FROM node:20-alpine AS ui-build

WORKDIR /build/ui/visual-console

# Install pinned dependencies first for layer caching
COPY ui/visual-console/package.json ui/visual-console/package-lock.json ./
RUN npm ci

# Build the production bundle (tsc -b && vite build)
COPY ui/visual-console/ ./
RUN npm run build && test -f dist/index.html

# Use a slim Python image for a smaller footprint
FROM python:3.12-slim

# Upgrade OS packages to apply security patches
RUN apt-get update && apt-get upgrade -y && apt-get clean && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
# NOTE: pip 26.0.1 is currently vulnerable to CVE-2026-3219 (concatenated archives).
# Ensure all requirements and local sources are trusted before building.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Overlay the freshly built Visual Suite (source tree may ship without dist)
COPY --from=ui-build /build/ui/visual-console/dist ./ui/visual-console/dist

# Fail the image build if the UI bundle is missing (defense in depth)
RUN test -f ui/visual-console/dist/index.html

# Install the package in editable mode to register the eval-harness script
RUN pip install -e .

# Create directory for reports
RUN mkdir -p reports/trajectories

# Set the entrypoint to the eval-harness CLI
ENTRYPOINT ["eval-harness"]

# Default command shows help
CMD ["--help"]

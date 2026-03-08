# Use a slim Python image for a smaller footprint
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements first to leverage Docker cache
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Install the package in editable mode to register the eval-harness script
RUN pip install -e .

# Create directory for reports
RUN mkdir -p reports/trajectories

# Set the entrypoint to the eval-harness CLI
ENTRYPOINT ["eval-harness"]

# Default command shows help
CMD ["--help"]

# Use a slim Python image
FROM python:3.11-slim

# Set the working directory
WORKDIR /app

# Copy requirements (Agent only needs Flask, requests, etc.)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the sample agent code
COPY sample_agent/ ./sample_agent/

# Expose the Flask port
EXPOSE 5001

# Set the working directory to where the agent app resides
WORKDIR /app/sample_agent

# Run the flask app
CMD ["python", "agent_app.py"]

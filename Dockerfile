# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    # Set path for Flask app files within the container
    FLASK_APP_DIR=/app \
    # Default Waitress settings (can be overridden at runtime or via docker-compose)
    WAITRESS_HOST=0.0.0.0 \
    WAITRESS_PORT=5000 \
    WAITRESS_THREADS=4

# Set the working directory in the container
WORKDIR ${FLASK_APP_DIR}

# Install system dependencies
# - ffmpeg: Required for audio merging
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    # Clean up apt caches to reduce image size
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Use --no-cache-dir to reduce image size
# Ensure waitress is listed in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
# Ensure templates folder and entrypoint script are copied
COPY . .

# Make the entrypoint script executable
RUN chmod +x entrypoint.sh

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define the command to run the application using the entrypoint script
CMD ["./entrypoint.sh"]


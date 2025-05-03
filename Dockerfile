# Use an official Python runtime as a parent image
FROM python:3.13-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    # Set Flask environment variables
    FLASK_APP=app.py \
    FLASK_RUN_HOST=0.0.0.0 \
    FLASK_RUN_PORT=5000 \
    # Set path for Flask templates
    FLASK_APP_DIR=/app

# Set the working directory in the container
WORKDIR ${FLASK_APP_DIR}

# Install system dependencies
# - ffmpeg: Required for audio merging (either by pydub or directly)
# - git: Might be needed by pip for some dependencies (optional but safer)
# - build-essential: Might be needed for compiling some Python packages (optional but safer)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    # git \
    # build-essential \
    # Clean up apt caches to reduce image size
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Copy the requirements file into the container
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Make port 5000 available to the world outside this container
EXPOSE 5000

# Define the command to run the application
# Using Flask's built-in server (suitable for development/low-traffic)
# For production, consider using Gunicorn: CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]
CMD ["flask", "run"]


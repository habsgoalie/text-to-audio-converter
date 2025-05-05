# EPUB/PDF to MP3 Web Converter

This project provides a simple web application, run via Docker, that converts text content from uploaded EPUB or PDF files into a downloadable MP3 audio file. It uses Microsoft Edge's high-quality online text-to-speech (TTS) service via the `edge-tts` library.

## Features

* Web-based interface for easy file upload and conversion.
* Supports EPUB and PDF input files.
* Uses Microsoft Edge's online TTS for high-quality voices.
* Allows selection of different en-US neural voices.
* Handles large files by chunking text for TTS processing.
* Merges audio chunks into a single downloadable MP3 file.
* Packaged as a Docker container for easy deployment and sharing.

## Prerequisites

1.  **Docker:** You must have Docker installed and running on your machine. Download from <https://www.docker.com/products/docker-desktop/>.

## Running the Application (Using Pre-built Docker Image)

This is the easiest way to run the application, as it uses the pre-built image directly from the GitHub Container Registry (ghcr.io).

1.  **Pull the Docker Image:** Open your terminal or command prompt and pull the latest image:
    ```bash
    docker pull ghcr.io/habsgoalie/text-to-audio-converter:latest
    ```
    *(Note: If the package is private on GitHub, you might need to log in first using `docker login ghcr.io`)*

2.  **Run the Docker Container:** Once the image is downloaded, start the container:
    ```bash
    docker run -p 5000:5000 --rm --name tts-web ghcr.io/habsgoalie/text-to-audio-converter:latest
    ```
    * `-p 5000:5000`: Maps port 5000 inside the container to port 5000 on your host machine.
    * `--rm`: Automatically removes the container when you stop it (e.g., by pressing `Ctrl+C` in the terminal where it's running).
    * `--name tts-web`: Assigns a convenient name to the running container.
    * `ghcr.io/habsgoalie/text-to-audio-converter:latest`: The full name of the image to run.

3.  **Access the Web App:** Open your web browser and navigate to:
    <http://localhost:5000>

## Using the Web Interface

1.  **Upload File:** Click "Choose File" and select an EPUB or PDF file from your computer.
2.  **Select Voice:** Choose your preferred voice from the dropdown menu (defaults to Steffan).
3.  **Convert:** Click the "Convert to MP3" button.
4.  **Wait:** The status area will show the progress ("Uploading...", "Processing...", "Converting chunk X/Y...", "Merging..."). This may take some time depending on the file size.
5.  **Download:** Once the status shows "complete", a download link for the generated MP3 file will appear. Click the link to save the audio file.

## Building from Source (Alternative)

If you prefer to build the image yourself:

1.  **Get the Code:** Clone or download the project files:
    ```bash
    git clone [https://github.com/habsgoalie/text-to-audio-converter.git](https://github.com/habsgoalie/text-to-audio-converter.git)
    cd text-to-audio-converter
    ```
2.  **Build the Docker Image:**
    ```bash
    docker build -t text-to-audio-converter-web .
    ```
3.  **Run the Docker Container:**
    ```bash
    docker run -p 5000:5000 --rm --name tts-web text-to-audio-converter-web
    ```

## Technology Stack

* **Backend:** Python, Waitress
* **Text-to-Speech:** `edge-tts` library (using Microsoft Edge online TTS)
* **EPUB Parsing:** `EbookLib`, `BeautifulSoup4`
* **PDF Parsing:** `PyMuPDF`
* **Audio Merging:** `ffmpeg` (called via `subprocess`)
* **Containerization:** Docker

## Notes

* Uploaded files and generated MP3s are stored temporarily within the running Docker container and are typically removed when the container stops (due to the `--rm` flag).
* There is a default file upload size limit of 50MB, configured in `app.py`.


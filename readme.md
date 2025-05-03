# EPUB/PDF to MP3 Converter

This Python script converts text content from EPUB or PDF files into a single MP3 audio file using Microsoft Edge's high-quality online text-to-speech (TTS) service via the `edge-tts` library. It handles large files by splitting the text into chunks for TTS processing and then merges the resulting audio chunks into one final MP3 file.

## Features

* Supports EPUB and PDF input files.
* Uses Microsoft Edge's online TTS for high-quality voices.
* Chunks large text files to avoid TTS limits and improve reliability.
* Merges audio chunks into a single MP3 output file per input file.
* Allows selection of different TTS voices.
* Command-line interface for easy use.

## Prerequisites

1.  **Python:** Version 3.7 or newer is required.
2.  **ffmpeg:** This is essential for merging the audio chunks. `pydub`, the library used for merging, relies on it.
    * Download and install `ffmpeg` from the official website: <https://ffmpeg.org/download.html>
    * **Crucially:** Ensure the directory containing `ffmpeg.exe` (on Windows) or `ffmpeg` (on macOS/Linux) is added to your system's **PATH environment variable** so the script can find it. You can verify this by opening a *new* terminal/command prompt and typing `ffmpeg -version`.
3.  **pip:** Python's package installer (usually comes with Python).

## Setup

1.  **Get the Code:** Download or clone the script (`convert_to_audio_merged.py`) and the `requirements.txt` file into a dedicated project directory (e.g., `text_to_audio_converter`).
2.  **Create a Virtual Environment:** Open your terminal or command prompt, navigate to the project directory, and create a virtual environment. This isolates the project's dependencies.
    * **macOS/Linux:**
        ```bash
        cd path/to/text_to_audio_converter
        python3 -m venv venv
        source venv/bin/activate
        ```
    * **Windows (Command Prompt):**
        ```bash
        cd path\to\text_to_audio_converter
        python -m venv venv
        venv\Scripts\activate.bat
        ```
    * **Windows (PowerShell):**
        ```bash
        cd path\to\text_to_audio_converter
        python -m venv venv
        .\venv\Scripts\Activate.ps1
        ```
        *(Note: You might need to adjust PowerShell's execution policy first: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`)*

    You should see `(venv)` appear at the beginning of your terminal prompt, indicating the environment is active.
3.  **Install Dependencies:** With the virtual environment active, install the required Python libraries using the `requirements.txt` file:
    ```bash
    pip install -r requirements.txt
    ```
    *(This installs `edge-tts`, `ebooklib`, `beautifulsoup4`, `PyMuPDF`, and `pydub`).*
4.  **Windows Specific Dependency (Optional but recommended):** If you encounter import errors related to `audioop` or `pyaudioop` when running the script on Windows (even with ffmpeg installed), you might need to install a helper package:
    ```bash
    pip install audioop-lts
    ```
    *(Update `requirements.txt` afterwards if you add this: `pip freeze > requirements.txt`)*

## Usage

Run the script from your terminal or command prompt while the virtual environment is active.

```bash
python convert_to_audio_merged.py [options] input_file
```

**Arguments:**

* `input_file`: (Required) The path to the input EPUB or PDF file you want to convert.

**Options:**

* `-o OUTPUT`, `--output OUTPUT`:
    * Specifies the path for the final output MP3 file.
    * If omitted, the output file will be saved in a sub-directory named `output_audio/` with a name based on the input file (e.g., `output_audio/my_book.mp3`).
* `-v VOICE`, `--voice VOICE`:
    * Specifies the TTS voice to use. Find available voices using `--list-voices`.
    * Default: `en-US-AriaNeural`
* `--list-voices`:
    * Lists all available TTS voices supported by `edge-tts` and exits. Use this to find the `ShortName` for the `--voice` option.
* `--no-chunking`:
    * Disables text chunking and merging. The script will attempt to process the entire file text in one go.
    * **Warning:** This may fail for large files due to TTS service limits, and no merging will occur. Use with caution.
* `-h`, `--help`:
    * Shows the help message describing the arguments and options.

**Examples:**

1.  **Convert an EPUB with default settings:**
    ```bash
    python convert_to_audio_merged.py "My Book Title.epub"
    ```
    *(Output will be in `output_audio/My Book Title.mp3`)*
2.  **Convert a PDF and specify the output file name:**
    ```bash
    python convert_to_audio_merged.py document.pdf -o my_audiobook.mp3
    ```
3.  **Convert using a specific voice (British English):**
    ```bash
    python convert_to_audio_merged.py report.pdf --voice en-GB-SoniaNeural
    ```
4.  **List available voices:**
    ```bash
    python convert_to_audio_merged.py --list-voices
    ```

## Output

* The script creates temporary files in a system temporary directory during processing. These are automatically deleted upon successful completion.
* If merging fails (e.g., ffmpeg issue), the temporary chunk files might be kept for debugging. The script will print the path to the temporary directory in this case.
* The final, merged MP3 file is saved either to the path specified with `-o` or in the `output_audio` sub-directory by default.


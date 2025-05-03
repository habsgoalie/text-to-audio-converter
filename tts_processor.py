# tts_processor.py
"""
Core logic for converting EPUB/PDF to MP3 using edge-tts.
Designed to be imported and used by a web application or other scripts.
"""

import asyncio
import edge_tts
import os
import sys
import re
import ebooklib # Requires: pip install EbookLib
from ebooklib import epub
from bs4 import BeautifulSoup, NavigableString # Requires: pip install beautifulsoup4
import fitz # PyMuPDF, Requires: pip install PyMuPDF
import tempfile # For temporary directory
import shutil # For file operations (moving, deleting directory) and finding executables
import subprocess # To check for ffmpeg
import logging # For better logging

# --- Configuration ---
# Using environment variables for flexibility in Docker, with defaults
DEFAULT_VOICE = os.environ.get("DEFAULT_VOICE", "en-US-AriaNeural")
MAX_CHUNK_SIZE = int(os.environ.get("MAX_CHUNK_SIZE", 4500))

# --- Setup Logging ---
# Configure logging to output to stderr, which Docker can capture
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)


# --- Globals for ffmpeg paths (set during check) ---
FFMPEG_PATH = None
FFPROBE_PATH = None

def check_and_set_ffmpeg_paths():
    """
    Checks if ffmpeg/ffprobe are available and sets the global paths.
    Returns True if both are found, False otherwise.
    """
    global FFMPEG_PATH, FFPROBE_PATH
    logger.info("Checking for ffmpeg and ffprobe availability...")
    try:
        ffmpeg_exe = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
        FFMPEG_PATH = shutil.which(ffmpeg_exe)

        ffprobe_exe = 'ffprobe.exe' if os.name == 'nt' else 'ffprobe'
        FFPROBE_PATH = shutil.which(ffprobe_exe)

        if FFMPEG_PATH and FFPROBE_PATH:
            logger.info(f"ffmpeg found at: {FFMPEG_PATH}")
            logger.info(f"ffprobe found at: {FFPROBE_PATH}")
            # Explicitly set pydub paths *if* pydub is used (currently not, but good practice)
            try:
                from pydub import AudioSegment
                AudioSegment.converter = FFMPEG_PATH
                AudioSegment.ffprobe = FFPROBE_PATH
                logger.info("Set pydub ffmpeg/ffprobe paths.")
            except ImportError:
                 logger.warning("pydub not found or import failed, skipping path setting for it.")
            except Exception as e:
                 logger.warning(f"Could not set pydub paths: {e}")

            return True
        else:
            if not FFMPEG_PATH:
                logger.error(f"'{ffmpeg_exe}' command not found in system PATH.")
            if not FFPROBE_PATH:
                 logger.error(f"'{ffprobe_exe}' command not found in system PATH.")
            return False
    except Exception as e:
        logger.error(f"Error checking for ffmpeg/ffprobe using shutil.which: {e}")
        return False

# --- Text Extraction & Cleaning (Adapted from previous script) ---

def clean_text(text):
    """ Basic text cleaning: remove excessive whitespace. """
    if not isinstance(text, str):
        return ""
    text = text.strip()
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'(\r?\n[ \t]*){2,}', '\n\n', text)
    # Convert single newlines not part of a paragraph break into spaces
    text = re.sub(r'(?<!\n)\r?\n(?!\n)', ' ', text)
    text = re.sub(r' +', ' ', text) # Ensure single spaces
    return text.strip()

def extract_text_from_pdf(pdf_path):
    """ Extracts text from all pages of a PDF file using PyMuPDF. """
    full_text = ""
    logger.info(f"Attempting to open PDF: {pdf_path}")
    try:
        doc = fitz.open(pdf_path)
        logger.info(f"Opened PDF: {len(doc)} pages.")
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            page_text = page.get_text("text")
            full_text += page_text.strip() + "\n\n"
        doc.close()
        logger.info(f"Successfully extracted ~{len(full_text)} characters from PDF.")
        return full_text.strip()
    except Exception as e:
        logger.error(f"Error opening or reading PDF {pdf_path}: {e}")
        raise ValueError(f"Failed to process PDF file: {e}") from e

def extract_text_from_epub(epub_path):
    """ Extracts text content from an EPUB file's HTML/XHTML items more carefully. """
    full_text = ""
    processed_item_ids = set()
    logger.info(f"Attempting to open EPUB: {epub_path}")
    try:
        book = epub.read_epub(epub_path)
        logger.info("Opened EPUB. Extracting text from documents...")
        items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        logger.info(f"Found {len(items)} document items.")

        for item in items:
            if item.get_id() in processed_item_ids:
                logger.warning(f"Skipping duplicate item ID: {item.get_id()}")
                continue
            processed_item_ids.add(item.get_id())

            content = item.get_content()
            soup = BeautifulSoup(content, 'html.parser')
            body = soup.find('body')
            item_text = ""

            if body:
                for element in body.children:
                    if isinstance(element, NavigableString):
                        stripped_string = element.strip()
                        if len(stripped_string) > 1:
                             item_text += stripped_string + " "
                        continue
                    if element.name in ['script', 'style', 'nav', 'header', 'footer', 'aside', 'figure', 'img', 'br', 'hr']:
                        continue
                    block_text = element.get_text(separator=' ', strip=True)
                    if block_text:
                        item_text += block_text + "\n\n"
            else:
                logger.warning(f"No <body> tag found in item {item.get_id()}. Trying to extract all text.")
                item_text = soup.get_text(separator='\n\n', strip=True)

            if item_text.strip():
                full_text += item_text.strip() + "\n\n"

        logger.info(f"Successfully extracted ~{len(full_text)} characters from EPUB (before final cleaning).")
        # Apply final cleaning
        return clean_text(full_text)

    except Exception as e:
        logger.error(f"Error opening or reading EPUB {epub_path}: {e}")
        raise ValueError(f"Failed to process EPUB file: {e}") from e

# --- TTS and Chunking (Adapted from previous script) ---

async def text_to_speech(text, output_filename, voice=DEFAULT_VOICE):
    """ Converts a chunk of text to speech using edge-tts and saves as MP3 """
    if not text or not text.strip():
        logger.warning("Skipping empty text chunk.")
        return False

    logger.info(f"Starting TTS conversion for: {os.path.basename(output_filename)} (Voice: {voice})")
    try:
        output_dir = os.path.dirname(output_filename)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_filename)

        if not os.path.exists(output_filename) or os.path.getsize(output_filename) == 0:
             logger.error(f"TTS process completed but the output file is missing or empty: {output_filename}")
             if os.path.exists(output_filename):
                 try: os.remove(output_filename)
                 except OSError as rm_err: logger.warning(f"Could not remove empty file {output_filename}: {rm_err}")
             return False

        logger.info(f"Successfully saved audio chunk to: {output_filename}")
        return True
    except edge_tts.NoAudioReceived:
        logger.error(f"No audio received from TTS service for chunk. Text may be invalid or empty. Skipping.")
        return False
    except Exception as e:
        logger.error(f"Error during text-to-speech conversion for {output_filename}: {e}")
        return False

def chunk_text(text, max_size=MAX_CHUNK_SIZE):
    """ Splits text into chunks smaller than max_size. """
    chunks = []
    current_chunk = ""
    paragraphs = text.split('\n\n')

    for para in paragraphs:
        para = para.strip()
        if not para: continue
        if len(current_chunk) + len(para) + 2 > max_size:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = ""
            if len(para) > max_size:
                sentences = re.split(r'(?<=[.!?])\s+', para)
                temp_chunk = ""
                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence: continue
                    if len(temp_chunk) + len(sentence) + 1 > max_size:
                        if temp_chunk: chunks.append(temp_chunk.strip())
                        if len(sentence) > max_size:
                            logger.warning(f"Sentence exceeds max chunk size ({max_size}). Splitting arbitrarily.")
                            for i in range(0, len(sentence), max_size): chunks.append(sentence[i:i+max_size])
                            temp_chunk = ""
                        else: temp_chunk = sentence + " "
                    else: temp_chunk += sentence + " "
                if temp_chunk: chunks.append(temp_chunk.strip())
                current_chunk = ""
            else: current_chunk = para + "\n\n"
        else: current_chunk += para + "\n\n"
    if current_chunk.strip(): chunks.append(current_chunk.strip())
    logger.info(f"Split text into {len(chunks)} chunks for processing.")
    return chunks

# --- Merging using FFmpeg directly ---

def merge_audio_chunks_ffmpeg(chunk_files, final_output_path, temp_dir):
    """ Merges a list of MP3 chunk files into a single MP3 file using ffmpeg directly. """
    if not FFMPEG_PATH:
        logger.error("ffmpeg path not found. Cannot merge.")
        raise EnvironmentError("ffmpeg path not configured correctly.")

    if not chunk_files:
        logger.error("No audio chunks provided for merging.")
        return False
    if len(chunk_files) == 1:
        logger.info("Only one chunk found, no merging needed. Moving temporary file.")
        try:
            final_dir = os.path.dirname(final_output_path)
            if final_dir: os.makedirs(final_dir, exist_ok=True)
            shutil.move(chunk_files[0], final_output_path)
            logger.info(f"Final audio saved to: {final_output_path}")
            return True
        except Exception as e:
            logger.error(f"Error moving single chunk file: {e}")
            return False

    logger.info(f"Merging {len(chunk_files)} audio chunks into {final_output_path} using ffmpeg...")
    list_file_path = os.path.join(temp_dir, "concat_list.txt")
    try:
        with open(list_file_path, 'w', encoding='utf-8') as f:
            for chunk_file in sorted(chunk_files): # Sort for consistent order
                if os.path.exists(chunk_file) and os.path.getsize(chunk_file) > 0:
                    safe_path = chunk_file.replace("\\", "/")
                    f.write(f"file '{safe_path}'\n") # Use quotes for safety
                else:
                    logger.warning(f"Skipping missing or empty chunk file in list: {chunk_file}")

        if os.path.getsize(list_file_path) == 0:
            logger.error("No valid chunk files found to add to the ffmpeg list.")
            return False

        final_dir = os.path.dirname(final_output_path)
        if final_dir: os.makedirs(final_dir, exist_ok=True)

        command = [
            FFMPEG_PATH, '-y', '-f', 'concat', '-safe', '0',
            '-i', list_file_path, '-c', 'copy', final_output_path
        ]
        logger.info(f"Running ffmpeg command: {' '.join(command)}")

        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE

        result = subprocess.run(command, capture_output=True, text=True, check=False, startupinfo=startupinfo)

        if result.returncode == 0:
            logger.info(f"Successfully merged audio chunks using ffmpeg.")
            logger.info(f"Final audio saved to: {final_output_path}")
            return True
        else:
            logger.error(f"ffmpeg command failed with return code {result.returncode}")
            logger.error(f"ffmpeg stderr:\n{result.stderr}")
            return False
    except Exception as e:
        logger.error(f"Error during ffmpeg merging process: {e}")
        return False
    finally:
        if os.path.exists(list_file_path):
            try: os.remove(list_file_path)
            except OSError as e: logger.warning(f"Failed to remove temporary list file {list_file_path}: {e}")

# --- Main Processing Function ---

async def process_file(input_path, final_output_path, voice=DEFAULT_VOICE, use_chunking=True, status_callback=None):
    """
    Main processing logic: extract text, chunk, TTS, and merge using ffmpeg.
    Returns the path to the final output file on success, raises Exception on failure.
    Calls status_callback(message) if provided.
    """
    if status_callback: status_callback("Checking tools...")
    if use_chunking and not check_and_set_ffmpeg_paths():
        raise EnvironmentError("ffmpeg/ffprobe required for merging but not found in PATH.")

    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found at '{input_path}'")

    logger.info(f"Processing file: {input_path}")
    logger.info(f"Final output target: {final_output_path}")

    # --- Text Extraction ---
    _, extension = os.path.splitext(input_path)
    extension = extension.lower()
    text = None
    try:
        if status_callback: status_callback(f"Extracting text from {extension}...")
        if extension == ".pdf":
            text = extract_text_from_pdf(input_path)
        elif extension == ".epub":
            text = extract_text_from_epub(input_path)
        else:
            raise ValueError(f"Unsupported file type '{extension}'. Only '.pdf' and '.epub' are supported.")
    except Exception as e:
        logger.error(f"Text extraction failed: {e}")
        raise

    if not text or not text.strip():
        raise ValueError("Text extraction failed or resulted in empty content.")

    # --- Create Temporary Directory for Chunks ---
    temp_dir = tempfile.mkdtemp(prefix="tts_chunks_")
    logger.info(f"Created temporary directory for chunks: {temp_dir}")
    successful_chunk_files = []
    merge_success = False

    try:
        # --- Chunking ---
        if use_chunking:
            if status_callback: status_callback("Splitting text into chunks...")
            text_chunks = chunk_text(text, MAX_CHUNK_SIZE)
        else:
            logger.info("Chunking disabled. Processing text as a single block.")
            text_chunks = [text]

        total_chunks = len(text_chunks)
        if total_chunks == 0:
            raise ValueError("No text chunks generated after splitting.")

        # --- TTS Conversion for each chunk ---
        for i, chunk in enumerate(text_chunks):
            chunk_num = i + 1
            logger.info(f"--- Processing Chunk {chunk_num}/{total_chunks} ---")
            if status_callback: status_callback(f"Converting chunk {chunk_num}/{total_chunks} to audio...")

            temp_chunk_filename = os.path.abspath(os.path.join(temp_dir, f"chunk_{chunk_num:03d}.mp3"))
            success = await text_to_speech(chunk, temp_chunk_filename, voice)

            if success:
                successful_chunk_files.append(temp_chunk_filename)
            else:
                logger.warning(f"Failed to process chunk {chunk_num}. Skipping this chunk.")
                # Decide if you want to raise an error or continue
                # raise RuntimeError(f"Failed to convert chunk {chunk_num} to speech.")

        # --- Merging ---
        if not successful_chunk_files:
            raise RuntimeError("No audio chunks were successfully generated.")

        if use_chunking:
            logger.info("--- Merging Audio Chunks ---")
            if status_callback: status_callback(f"Merging {len(successful_chunk_files)} audio chunks...")
            merge_success = merge_audio_chunks_ffmpeg(successful_chunk_files, final_output_path, temp_dir)
            if not merge_success:
                 raise RuntimeError("Merging audio chunks failed.")
        else: # Handling --no-chunking output
            logger.info("--- Single Chunk Processing ---")
            try:
                final_dir = os.path.dirname(final_output_path)
                if final_dir: os.makedirs(final_dir, exist_ok=True)
                shutil.move(successful_chunk_files[0], final_output_path)
                logger.info(f"Successfully saved single audio file to: {final_output_path}")
                merge_success = True # Treat move as success for cleanup
            except Exception as e:
                logger.error(f"Error moving single audio file: {e}")
                raise RuntimeError(f"Failed to move single audio file: {e}") from e

        logger.info("--- Conversion Finished ---")
        return final_output_path # Return the final path on success

    except Exception as e:
        logger.error(f"An error occurred during processing: {e}")
        # Keep temp files on error for debugging
        logger.error(f"Temporary files kept in: {temp_dir}")
        raise # Re-raise the exception to be caught by the caller
    finally:
        # Clean up only if the entire process (including merge/move) was successful
        if merge_success and os.path.exists(temp_dir):
            logger.info(f"Cleaning up temporary directory: {temp_dir}")
            try:
                shutil.rmtree(temp_dir)
                logger.info("Temporary directory removed.")
            except Exception as e:
                logger.warning(f"Failed to remove temporary directory {temp_dir}: {e}")

# --- Main execution block (for standalone testing) ---
async def main_standalone():
    parser = argparse.ArgumentParser(description="Convert EPUB/PDF to MP3 (Standalone Test)")
    parser.add_argument("input_file", help="Path to input file")
    parser.add_argument("-o", "--output", help="Path for final output MP3")
    parser.add_argument("-v", "--voice", default=DEFAULT_VOICE, help="TTS voice")
    parser.add_argument("--no-chunking", action="store_true", help="Disable chunking")
    args = parser.parse_args()

    if not args.output:
        base = os.path.splitext(os.path.basename(args.input_file))[0]
        args.output = f"{base}.mp3"
        logger.info(f"Output path not specified, defaulting to: {args.output}")

    def print_status(msg):
        print(f"STATUS: {msg}")

    try:
        output_file = await process_file(
            args.input_file,
            args.output,
            voice=args.voice,
            use_chunking=not args.no_chunking,
            status_callback=print_status
        )
        print(f"\nSuccess! Output saved to: {output_file}")
    except Exception as e:
        print(f"\nError during conversion: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    # This allows testing the processor logic directly
    asyncio.run(main_standalone())

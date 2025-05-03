#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Converts EPUB or PDF files to a single MP3 audio file using Microsoft Edge's
online TTS service, handling large files via chunking and merging using pydub.
"""

import asyncio
import edge_tts
import argparse
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
# NOTE: pydub import moved inside merge_audio_chunks to delay loading
# Requires ffmpeg or libav installed system-wide and in PATH (brew install ffmpeg / download from ffmpeg.org)

# --- Configuration ---
DEFAULT_VOICE = "en-US-SteffanNeural" # Default voice - find others with --list-voices
OUTPUT_DIR = "output_audio"       # Default directory to save MP3 files
# Max characters per chunk for TTS. edge-tts might handle large text,
# but chunking prevents potential issues and allows resuming if interrupted.
# Adjust based on testing and desired file size.
MAX_CHUNK_SIZE = 4500
# Globals to store ffmpeg check status and path
FFMPEG_CHECKED = False
FFMPEG_AVAILABLE = False
FFMPEG_PATH = None
FFPROBE_PATH = None # Also store ffprobe path, often needed by pydub
# --- End Configuration ---

def check_ffmpeg():
    """
    Checks if ffmpeg and ffprobe commands are accessible in the system PATH.
    Stores their paths if found.
    """
    global FFMPEG_AVAILABLE, FFMPEG_CHECKED, FFMPEG_PATH, FFPROBE_PATH
    if FFMPEG_CHECKED:
        return FFMPEG_AVAILABLE

    print("Checking for ffmpeg and ffprobe availability...")
    try:
        # Find ffmpeg path
        ffmpeg_exe = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
        FFMPEG_PATH = shutil.which(ffmpeg_exe)

        # Find ffprobe path (usually in the same directory)
        ffprobe_exe = 'ffprobe.exe' if os.name == 'nt' else 'ffprobe'
        FFPROBE_PATH = shutil.which(ffprobe_exe)

        if FFMPEG_PATH and FFPROBE_PATH:
            print(f"ffmpeg found at: {FFMPEG_PATH}")
            print(f"ffprobe found at: {FFPROBE_PATH}")
            FFMPEG_AVAILABLE = True
        else:
            if not FFMPEG_PATH:
                print(f"Error: '{ffmpeg_exe}' command not found in system PATH.", file=sys.stderr)
            if not FFPROBE_PATH:
                 print(f"Error: '{ffprobe_exe}' command not found in system PATH (needed by pydub).", file=sys.stderr)
            FFMPEG_AVAILABLE = False

    except Exception as e:
        print(f"Error checking for ffmpeg/ffprobe using shutil.which: {e}", file=sys.stderr)
        FFMPEG_AVAILABLE = False

    FFMPEG_CHECKED = True
    if not FFMPEG_AVAILABLE:
         print("-------------------------------------------------------------", file=sys.stderr)
         print("Please ensure ffmpeg is installed (including ffprobe) and", file=sys.stderr)
         print("its 'bin' directory is added to your system's PATH.", file=sys.stderr)
         print("Download from: https://ffmpeg.org/download.html", file=sys.stderr)
         print("-------------------------------------------------------------", file=sys.stderr)
    return FFMPEG_AVAILABLE


def clean_text(text):
    """ Basic text cleaning: remove excessive whitespace. """
    if not isinstance(text, str):
        return ""
    text = text.strip()
    # Replace multiple whitespace characters (including newlines, tabs) with a single space
    # Keep paragraph breaks (\n\n) added during extraction
    text = re.sub(r'[ \t]+', ' ', text) # Replace spaces/tabs with single space
    text = re.sub(r'(\r?\n[ \t]*){2,}', '\n\n', text) # Consolidate multiple newlines+whitespace into double newline
    text = re.sub(r'(\r?\n)', ' ', text) # Replace single newlines with space (unless part of \n\n) - careful with this one
    text = re.sub(r' +', ' ', text) # Ensure single spaces
    return text.strip()

def extract_text_from_pdf(pdf_path):
    """ Extracts text from all pages of a PDF file using PyMuPDF. """
    full_text = ""
    print(f"Attempting to open PDF: {pdf_path}")
    try:
        doc = fitz.open(pdf_path)
        print(f"Opened PDF: {len(doc)} pages.")
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            page_text = page.get_text("text") # Extract plain text
            # Add a separator between pages - using paragraph break for TTS pacing
            full_text += page_text.strip() + "\n\n"
        doc.close()
        print(f"Successfully extracted ~{len(full_text)} characters from PDF.")
        # Use a more basic cleaning for the combined text
        return full_text.strip() # Keep paragraph breaks
    except Exception as e:
        print(f"Error opening or reading PDF {pdf_path}: {e}", file=sys.stderr)
        return None

def extract_text_from_epub(epub_path):
    """ Extracts text content from an EPUB file's HTML/XHTML items more carefully. """
    full_text = ""
    processed_item_ids = set() # Keep track of processed item IDs to avoid duplicates if items repeat

    print(f"Attempting to open EPUB: {epub_path}")
    try:
        book = epub.read_epub(epub_path)
        print("Opened EPUB. Extracting text from documents...")
        # Iterate through EPUB items of type 'document' (usually HTML/XHTML)
        items = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        print(f"Found {len(items)} document items.")

        for item in items:
            # Skip if this item ID has already been processed (handles some malformed EPUBs)
            if item.get_id() in processed_item_ids:
                print(f"Skipping duplicate item ID: {item.get_id()}")
                continue
            processed_item_ids.add(item.get_id())

            content = item.get_content()
            soup = BeautifulSoup(content, 'html.parser')
            body = soup.find('body')
            item_text = ""

            if body:
                # Iterate through direct children of the body tag
                for element in body.children:
                    # Skip navigable strings (raw text not in a tag) unless they contain significant content
                    if isinstance(element, NavigableString):
                        stripped_string = element.strip()
                        if len(stripped_string) > 1: # Avoid adding just whitespace or single chars
                             item_text += stripped_string + " " # Add space separation
                        continue

                    # Skip non-relevant tags (like script, style, etc.)
                    if element.name in ['script', 'style', 'nav', 'header', 'footer', 'aside', 'figure', 'img', 'br', 'hr']:
                        continue

                    # Process relevant block-level tags or divs/spans potentially containing text
                    # Use get_text with a separator to maintain some structure within the block
                    # strip=True removes leading/trailing whitespace from the extracted text block
                    block_text = element.get_text(separator=' ', strip=True)

                    if block_text: # Only add if text was found
                        item_text += block_text + "\n\n" # Add paragraph break after each processed element's text

            else:
                # Fallback if no body tag is found (unlikely for valid EPUB)
                print(f"Warning: No <body> tag found in item {item.get_id()}. Trying to extract all text.", file=sys.stderr)
                item_text = soup.get_text(separator='\n\n', strip=True)


            if item_text.strip(): # Add text from this item if it's not empty
                # Apply basic cleaning to the text extracted from this item
                # cleaned_item_text = clean_text(item_text) # Apply cleaning per item
                # full_text += cleaned_item_text + "\n\n" # Add paragraph break between items
                # Let's accumulate raw text first and clean at the end
                full_text += item_text.strip() + "\n\n"


        print(f"Successfully extracted ~{len(full_text)} characters from EPUB (before final cleaning).")
        # Apply final cleaning to the entire extracted text
        #return clean_text(full_text)
        # Let's return without clean_text for now to see raw extraction result
        return full_text.strip()

    except Exception as e:
        print(f"Error opening or reading EPUB {epub_path}: {e}", file=sys.stderr)
        return None


async def list_available_voices():
    """ Lists available voices using edge-tts """
    print("Fetching available voices...")
    try:
        voices = await edge_tts.list_voices()
        print("-" * 60)
        print("Available Voices (use 'ShortName' with --voice):")
        print("-" * 60)
        # Sort voices for better readability
        for voice in sorted(voices, key=lambda v: v['ShortName']):
            print(f"  ShortName: {voice['ShortName']}")
            print(f"     Gender: {voice['Gender']}")
            print(f"     Locale: {voice['Locale']}")
            print("-" * 20)
        print("-" * 60)
    except Exception as e:
        print(f"Could not retrieve voices: {e}", file=sys.stderr)

async def text_to_speech(text, output_filename, voice=DEFAULT_VOICE):
    """ Converts a chunk of text to speech using edge-tts and saves as MP3 """
    if not text or not text.strip():
        print("Warning: Skipping empty text chunk.", file=sys.stderr)
        return False

    print(f"Starting TTS conversion for: {os.path.basename(output_filename)} (Voice: {voice})")
    try:
        # Ensure the output directory exists (needed for temporary files)
        output_dir = os.path.dirname(output_filename)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        # Create Communicate object and save the audio
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_filename)

        # Check if the file was actually created and has size
        if not os.path.exists(output_filename) or os.path.getsize(output_filename) == 0:
             print(f"Error: TTS process completed but the output file is missing or empty: {output_filename}", file=sys.stderr)
             print("This might happen with certain text inputs (e.g., only symbols). Skipping chunk.", file=sys.stderr)
             # Attempt to remove the empty file if it exists
             if os.path.exists(output_filename):
                 try:
                     os.remove(output_filename)
                 except OSError as rm_err:
                     print(f"Warning: Could not remove empty file {output_filename}: {rm_err}", file=sys.stderr)
             return False


        print(f"Successfully saved audio chunk to: {output_filename}")
        return True
    except edge_tts.NoAudioReceived:
        print(f"Error: No audio received from TTS service for chunk. Text may be invalid or empty. Skipping.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error during text-to-speech conversion for {output_filename}: {e}", file=sys.stderr)
        # Optional: Log the problematic text chunk (can be long)
        # print(f"Problematic text (first 100 chars): {text[:100]}...", file=sys.stderr)
        return False

def chunk_text(text, max_size=MAX_CHUNK_SIZE):
    """
    Splits text into chunks smaller than max_size.
    Tries to split at paragraph breaks (\n\n) first, then sentences (.!?).
    """
    chunks = []
    current_chunk = ""

    # Split by paragraphs first
    paragraphs = text.split('\n\n')

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # If adding the next paragraph exceeds max_size
        if len(current_chunk) + len(para) + 2 > max_size: # +2 for potential '\n\n'
            # If current chunk has content, add it to the list
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = "" # Reset current chunk *before* handling the new paragraph

            # If the paragraph itself is too large, split it further
            if len(para) > max_size:
                #print(f"DEBUG: Paragraph exceeds max size ({len(para)} > {max_size}). Splitting by sentences.") # Optional Debug
                # Split by sentences (basic split, might need refinement)
                sentences = re.split(r'(?<=[.!?])\s+', para) # Split after sentence end punctuation
                temp_chunk = ""
                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    # If adding sentence exceeds max size
                    if len(temp_chunk) + len(sentence) + 1 > max_size:
                        if temp_chunk:
                            chunks.append(temp_chunk.strip())
                        # If the sentence itself is too large, split it arbitrarily
                        if len(sentence) > max_size:
                            print(f"Warning: Sentence exceeds max chunk size ({max_size}). Splitting arbitrarily.", file=sys.stderr)
                            for i in range(0, len(sentence), max_size):
                                chunks.append(sentence[i:i+max_size])
                            temp_chunk = "" # Reset after handling oversized sentence
                        else:
                            temp_chunk = sentence + " " # Start new chunk with this sentence
                    else:
                        temp_chunk += sentence + " " # Add sentence to current temp chunk

                # Add the last part of the split paragraph
                if temp_chunk:
                    chunks.append(temp_chunk.strip())

                # Ensure current_chunk is empty after processing a large paragraph
                current_chunk = ""

            # If the paragraph is not too large itself, start the next chunk with it
            # This paragraph didn't fit with the previous current_chunk
            else:
                 current_chunk = para + "\n\n"

        # Otherwise, add the paragraph to the current chunk
        else:
            current_chunk += para + "\n\n"

    # Add the last remaining chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    print(f"Split text into {len(chunks)} chunks for processing.")
    return chunks

def merge_audio_chunks(chunk_files, final_output_path):
    """ Merges a list of MP3 chunk files into a single MP3 file using pydub. """
    global FFMPEG_PATH, FFPROBE_PATH # Access the stored paths

    # --- Check if ffmpeg/ffprobe paths were found ---
    if not FFMPEG_PATH or not FFPROBE_PATH:
        print("Error: ffmpeg or ffprobe path not found during initial check.", file=sys.stderr)
        print("Merging skipped. Temporary chunk files are kept.", file=sys.stderr)
        return False # Indicate merge failure

    # --- Import pydub and set paths *before* use ---
    try:
        print("Attempting to import pydub and set converter paths...")
        # Explicitly tell pydub where ffmpeg and ffprobe are *before* loading AudioSegment
        # This is often necessary on Windows or if they aren't discoverable automatically
        from pydub import AudioSegment
        AudioSegment.converter = FFMPEG_PATH
        AudioSegment.ffprobe   = FFPROBE_PATH
        print(f"pydub converter set to: {AudioSegment.converter}")
        print(f"pydub ffprobe set to: {AudioSegment.ffprobe}")

    except ImportError as e:
         # Catch the import error here if it still happens
         # Now potentially fixed by audioop-lts, but keep check just in case
         print(f"Error: Failed to import pydub ({e}).", file=sys.stderr)
         print("Ensure pydub and potentially audioop-lts are installed correctly.", file=sys.stderr)
         return False # Indicate merge failure
    except Exception as e: # Catch any other potential errors during setup
         print(f"An unexpected error occurred during pydub setup: {e}", file=sys.stderr)
         return False


    if not chunk_files:
        print("Error: No audio chunks provided for merging.", file=sys.stderr)
        return False
    if len(chunk_files) == 1:
        print("Only one chunk found, no merging needed. Renaming temporary file.")
        try:
            # Ensure the target directory exists
            final_dir = os.path.dirname(final_output_path)
            if final_dir:
                os.makedirs(final_dir, exist_ok=True)
            shutil.move(chunk_files[0], final_output_path)
            print(f"Final audio saved to: {final_output_path}")
            return True
        except Exception as e:
            print(f"Error moving single chunk file: {e}", file=sys.stderr)
            return False

    print(f"Merging {len(chunk_files)} audio chunks into {final_output_path}...")
    combined = AudioSegment.empty()
    try:
        # Ensure chunk_files are sorted numerically for correct order
        sorted_chunk_files = sorted(chunk_files)

        for i, chunk_file in enumerate(sorted_chunk_files): # Use sorted list
             print(f"  Adding chunk {i+1}/{len(sorted_chunk_files)}: {os.path.basename(chunk_file)}")
             # Check if file exists and is not empty before loading
             if os.path.exists(chunk_file) and os.path.getsize(chunk_file) > 0:
                 # Now load the segment, pydub should use the explicitly set converter/ffprobe
                 segment = AudioSegment.from_mp3(chunk_file)
                 combined += segment # Append the segment
             else:
                 print(f"Warning: Skipping missing or empty chunk file: {chunk_file}", file=sys.stderr)

        if len(combined) == 0:
            print("Error: Combined audio is empty. Merging failed (perhaps all chunks were invalid?).", file=sys.stderr)
            return False

        # Export the combined audio
        # Ensure the target directory exists
        final_dir = os.path.dirname(final_output_path)
        if final_dir:
            os.makedirs(final_dir, exist_ok=True)
        print(f"Exporting combined audio to {final_output_path}...")
        combined.export(final_output_path, format="mp3")
        print(f"Successfully merged audio chunks.")
        print(f"Final audio saved to: {final_output_path}")
        return True
    except FileNotFoundError as fnf_err:
         # This error might still occur if, despite setting the path, pydub fails to execute ffmpeg/ffprobe
         print(f"Error during merging (FileNotFoundError): {fnf_err}", file=sys.stderr)
         print("This *might* indicate an issue executing ffmpeg/ffprobe even though the path was set.", file=sys.stderr)
         print(f"Check permissions for: {FFMPEG_PATH} and {FFPROBE_PATH}", file=sys.stderr)
         return False
    except Exception as e:
        # Catch pydub specific errors if possible, otherwise general exception
        # Look for common pydub runtime errors
        err_str = str(e).lower()
        if "audiosegment" in err_str or "conversion failed" in err_str or "ffmpeg" in err_str:
             print(f"Error during pydub operation: {e}", file=sys.stderr)
        else:
             print(f"Error merging audio chunks: {e}", file=sys.stderr)
        return False


async def process_file(input_path, output_path=None, voice=DEFAULT_VOICE, use_chunking=True):
    """Main processing logic: extract text, chunk, TTS, and merge using pydub."""
    # --- Check for ffmpeg early if chunking is enabled (needed for merging) ---
    # This also stores the paths in global variables if found
    if use_chunking:
        if not check_ffmpeg():
            print("Error: ffmpeg/ffprobe is required for merging chunks but was not found.", file=sys.stderr)
            print("To proceed without merging, use the --no-chunking flag (may fail for large files),", file=sys.stderr)
            print("or install ffmpeg and add it to your PATH.", file=sys.stderr)
            return # Stop processing if ffmpeg needed but not found

    if not os.path.exists(input_path):
        print(f"Error: Input file not found at '{input_path}'", file=sys.stderr)
        return

    # --- Determine Final Output Path ---
    if output_path:
        # Use user-provided output path
        final_output_path = output_path
        # Ensure the extension is .mp3
        base, ext = os.path.splitext(final_output_path)
        if ext.lower() != ".mp3":
            final_output_path = base + ".mp3"
            print(f"Warning: Output extension was not '.mp3'. Changed to: {final_output_path}", file=sys.stderr)
        # Ensure the directory for the final output exists
        final_output_dir = os.path.dirname(final_output_path)
        if final_output_dir:
             os.makedirs(final_output_dir, exist_ok=True)
    else:
        # Generate default output name in OUTPUT_DIR
        base_name = os.path.basename(input_path)
        file_name_no_ext = os.path.splitext(base_name)[0]
        os.makedirs(OUTPUT_DIR, exist_ok=True) # Ensure default output dir exists
        final_output_path = os.path.join(OUTPUT_DIR, f"{file_name_no_ext}.mp3")

    print(f"Input file: {input_path}")
    print(f"Final output file target: {final_output_path}")

    # --- Text Extraction ---
    _, extension = os.path.splitext(input_path)
    extension = extension.lower()
    text = None
    if extension == ".pdf":
        print(f"Processing PDF file...")
        text = extract_text_from_pdf(input_path)
    elif extension == ".epub":
        print(f"Processing EPUB file...")
        text = extract_text_from_epub(input_path) # Using updated function
    else:
        print(f"Error: Unsupported file type '{extension}'. Only '.pdf' and '.epub' are supported.", file=sys.stderr)
        return

    if not text or not text.strip():
        print("Error: Text extraction failed or resulted in empty content.", file=sys.stderr)
        return

    # --- Create Temporary Directory for Chunks ---
    temp_dir = tempfile.mkdtemp(prefix="tts_chunks_")
    print(f"Created temporary directory for chunks: {temp_dir}")
    successful_chunk_files = [] # List to store paths of successfully created chunks
    merge_success = False # Initialize merge status

    try:
        # --- Chunking ---
        if use_chunking:
            text_chunks = chunk_text(text, MAX_CHUNK_SIZE)
        else:
            print("Chunking disabled. Processing text as a single block.")
            text_chunks = [text] # Treat the whole text as one chunk

        total_chunks = len(text_chunks)
        if total_chunks == 0:
            print("Error: No text chunks generated after splitting.", file=sys.stderr)
            # Clean up temp dir if no chunks
            if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
            return # Exit if no chunks

        # --- TTS Conversion for each chunk ---
        for i, chunk in enumerate(text_chunks):
            chunk_num = i + 1
            print(f"\n--- Processing Chunk {chunk_num}/{total_chunks} ---")

            # Define temporary filename for this chunk's audio
            # Ensure paths are absolute for safety
            temp_chunk_filename = os.path.abspath(os.path.join(temp_dir, f"chunk_{chunk_num:03d}.mp3"))

            # --- REMOVED DEBUG PRINTS FOR TEXT CHUNK ---

            # Perform TTS for the chunk, save to temporary file
            success = await text_to_speech(chunk, temp_chunk_filename, voice)

            if success:
                # Add the path of the successfully created chunk file to the list
                successful_chunk_files.append(temp_chunk_filename)
            else:
                print(f"Failed to process chunk {chunk_num}. Skipping this chunk.", file=sys.stderr)
                # Optional: Decide whether to stop on failure
                # print("Stopping process due to chunk failure.", file=sys.stderr)
                # return # Uncomment to stop processing after the first failed chunk

        # --- Merging (only if chunking was used and chunks were successful) ---
        if use_chunking:
            print("\n--- Merging Audio Chunks ---")
            if not successful_chunk_files:
                 print("Error: No audio chunks were successfully generated. Cannot create final file.", file=sys.stderr)
                 # Make sure temp dir is cleaned up even if we exit here
                 if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
                 return # Exit if no chunks succeeded

            # --- DEBUG: Print the list of files to be merged ---
            print(f"DEBUG: Files to merge ({len(successful_chunk_files)}):")
            # Sort the list for consistent order in debugging output
            sorted_files_for_debug = sorted(successful_chunk_files)
            for f_path in sorted_files_for_debug:
                print(f"  - {os.path.basename(f_path)}") # Print just the filename for brevity
            # --- END DEBUG ---


            # Use the pydub merging function
            merge_success = merge_audio_chunks(successful_chunk_files, final_output_path)

            if merge_success:
                print("--- Conversion Finished ---")
            else:
                print("--- Conversion Finished with Merging Errors ---", file=sys.stderr)
                print(f"Temporary chunk files are kept in: {temp_dir}", file=sys.stderr)
                # Avoid deleting temp dir if merging failed, so user can inspect
                return # Exit without cleanup
        else:
            # --- Handling --no-chunking ---
            print("\n--- Single Chunk Processing ---")
            if successful_chunk_files:
                # Move the single generated chunk file to the final destination
                try:
                    # Ensure the target directory exists
                    final_dir = os.path.dirname(final_output_path)
                    if final_dir:
                        os.makedirs(final_dir, exist_ok=True)
                    shutil.move(successful_chunk_files[0], final_output_path)
                    print(f"Successfully saved single audio file to: {final_output_path}")
                    print("--- Conversion Finished ---")
                    merge_success = True # Treat as success for cleanup purposes
                except Exception as e:
                    print(f"Error moving single audio file: {e}", file=sys.stderr)
                    print(f"Temporary file is kept in: {temp_dir}", file=sys.stderr)
                    return # Exit without cleanup
            else:
                print("Error: The single audio chunk failed to generate.", file=sys.stderr)
                # Make sure temp dir is cleaned up even if we exit here
                if os.path.exists(temp_dir): shutil.rmtree(temp_dir)
                return # Exit without cleanup


    except Exception as e:
        print(f"\nAn unexpected error occurred during processing: {e}", file=sys.stderr)
        # Optionally keep temp files on unexpected error
        print(f"Temporary chunk files (if any) are in: {temp_dir}", file=sys.stderr)
        return # Exit without cleanup
    finally:
        # --- Cleanup ---
        # Only clean up if merging/moving was successful
        if merge_success and os.path.exists(temp_dir):
            print(f"Cleaning up temporary directory: {temp_dir}")
            try:
                shutil.rmtree(temp_dir)
                print("Temporary directory removed.")
            except Exception as e:
                print(f"Warning: Failed to remove temporary directory {temp_dir}: {e}", file=sys.stderr)
        elif not merge_success and os.path.exists(temp_dir):
            # Handle case where processing failed before merge attempt or merge failed
             print(f"Process did not complete successfully. Keeping temporary files in: {temp_dir}", file=sys.stderr)


async def main():
    """Parses arguments and initiates the conversion process."""
    parser = argparse.ArgumentParser(
        description="Convert EPUB or PDF file to a single MP3 audio file using edge-tts.\nRequires ffmpeg to be installed and in PATH for merging audio chunks.",
        formatter_class=argparse.RawTextHelpFormatter # Keep formatting in help
        )
    parser.add_argument("input_file", nargs='?', # Make optional if --list-voices is used
                        help="Path to the input EPUB or PDF file.")
    parser.add_argument("-o", "--output",
                        help="Path for the final output MP3 file.\n"
                             f"(Default: Creates file in '{OUTPUT_DIR}' based on input name)")
    parser.add_argument("-v", "--voice", default=DEFAULT_VOICE,
                        help=f"Voice to use for TTS (e.g., 'en-GB-SoniaNeural').\n"
                             f"Use --list-voices to see options. Default: {DEFAULT_VOICE}")
    parser.add_argument("--list-voices", action="store_true",
                        help="List available voices supported by edge-tts and exit.")
    parser.add_argument("--no-chunking", action="store_true",
                        help="Disable text chunking and merging. May fail for large files.")

    args = parser.parse_args()

    # Handle --list-voices separately
    if args.list_voices:
        await list_available_voices()
        sys.exit(0)

    # If --list-voices wasn't used, input_file is required
    if not args.input_file:
        parser.error("the following arguments are required: input_file (unless using --list-voices)")
        sys.exit(1) # Exit if no input file provided

    # Run the main file processing logic
    await process_file(
        args.input_file,
        args.output,
        args.voice,
        use_chunking=not args.no_chunking # Pass True for chunking unless --no-chunking is set
        )

if __name__ == "__main__":
    # Check Python version for asyncio support needed by edge-tts
    if sys.version_info < (3, 7):
        print("Error: This script requires Python 3.7 or later for asyncio features.", file=sys.stderr)
        sys.exit(1)

    # Run the main async function
    temp_dir_ref = None # Reference for cleanup in case of main exception
    try:
        # Assign temp_dir globally if possible for cleanup, though tricky with async structure
        # The finally block within process_file is the primary cleanup mechanism
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nConversion interrupted by user.", file=sys.stderr)
        # Note: Cleanup of temp_dir on interrupt is handled by process_file's finally block if it got that far
        sys.exit(1)
    except Exception as e:
        print(f"\nAn unexpected error occurred in main execution: {e}", file=sys.stderr)
        # Note: Cleanup of temp_dir on error is handled by process_file's finally block if it got that far
        sys.exit(1)

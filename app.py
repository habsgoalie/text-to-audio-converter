# app.py
import os
import uuid
import asyncio
import threading
import logging
from flask import Flask, request, render_template, jsonify, send_from_directory, url_for
from werkzeug.utils import secure_filename
from concurrent.futures import ThreadPoolExecutor

# Import the processor logic
import tts_processor

# --- Configuration ---
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'output_audio'
ALLOWED_EXTENSIONS = {'pdf', 'epub'}
MAX_CONTENT_LENGTH = 50 * 1024 * 1024 # 50 MB limit for uploads

# --- Predefined List of Common en-US Neural Voices ---
# Extracted from edge-tts list_voices() output
# Format: ('Display Name', 'ShortName')
EN_US_NEURAL_VOICES = [
    ('Aria', 'en-US-AriaNeural'),
    ('Jenny', 'en-US-JennyNeural'),
    ('Guy', 'en-US-GuyNeural'),
    ('Ana', 'en-US-AnaNeural'),
    ('Christopher', 'en-US-ChristopherNeural'),
    ('Eric', 'en-US-EricNeural'),
    ('Michelle', 'en-US-MichelleNeural'),
    ('Roger', 'en-US-RogerNeural'),
    ('Steffan', 'en-US-SteffanNeural'),
    ('Andrew', 'en-US-AndrewMultilingualNeural'),
    ('Brian', 'en-US-BrianMultilingualNeural'),
]
DEFAULT_VOICE_SHORTNAME = 'en-US-SteffanNeural' # Ensure this matches one in the list

# --- Setup Logging ---
# Configure logging for Flask app
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Flask App Setup ---
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.secret_key = os.urandom(24) # Needed for flashing messages potentially

# Create upload and output folders if they don't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# --- Background Task Management ---
# Using ThreadPoolExecutor to run asyncio code from sync Flask
executor = ThreadPoolExecutor(max_workers=2) # Limit concurrent conversions
tasks = {} # Dictionary to store task status: {task_id: {'status': '...', 'result': '...', 'filename': '...'}}

def allowed_file(filename):
    """Checks if the uploaded file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def run_conversion_in_background(task_id, input_path, output_path, voice):
    """Target function for the background thread."""
    logger.info(f"Background task {task_id}: Starting conversion for {input_path} with voice {voice}")
    tasks[task_id]['status'] = 'processing'
    tasks[task_id]['message'] = 'Starting conversion...'

    # --- This is the key part: run the async function within an event loop in this thread ---
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def update_status_sync(message):
        """ Safely update status from the async callback """
        # Avoid overwriting final messages
        if tasks[task_id]['status'] == 'processing':
             tasks[task_id]['message'] = message

    try:
        # Run the async process_file function until it completes
        result_path = loop.run_until_complete(
            tts_processor.process_file(
                input_path=input_path,
                final_output_path=output_path,
                voice=voice, # Pass the selected voice
                use_chunking=True, # Always use chunking for web app
                status_callback=update_status_sync # Pass the sync callback
            )
        )
        tasks[task_id]['status'] = 'complete'
        tasks[task_id]['result'] = result_path # Store the final output path
        tasks[task_id]['message'] = 'Conversion successful!'
        logger.info(f"Background task {task_id}: Conversion successful. Output: {result_path}")
    except Exception as e:
        logger.error(f"Background task {task_id}: Conversion failed - {e}", exc_info=True) # Log traceback
        tasks[task_id]['status'] = 'error'
        tasks[task_id]['result'] = str(e) # Store error message
        tasks[task_id]['message'] = f'Error: {e}'
    finally:
        loop.close()
        # Clean up the uploaded file after processing
        try:
            if os.path.exists(input_path):
                os.remove(input_path)
                logger.info(f"Background task {task_id}: Cleaned up uploaded file {input_path}")
        except OSError as e:
            logger.error(f"Background task {task_id}: Error cleaning up upload file {input_path}: {e}")
        logger.info(f"Background task {task_id}: Thread finished.")


# --- Flask Routes ---

@app.route('/', methods=['GET'])
def index():
    """Renders the main upload page, passing the voice list."""
    return render_template('index.html', voices=EN_US_NEURAL_VOICES, default_voice=DEFAULT_VOICE_SHORTNAME)

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handles file upload and starts the conversion task."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part in the request'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file and allowed_file(file.filename):
        # Sanitize filename
        original_filename = secure_filename(file.filename)
        # Create unique names for stored files
        unique_id = str(uuid.uuid4())
        input_filename = f"{unique_id}_{original_filename}"
        input_path = os.path.join(app.config['UPLOAD_FOLDER'], input_filename)

        # Construct output path based on original name but ensure uniqueness if needed
        output_basename = os.path.splitext(original_filename)[0]
        output_filename = f"{output_basename}_{unique_id[:8]}.mp3" # Add part of UUID for safety
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)

        try:
            file.save(input_path)
            logger.info(f"File uploaded and saved to: {input_path}")

            # Get selected voice from form data
            selected_voice = request.form.get('voice', DEFAULT_VOICE_SHORTNAME)
            # Validate if the selected voice is in our allowed list (optional but good practice)
            valid_voices = [v[1] for v in EN_US_NEURAL_VOICES]
            if selected_voice not in valid_voices:
                 logger.warning(f"Invalid voice '{selected_voice}' submitted, falling back to default.")
                 selected_voice = DEFAULT_VOICE_SHORTNAME

            logger.info(f"Selected voice: {selected_voice}")


            # Generate task ID and store initial status
            task_id = unique_id
            tasks[task_id] = {
                'status': 'queued',
                'result': None,
                'filename': output_filename, # Store the intended output filename
                'message': 'Waiting to start...'
                }
            logger.info(f"Task {task_id} created for {original_filename}")

            # Submit the conversion task to the thread pool with the selected voice
            executor.submit(run_conversion_in_background, task_id, input_path, output_path, selected_voice)
            logger.info(f"Task {task_id} submitted to background executor.")

            return jsonify({'task_id': task_id})

        except Exception as e:
            logger.error(f"Error during file upload or task submission: {e}", exc_info=True)
            # Clean up saved file if submission failed
            if os.path.exists(input_path):
                try: os.remove(input_path)
                except OSError: pass
            return jsonify({'error': f'An internal error occurred: {e}'}), 500

    else:
        return jsonify({'error': 'File type not allowed'}), 400

@app.route('/status/<task_id>', methods=['GET'])
def task_status(task_id):
    """Returns the status of a background task."""
    task = tasks.get(task_id)
    if not task:
        return jsonify({'status': 'error', 'message': 'Task not found'}), 404

    response = {'status': task['status'], 'message': task.get('message', '')}
    if task['status'] == 'complete':
        # Provide URL for download if complete
        response['download_url'] = url_for('download_file', task_id=task_id)
        response['filename'] = task.get('filename', 'output.mp3')
    elif task['status'] == 'error':
        response['error_details'] = task.get('result', 'Unknown error') # Send error details

    return jsonify(response)

@app.route('/download/<task_id>', methods=['GET'])
def download_file(task_id):
    """Serves the generated MP3 file for download."""
    task = tasks.get(task_id)
    if not task or task['status'] != 'complete':
        logger.warning(f"Download attempt for non-existent or incomplete task: {task_id}")
        return "Task not found or not complete.", 404

    output_filename = task.get('filename')
    if not output_filename:
         logger.error(f"Output filename missing for completed task: {task_id}")
         return "Error: Output filename not found.", 500

    try:
        logger.info(f"Serving file: {output_filename} from directory: {app.config['OUTPUT_FOLDER']}")
        # Use send_from_directory for security
        return send_from_directory(
            app.config['OUTPUT_FOLDER'],
            output_filename,
            as_attachment=True # Force download dialog
            )
    except FileNotFoundError:
        logger.error(f"Download failed: File not found at expected location - {output_filename}")
        return "Error: Output file not found.", 404
    except Exception as e:
        logger.error(f"Error during file download for task {task_id}: {e}", exc_info=True)
        return "Error serving file.", 500

# --- Main Execution ---
if __name__ == '__main__':
    # Check ffmpeg on startup
    if not tts_processor.check_and_set_ffmpeg_paths():
         logger.critical("FATAL: ffmpeg/ffprobe not found or configured correctly. The application may not function.")
         # Decide if you want to exit or just warn
         # sys.exit("Exiting due to missing ffmpeg/ffprobe.")

    # Consider using Waitress or Gunicorn instead of development server for production
    logger.info("Starting Flask development server...")
    app.run(debug=False, host='0.0.0.0', port=5000) # debug=False for background threads

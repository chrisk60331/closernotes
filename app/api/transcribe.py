"""Audio transcription API endpoints."""

from flask import Blueprint, request, jsonify, current_app

from app.services.transcription import TranscriptionService

transcribe_bp = Blueprint("transcribe", __name__)


@transcribe_bp.route("/transcribe", methods=["POST"])
def transcribe_audio():
    """Transcribe uploaded audio to text.

    Accepts audio file upload (multipart/form-data) or raw audio bytes.
    Supports wav, mp3, m4a, webm, ogg formats.

    Request:
        - File upload: multipart/form-data with 'audio' file field
        - Optional 'language' form field for language hint

    Returns:
        JSON response with transcription result:
        {
            "text": "Transcribed text...",
            "language": "en",
            "duration_seconds": 45.2,
            "segments": [
                {"start": 0.0, "end": 2.5, "text": "Hello..."}
            ]
        }
    """
    try:
        # Get audio from file upload
        if "audio" not in request.files:
            return jsonify({"error": "No audio file provided"}), 400

        audio_file = request.files["audio"]
        if audio_file.filename == "":
            return jsonify({"error": "Empty filename"}), 400

        # Read audio data
        audio_data = audio_file.read()
        if len(audio_data) == 0:
            return jsonify({"error": "Empty audio file"}), 400

        # Optional language hint
        language = request.form.get("language")

        # Transcribe
        service = TranscriptionService()
        result = service.transcribe_audio(
            audio_data,
            language=language,
            filename=audio_file.filename,
        )

        current_app.logger.info(
            f"Transcribed {result.duration_seconds:.1f}s of audio, "
            f"language={result.language}, text_length={len(result.text)}"
        )

        return jsonify(result.model_dump()), 200

    except Exception as e:
        current_app.logger.exception("Error transcribing audio")
        return jsonify({"error": f"Transcription failed: {str(e)}"}), 500


@transcribe_bp.route("/transcribe/status", methods=["GET"])
def transcribe_status():
    """Check if transcription service is available.

    Returns model info and availability status.
    """
    try:
        # Check if model can be loaded
        service = TranscriptionService()

        return jsonify({
            "available": True,
            "model_size": service._model_size,
            "model_loaded": service._model is not None,
        }), 200

    except Exception as e:
        return jsonify({
            "available": False,
            "error": str(e),
        }), 200

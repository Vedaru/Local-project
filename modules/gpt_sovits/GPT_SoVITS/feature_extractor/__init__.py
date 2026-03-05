from . import cnhubert

try:
    from . import whisper_enc
except ImportError:
    whisper_enc = None

content_module_map = {"cnhubert": cnhubert}
if whisper_enc is not None:
    content_module_map["whisper"] = whisper_enc

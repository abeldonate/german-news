from io import BytesIO

from gtts import gTTS


def build_tts_audio(text: str, lang: str) -> bytes:
    audio_buffer = BytesIO()
    tts = gTTS(text=text, lang=lang, slow=False)
    tts.write_to_fp(audio_buffer)
    audio_buffer.seek(0)
    return audio_buffer.read()
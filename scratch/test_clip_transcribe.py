import subprocess
import sys
sys.path.insert(0, ".")
from app.ai_modules.speech_to_text.whisper_analyzer import WhisperAnalyzer

analyzer = WhisperAnalyzer()
res = analyzer.analyze({'audio_path': 'scratch/clip_audio_test.wav', 'language': 'id'})

all_words = []
for s in res.result_data['segments']:
    for w in s['words']:
        word_text = w['word'].strip()
        if word_text:
            all_words.append({'word': word_text, 'start': w['start'], 'end': w['end']})

chunks = []
curr_chunk = []
for i, w in enumerate(all_words):
    curr_chunk.append(w)
    chunk_len = sum(len(cw['word']) for cw in curr_chunk) + len(curr_chunk) - 1
    is_last = (i == len(all_words) - 1)
    has_punct = w['word'].endswith(('.', '?', '!', '...', '…'))
    
    should_break = (
        has_punct
        or len(curr_chunk) >= 3
        or (len(curr_chunk) >= 2 and chunk_len >= 8)
        or is_last
    )
    if should_break:
        start = curr_chunk[0]['start']
        end = curr_chunk[-1]['end']
        text = ' '.join(cw['word'] for cw in curr_chunk).upper()
        chunks.append({'start': start, 'end': end, 'text': text})
        curr_chunk = []

# Clamp overlaps
for i in range(len(chunks) - 1):
    if chunks[i]['end'] > chunks[i+1]['start']:
        chunks[i]['end'] = max(chunks[i]['start'] + 0.1, chunks[i+1]['start'] - 0.02)

print(f"Total chunks: {len(chunks)}")
for c in chunks:
    dur = c['end'] - c['start']
    print(f"{c['start']:05.2f} - {c['end']:05.2f} (dur: {dur:.2f}s): {c['text']}")

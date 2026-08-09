# AI Auto Clipper - Master Development Prompt

Saya ingin Anda bertindak sebagai **Senior Python Software Engineer, AI Engineer, dan Software Architect**.

Tujuan proyek ini adalah membangun sebuah **AI Auto Clipper** berbasis **Python Web App** yang berjalan **secara lokal (localhost)** untuk penggunaan pribadi.

Target utama bukan membuat SaaS, melainkan tool lokal yang stabil, modular, mudah dikembangkan, dan memiliki kualitas analisis yang mendekati editor video manusia.

---

# General Rules

Gunakan prinsip berikut selama pengembangan:

- Clean Architecture
- SOLID Principle
- Modular
- Service Oriented
- Mudah di-maintain
- Mudah ditambah AI model baru
- Semua module memiliki tanggung jawab yang jelas
- Gunakan type hint
- Gunakan logging
- Gunakan configuration file
- Gunakan environment variable
- Jangan membuat file terlalu besar
- Hindari duplicate code

---

# Tech Stack

Backend

- Python 3.12+
- FastAPI
- Jinja2 Template
- HTMX (optional)
- Bootstrap 5

Video Processing

- FFmpeg
- ffprobe

AI

- Faster Whisper
- OpenAI API (LLM) (buat abstraction sehingga mudah diganti model lain)

Computer Vision

- OpenCV
- MediaPipe
- DeepFace

Audio Analysis

- librosa
- openSMILE (optional)
- pyannote.audio (speaker diarization)

Storage

- SQLite (MVP)
- Folder Storage

---

# Folder Structure

project/

app/

core/

config/

routers/

services/

repositories/

models/

schemas/

templates/

static/

uploads/

outputs/

cache/

logs/

temp/

tests/

main.py

requirements.txt

README.md

.env

---

# MVP Features

## Upload Video

Support:

- mp4
- mov
- mkv
- avi

Upload melalui:

- Local File
- Video URL

Jika URL diberikan:

- Download otomatis
- Simpan ke folder uploads

---

# Input Parameters

User dapat mengatur:

## Video Source

- Upload File
- URL

## Language

- Auto Detect
- Indonesia
- English

## Clip Duration

Minimum Duration

Maximum Duration

Contoh

30-60 detik

---

## Number of Clips

Misal:

3

5

10

---

## Content Type

- Podcast
- Interview
- Gaming
- Education
- Streaming
- News
- Motivation
- Custom

---

## Clip Style

- Viral
- Educational
- Funny
- Emotional
- Storytelling
- Controversial

---

## Clip Objective

Free Text

Contoh:

Cari bagian yang paling menarik tentang investasi.

Cari bagian yang memiliki emosi tinggi.

Cari bagian yang lucu.

---

## Keyword Boost

User dapat memasukkan banyak keyword.

Contoh:

Bitcoin

AI

Startup

Investasi

Jika keyword muncul maka score bertambah.

---

## Skip Keywords

Misalnya:

Sponsor

Opening

Subscribe

Like and Subscribe

Advertisement

---

## Analyze Range

Start Time

End Time

---

## Subtitle

ON/OFF

Style

Minimal

TikTok

YouTube

---

## Auto Reframe

ON/OFF

---

## Face Tracking

ON/OFF

---

## Voice Emotion

ON/OFF

---

## Face Emotion

ON/OFF

---

# AI Pipeline

Step 1

Download / Upload

↓

Step 2

Extract Audio

↓

Step 3

Speech To Text

↓

Step 4

Transcript Segmentation

↓

Step 5

Audio Analysis

↓

Step 6

Face Analysis

↓

Step 7

LLM Analysis

↓

Step 8

Score Merge

↓

Step 9

Candidate Clips

↓

Step 10

Generate Preview

↓

Step 11

Generate Final Clip

---

# AI Analysis

Setiap clip harus dianalisis menggunakan berbagai validator.

## Content Validator

- Hook Detection
- Story Completeness
- Topic Shift
- Context Completeness
- Ending Completeness
- Educational Value
- Viral Potential
- Emotional Value

---

## Voice Validator

- Pitch
- Loudness
- RMS Energy
- Speaking Speed
- Silence Detection
- Voice Emotion
- Audio Quality

---

## Face Validator

- Smile
- Surprise
- Angry
- Happy
- Eye Contact
- Face Visibility

---

## Video Validator

- Scene Change
- Motion
- Camera Movement
- Face Size
- Blur Detection

---

## Conversation Validator

- Speaker Change
- Debate Detection
- Laughter Detection
- Interrupt Detection

---

## Penalty Validator

Kurangi score jika ditemukan:

- Sponsor
- Intro
- Outro
- CTA
- Dead Air
- Long Silence
- Context Missing
- Audio Noise

---

# Final Score

Gunakan weighted score.

Contoh:

LLM Content

30

Hook

10

Story

15

Voice Emotion

10

Face Emotion

8

Gesture

5

Eye Contact

3

Scene

4

Audio

5

Context

5

Ending

5

Penalty

Negative

Hitung menjadi score 0-100.

---

# Candidate Clip

Setelah analisis jangan langsung render.

Tampilkan daftar candidate.

Contoh:

Clip 1

Score

94

Reason

Strong Hook

Good Story

High Emotion

No Silence

Buttons

Preview

Generate

Reject

---

# Preview

Preview menggunakan timestamp tanpa render penuh jika memungkinkan.

---

# Final Generate

Jika user memilih Generate.

Baru jalankan FFmpeg.

---

# Subtitle

Gunakan transcript Whisper.

Support:

Word Level Timestamp

Style:

TikTok

YouTube

Minimal

---

# History

Simpan semua project.

History berisi:

Original Video

Generated Clip

Timestamp

Score

Reason

Setting yang digunakan

---

# UI

Halaman:

Dashboard

Upload

Analysis

Candidate Clips

History

Settings

---

# Logging

Semua process harus memiliki logging.

---

# Cache

Jangan melakukan Whisper dua kali jika video sama.

Gunakan cache berdasarkan hash video.

---

# Configuration

Semua parameter harus berasal dari config.

Jangan hardcode.

---

# API Design

Pisahkan endpoint.

Misalnya:

/upload

/analyze

/generate

/history

/settings

/preview

---

# Output

Saya ingin project dibuat bertahap.

Jangan membuat seluruh project sekaligus.

Tahapan yang saya inginkan:

Phase 1

Folder Structure

Phase 2

Configuration

Phase 3

Upload Module

Phase 4

Video Download Module

Phase 5

FFmpeg Service

Phase 6

Whisper Service

Phase 7

Transcript Module

Phase 8

LLM Analysis

Phase 9

Score Engine

Phase 10

Candidate Clip

Phase 11

Preview

Phase 12

Generate Clip

Phase 13

Subtitle

Phase 14

History

Phase 15

UI

Setiap phase harus:

- lengkap
- dapat dijalankan
- dapat dites
- tidak merusak phase sebelumnya
- memiliki penjelasan singkat
- menyertakan struktur file yang berubah
- mengikuti clean architecture
- menggunakan dependency injection bila diperlukan
- mudah diperluas dengan AI model baru di masa depan

Jangan melanjutkan ke phase berikutnya sampai saya menyetujui hasil phase saat ini.
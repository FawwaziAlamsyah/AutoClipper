# Additional Requirement - Observability, Logging, Analysis Report & Debug System

Tambahkan modul baru bernama **Observability System**.

Saya ingin seluruh proses AI dapat dipantau secara realtime baik oleh user maupun developer.

Project ini akan terus dikembangkan sehingga seluruh proses harus mudah di-debug.

---

# Progress Tracker

Pada halaman web tampilkan progress realtime.

Contoh:

✓ Upload Video

✓ Download Video

✓ Extract Audio

✓ Extract Frames

✓ Speech To Text

✓ Transcript Segmentation

✓ Face Detection

✓ Face Emotion Analysis

✓ Voice Analysis

✓ Speaker Detection

✓ Keyword Analysis

✓ Hook Detection

✓ Story Detection

✓ LLM Analysis

✓ Score Engine

✓ Candidate Clip Generation

✓ Subtitle Generation

✓ Preview Generation

✓ Final Render

✓ Finished

Setiap proses harus menampilkan:

- Status
- Persentase
- Waktu Mulai
- Waktu Selesai
- Durasi

Contoh:

Speech To Text

Status:
Running

Progress:
63%

Elapsed:
00:01:23

---

# Real Time Console

Tambahkan halaman Console.

Console menampilkan log seperti terminal.

Contoh:

[09:12:11]

INFO

Loading Whisper Model

----------------------

[09:12:20]

INFO

Transcript Started

----------------------

[09:13:55]

SUCCESS

Transcript Finished

Duration

95 seconds

----------------------

[09:14:01]

INFO

LLM Started

----------------------

[09:14:22]

SUCCESS

Candidate Clip Found

Score

93

Reason

Strong Hook

---

# Logging System

Gunakan Python logging.

Pisahkan level:

DEBUG

INFO

WARNING

ERROR

CRITICAL

Gunakan RotatingFileHandler.

Folder:

logs/

Contoh file:

app.log

analysis.log

error.log

performance.log

---

# Analysis Report

Setelah proses selesai buat folder project.

Misalnya:

history/

2026-08-07_093001/

Di dalamnya simpan:

original.mp4

analysis.json

transcript.json

segments.json

candidate.json

score.json

setting.json

performance.json

subtitle.srt

clip_1.mp4

clip_2.mp4

preview.mp4

---

# analysis.json

Berisi:

Video Information

Duration

FPS

Resolution

Language

Transcript

Speaker

Emotion

Keyword

Topic

Hook

LLM Result

Semua validator

Semua score

Reason

Confidence

Penalty

Timestamp

---

# score.json

Berisi seluruh score.

Contoh:

{

"clip_1":{

"hook":10,

"story":15,

"voice":9,

"emotion":8,

"context":10,

"ending":5,

"penalty":0,

"total":94

}

}

---

# transcript.json

Berisi transcript lengkap.

Setiap kata memiliki:

Start

End

Word

Speaker

Confidence

---

# performance.json

Catat performa setiap proses.

Contoh:

Upload

2 sec

Whisper

91 sec

LLM

18 sec

OpenCV

12 sec

DeepFace

15 sec

FFmpeg

26 sec

Total

164 sec

---

# Cache System

Jika video pernah dianalisis:

Jangan ulangi:

Whisper

Face Detection

Frame Extraction

Gunakan cache.

Cache berdasarkan SHA256 video.

---

# Error Recovery

Jika proses gagal.

Misalnya:

DeepFace Error

Maka:

Jangan hentikan seluruh pipeline.

Skip module tersebut.

Lanjutkan proses berikutnya.

Semua error dicatat.

---

# Analysis Dashboard

Tambahkan halaman Analysis.

Berisi:

Ringkasan Video

Jumlah Clip

Processing Time

Candidate Clip

Average Score

Highest Score

Lowest Score

Keyword yang ditemukan

Emotion Distribution

Speaker Distribution

Silence Timeline

Hook Timeline

Penalty Timeline

---

# Candidate Detail

Saat user klik Candidate.

Tampilkan:

Preview

Reason

Hook

Story

Voice

Emotion

Keyword

Penalty

Confidence

Timeline

---

# Final Report

Setelah selesai.

Generate report HTML.

Contoh:

Project Name

Video Information

Pipeline Summary

Timeline

Candidate Clip

Score Breakdown

Performance

Logs

Final Output

User dapat membuka report tersebut di browser.

---

# Debug Mode

Tambahkan switch.

Mode:

Production

Debug

Jika Debug aktif.

Tampilkan:

Memory Usage

CPU Usage

GPU Usage

Frame Processing Speed

Whisper Speed

LLM Token Usage

OpenCV FPS

DeepFace FPS

Queue Size

Cache Hit

Cache Miss

---

# Monitoring

Tambahkan halaman Monitoring.

Berisi realtime:

Current Task

Running Module

Elapsed Time

Estimated Remaining Time

CPU

RAM

GPU

Progress

Current Frame

Current Segment

---

# Developer Requirement

Semua service wajib memiliki logging.

Gunakan decorator atau middleware untuk otomatis mencatat:

Nama Function

Parameter

Execution Time

Success / Failed

Exception

Return Value Summary

---

# Code Requirement

Jangan menggunakan print() untuk debugging.

Gunakan logging.

Semua module harus memiliki logger sendiri.

Seluruh exception harus memiliki stack trace yang jelas.

Semua hasil analisis harus dapat direproduksi dari file JSON yang disimpan.

Pastikan sistem observability ini bersifat modular sehingga mudah ditambah validator atau AI model baru tanpa mengubah struktur logging yang sudah ada.
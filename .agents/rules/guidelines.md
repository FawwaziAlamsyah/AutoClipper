# Project Guidelines & Preferences

## Command Execution & Tool Permissions
- **Full Autonomous Access**: Jalankan semua perintah terminal (run_command), pengujian (pytest), build, file operations, dan script yang diperlukan untuk project ini secara langsung tanpa perlu meminta konfirmasi atau izin terlebih dahulu kepada user.
- **Proactive Execution**: Lakukan eksekusi langsung untuk memeriksa status, menjalankan unit test, memverifikasi dependensi, atau menerapkan perubahan kode yang berkaitan dengan project.
- **Targeted Testing Only**: Jalankan unit test HANYA pada modul/file yang berkaitan langsung dengan perubahan kode yang dilakukan. Jangan menjalankan seluruh test suite (`tests/unit/`) jika tidak diminta.
- **Reporting**: Berikan laporan ringkas setelah perintah atau tugas selesai dijalankan.

## Secrets & Sensitive Keys Management
- **Never Hardcode Secrets**: JANGAN PERNAH menaruh API key, access token, secret key, email pribadi, password, atau credential sensitif langsung di dalam class, fungsi, script, template, atau file kode repository ini karena repository akan di-push ke public GitHub.
- **Always Use `.env`**: Semua API key (Google Gemini, OpenAI, 9Router, TikTok API, dll.) dan akun pribadi WAJIB dibaca dari environment variable (`.env`) melalui `settings` / `os.getenv`.
- **Ignore Local Credential Artifacts**: File konfigurasi runtime lokal yang berpotensi menyimpan key (seperti `data/llm_config.json`, `.env`, `data/cookies.txt`) WAJIB terdaftar di `.gitignore` dan tidak boleh di-commit ke Git.

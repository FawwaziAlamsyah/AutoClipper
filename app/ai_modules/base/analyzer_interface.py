"""AnalyzerInterface — kontrak semua AI module plugin.

Setiap analyzer (face, voice, gesture, scene, llm, whisper, dst) mewarisi
interface ini dan didaftarkan ke registry. Pipeline memanggil analyzer lewat
registry, sehingga model AI bisa diganti tanpa mengubah orchestration.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AnalysisResult:
    """Output standar sebuah analyzer.

    score: nilai 0-10.
    result_data: kan DATA di analysis_results.result_data (JSONB).
    """

    score: float
    result_data: dict[str, Any] = field(default_factory=dict)


class AnalyzerUnavailable(Exception):
    """Raise saat analyzer tidak bisa dijalankan (dependency/video tak ada, dst).

    Caller menangkap exception ini dan melewati analyzer (tidak menulis
    analysis_results) daripada menggagalkan pipeline.
    """


class AnalyzerInterface(ABC):
    """Kontrak minimum yang harus dipenuhi semua analyzer."""

    analyzer_type: str = ""

    @abstractmethod
    def analyze(self, input: Any) -> AnalysisResult:
        """Analisis satu input dan kembali score + data pendukung.

        Beda analyzer terima input yang berbeda (video_path, audio_path,
        transcript text) — makanya input ber-typed Any. Yang disimpan
        di analysis_results hanya analyzer_type, score, result_data.
        Raise AnalyzerUnavailable kalau tidak bisa dijalankan.
        """
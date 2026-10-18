"""Score engine: aggregate analyzer scores into weighted final score."""

import logging
from pathlib import Path

from app.core.config.settings import settings
from app.core.config.score_blend import get_fallback_weight, get_trained_weight
from app.ml.predictor import predict_score
from app.models.candidate_model import CandidateModel
from app.models.clip_model import ClipModel
from app.repositories.analysis_result_repository import AnalysisResultRepository
from app.repositories.candidate_repository import CandidateRepository
from app.repositories.job_repository import JobRepository
from app.repositories.video_repository import VideoRepository

logger = logging.getLogger(__name__)


class ScoreEngine:
    """Aggregate and weight scores from various analyzers."""

    def __init__(self, db):
        """Initialize with DB session and repos."""
        self.db = db
        self.video_repo = VideoRepository(db)
        self.job_repo = JobRepository(db)
        self.analysis_repo = AnalysisResultRepository(db)
        self.candidate_repo = CandidateRepository(db)

    def calculate_for_job(self, job_id: int) -> float:
        """Calculate weighted score for all candidates in a job.

        Weights (prioritas retensi algoritma viral >= 200k views, configurable via settings):
        - Hook: 25% (detik 0-3 stop-scroll rate)
        - LLM Content: 22% (curiosity gap, humor, argumen menarik)
        - Voice Emotion: 18% (dinamika energi nada & reaksi vokal)
        - Gesture: 10% (gerakan tangan dinamis)
        - Face Emotion: 7% (ekspresi wajah / senyum)
        - Ending: 6% (punchline & kesimpulan)
        - Story: 5% (alur narasi)
        - Eye Contact: 2%
        - Scene: 2%
        - Audio: 1%
        - Context: 1%
        - Viral Potential: 1%
        """
        job = self.job_repo.get(job_id)
        if job is None:
            raise ValueError(f"Job {job_id} not found")

        candidates = self.candidate_repo.get_by_job(job_id)
        if not candidates:
            logger.warning("No candidates found for job %d", job_id)
            return 0.0

        for candidate in candidates:
            breakdown = self._calculate_score_breakdown(job_id, candidate, job.category_id)
            meta = breakdown.get("_meta", {})
            weighted = meta.get("legacy_weighted_sum_score", 0.0)
            trained = meta.get("model_predicted_score")
            gk_mult = meta.get("gatekeeper_multiplier", 1.0)
            # Kiblat = bobot (0.8). Trained model hanya koreksi tipis (0.2) bila ada.
            # Bobot SELALU menentukan final score — trained tidak pernah ganti total.
            if trained is not None:
                # Kategori sudah dilatih → campur sesuai preferensi user
                # (default: trained 0.8, fallback 0.2). Tunable via Settings.
                tw = get_trained_weight()
                fw = get_fallback_weight()
                total = tw + fw
                if total <= 0:
                    tw, fw = 0.8, 0.2
                else:
                    tw, fw = tw / total, fw / total
                raw_blend = tw * trained + fw * meta.get("raw_weighted_sum_score", weighted)
                final_score = round(raw_blend * gk_mult, 2)
            else:
                final_score = weighted
            breakdown.setdefault("_meta", {})["final_score"] = final_score
            candidate.final_score = final_score
            candidate.score_breakdown = breakdown

        self.db.commit()
        return candidates[0].final_score if candidates else 0.0

    def select_top_n(self, job_id: int, n: int) -> list:
        """Simpan top-n candidate dengan final_score tertinggi, TANPA overlap satu
        sama lain (non-max suppression berbasis waktu), hapus sisanya.

        Window yang overlap satu sama lain (hasil sliding window) bisa punya
        konten nyaris sama — suppression memastikan top-N adalah momen berbeda.
        Window yang tidak lolos top-N langsung dihapus — label training hanya
        dari aksi manual user (Like / Tandai Jelek), bukan otomatis.
        Return selected (sorted desc).
        """
        candidates = self.candidate_repo.get_by_job(job_id)
        if not candidates:
            return []

        # Tolak candidate di bawah MIN_CANDIDATE_SCORE — mencegah clip sampah
        # lolos murni karena relatif tertinggi (tanpa threshold, top-N diambil
        # dari skor berapapun, meski semua rendah).
        min_score = settings.MIN_CANDIDATE_SCORE
        below = sum(1 for c in candidates if (c.final_score or 0.0) < min_score)
        ranked = sorted(
            (c for c in candidates if (c.final_score or 0.0) >= min_score),
            key=lambda c: c.final_score or 0.0,
            reverse=True,
        )

        selected: list = []
        for cand in ranked:
            overlaps = any(
                cand.start_time < kept.end_time and cand.end_time > kept.start_time
                for kept in selected
            )
            if not overlaps:
                selected.append(cand)
            if len(selected) >= n:
                break

        # Semua yang tidak lolos top-N langsung dihapus.
        # Tidak ada auto-harvest — label training hanya dari aksi manual user.
        drop_ids = [c.id for c in candidates if c not in selected]
        if drop_ids:
            self.db.query(ClipModel).filter(ClipModel.candidate_id.in_(drop_ids)).delete(synchronize_session=False)
            self.db.query(CandidateModel).filter(CandidateModel.id.in_(drop_ids)).delete(synchronize_session=False)

        self.db.commit()
        logger.info(
            "Job %d: %d selected, %d dihapus (%d di bawah min_score=%.1f)",
            job_id, len(selected), len(drop_ids), below, min_score,
        )
        return selected

    def _calculate_score_breakdown(
        self, job_id: int, candidate, category_id: int | None = None
    ) -> dict[str, dict]:
        """Calculate weighted score components for a candidate.

        Setiap analyzer jadi dict: {score, weight, contribution, reason}.
        Analyzer dengan bobot 0 dilewati. Analyzer yang TIDAK PERNAH menghasilkan
        result di seluruh job dianggap tidak aktif — bobotnya di-exclude.

        PENTING: analysis difilter per window candidate (start_time range) —
        bukan rata-rata seluruh job. Tanpa filter ini, semua candidate dapat skor
        identik (rata-rata global) — persis bug skor seragam.
        """
        analysis = self.analysis_repo.get_by_job(job_id)

        # Analyzer yang sama sekali tidak punya result di seluruh job ini dianggap
        # tidak aktif untuk job ini — bobotnya di-exclude, bukan 0.5 ke semua window.
        active_types = {a.analyzer_type for a in analysis}

        weights = {
            "llm_content": settings.SCORE_WEIGHT_LLM_CONTENT,
            "hook": settings.SCORE_WEIGHT_HOOK,
            "story": settings.SCORE_WEIGHT_STORY,
            "voice_emotion": settings.SCORE_WEIGHT_VOICE_EMOTION,
            "face_emotion": settings.SCORE_WEIGHT_FACE_EMOTION,
            "gesture": settings.SCORE_WEIGHT_GESTURE,
            "eye_contact": settings.SCORE_WEIGHT_EYE_CONTACT,
            "scene": settings.SCORE_WEIGHT_SCENE,
            "audio": settings.SCORE_WEIGHT_AUDIO,
            "context": settings.SCORE_WEIGHT_CONTEXT,
            "ending": settings.SCORE_WEIGHT_ENDING,
            "viral_potential": settings.SCORE_WEIGHT_VIRAL_POTENTIAL,
        }

        # Filter analysis ke window candidate ini saja (overlap check).
        cand_analysis = [
            a for a in analysis
            if (a.start_time is None or a.start_time < candidate.end_time)
            and (a.end_time is None or a.end_time > candidate.start_time)
        ]

        breakdown = {}
        for analyzer_type, weight in weights.items():
            if weight <= 0 or analyzer_type not in active_types:
                continue
            score = self._get_analyzer_score(cand_analysis, analyzer_type)
            breakdown[analyzer_type] = {
                "score": score,
                "weight": weight,
                "contribution": round(score * weight, 2),
                "reason": self._get_reason(cand_analysis, analyzer_type),
            }

        # Penalty for skip keywords and slow start / dead-air
        penalty = self._calculate_penalty(cand_analysis)
        if penalty > 0:
            reasons = []
            slow_reason = self._get_reason(cand_analysis, "slow_start")
            if slow_reason:
                reasons.append(slow_reason)
            pen_reason = self._get_reason(cand_analysis, "penalty")
            if pen_reason:
                reasons.append(pen_reason)
            penalty_reason = ", ".join(reasons) if reasons else "Konten spam/CTA/slow-start terdeteksi"
            breakdown["penalty"] = {
                "score": penalty,
                "weight": 0.0,
                "contribution": round(-abs(penalty), 2),
                "reason": penalty_reason,
            }

        # Weighted-sum legacy score (selalu dihitung — dipakai sebagai fallback
        # DAN sebagai pembanding transparansi di breakdown)
        raw_weighted = sum(v["contribution"] for v in breakdown.values())

        # Hook Gatekeeper Multiplier (Detik 0-3 Kill-Switch):
        # Jika hook lemah (< 4.0), video terbukti rontok di algoritma TikTok/Reels (< 200k views).
        # Multiplier memangkas skor agar klip dengan pembuka datar tidak bisa lolos ke Top Rank.
        hook_score = breakdown.get("hook", {}).get("score") if "hook" in breakdown else None
        gatekeeper_multiplier, gatekeeper_reason = self._calculate_hook_gatekeeper(hook_score)
        legacy_score = round(raw_weighted * gatekeeper_multiplier, 2)

        # Model terlatih — coba prediksi, None jika model belum ada atau gagal
        model_score = None
        fallback_reason = None
        if settings.USE_TRAINED_SCORE_MODEL:
            model_score = predict_score(cand_analysis, category_id)
            if model_score is None:
                if category_id is None:
                    fallback_reason = "tidak ada category_id (model per-kategori tidak bisa dipilih)"
                else:
                    path = Path(f"data/models/category_{category_id}/score_model.pkl")
                    if not path.exists():
                        fallback_reason = f"model kategori {category_id} belum dilatih"
                    else:
                        fallback_reason = f"prediksi model kategori {category_id} gagal"

        breakdown["_meta"] = {
            "scoring_method": "trained_model" if model_score is not None else "weighted_sum",
            "raw_weighted_sum_score": round(raw_weighted, 2),
            "gatekeeper_multiplier": gatekeeper_multiplier,
            "gatekeeper_reason": gatekeeper_reason,
            "legacy_weighted_sum_score": round(legacy_score, 2),
            "model_predicted_score": round(model_score, 2) if model_score is not None else None,
            "trained_model_used": model_score is not None,
            "fallback_reason": fallback_reason,
        }

        return breakdown

    def _calculate_hook_gatekeeper(self, hook_score: float | None) -> tuple[float, str]:
        """Hitung Gatekeeper Multiplier berdasarkan skor hook (detik 0-3).

        Target retensi media sosial >= 200k views:
        - hook >= HIGH_THRESHOLD (default 6.0): Hook kuat/potensial -> Multiplier = 1.0x (Lolos)
        - LOW_THRESHOLD <= hook < HIGH_THRESHOLD: Hook moderat -> Multiplier = MID_MULTIPLIER (0.85x)
        - hook < LOW_THRESHOLD (default 4.0): Hook lemah -> Multiplier = LOW_MULTIPLIER (0.60x)
        """
        if hook_score is None:
            return 1.0, "Hook analyzer tidak aktif (multiplier netral 1.0x)"

        high_th = getattr(settings, "HOOK_GATEKEEPER_HIGH_THRESHOLD", 6.0)
        low_th = getattr(settings, "HOOK_GATEKEEPER_LOW_THRESHOLD", 4.0)
        mid_mult = getattr(settings, "HOOK_GATEKEEPER_MID_MULTIPLIER", 0.85)
        low_mult = getattr(settings, "HOOK_GATEKEEPER_LOW_MULTIPLIER", 0.60)

        if hook_score >= high_th:
            return 1.0, f"Hook kuat ({hook_score:.1f}/10) — Lolos Gatekeeper 1.0x"
        elif hook_score >= low_th:
            return mid_mult, f"Hook moderat ({hook_score:.1f}/10) — Gatekeeper Multiplier {mid_mult:.2f}x"
        else:
            return low_mult, f"Hook lemah ({hook_score:.1f}/10) — Gatekeeper Penalty {low_mult:.2f}x"

    def _get_reason(self, analysis: list, analyzer_type: str) -> str:
        """Ambil reason dari result_data analysis terakhir untuk analyzer type."""
        reason = ""
        for a in analysis:
            if a.analyzer_type == analyzer_type and a.result_data:
                reason = a.result_data.get("reason", "")
        return reason

    def _get_analyzer_score(self, analysis: list, analyzer_type: str) -> float:
        """Extract average score from analyzer results (per-window, sudah di-filter)."""
        results = [a for a in analysis if a.analyzer_type == analyzer_type]
        if not results:
            return 5.0  # Default neutral score (skala 0-10)

        return sum(r.score or 0 for r in results) / len(results)

    def _calculate_penalty(self, analysis: list) -> float:
        """Calculate penalty for skip keywords, dead-air, and slow-pacing intro."""
        penalties = {
            "sponsor": 0.5,
            "intro": 0.5,
            "outro": 0.5,
            "cta": 0.3,
            "dead air": 0.2,
            "silence": 0.2,
        }

        total_penalty = 0.0
        for a in analysis:
            # 1. Analyzer bertipe penalty atau slow_start dengan skor negatif
            if a.analyzer_type in ("penalty", "slow_start") and a.score is not None and a.score < 0:
                total_penalty += abs(a.score)

            # 2. Keyword eksplisit di result_data
            result_data = a.result_data or {}
            if "keyword" in result_data:
                for kw, val in penalties.items():
                    if kw in result_data["keyword"].lower():
                        total_penalty += val

        return total_penalty

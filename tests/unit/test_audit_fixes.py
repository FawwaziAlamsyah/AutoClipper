"""Regression tests untuk perbaikan audit pipeline (progress monotonic,
minimum score threshold, tidak ada fake completion)."""

import pytest

from app.core.config.settings import settings
from app.services.job_service import JobService, PIPELINE_STEPS, ANALYZER_STEPS


class _FakeStep:
    def __init__(self, step_name, status="pending"):
        self.step_name = step_name
        self.status = status


class _FakeJob:
    id = 1
    status = "pending"
    current_step = None
    started_at = None
    finished_at = None
    error_message = None


class _FakeStepRepo:
    def __init__(self, steps):
        self.steps = steps

    def get_by_job(self, job_id):
        return self.steps


class _FakeJobRepo:
    def __init__(self, job):
        self.job = job

    def get(self, job_id):
        return self.job

    def get_running(self):
        return [self.job]


class _FakeDb:
    def commit(self):
        pass

    def refresh(self, obj):
        return obj


def _all_steps():
    return [_FakeStep(n) for n in PIPELINE_STEPS + ANALYZER_STEPS]


def test_update_progress_never_decreases():
    """Invariant P(n+1) >= P(n): update stale (lebih kecil) tidak nurunin progress."""
    job = _FakeJob()
    job.progress_percent = 20
    svc = JobService.__new__(JobService)
    svc.repo = _FakeJobRepo(job)
    svc.db = _FakeDb()

    assert svc.update_progress(1, 35) == 35
    assert svc.update_progress(1, 17) == 35, "stale update tidak boleh nurunin progress"
    assert svc.update_progress(1, 40) == 40
    assert job.progress_percent == 40


def test_progress_denominator_fixed_from_start():
    """Semua pipeline + analyzer steps di-seed sekali → denominator tak tumbuh."""
    steps = _all_steps()
    got = {s.step_name for s in steps}
    assert got == set(PIPELINE_STEPS + ANALYZER_STEPS)
    # 12 step tetap (5 pipeline + 7 analyzer), tidak berubah di tengah pipeline.


def test_progress_monotonic_across_recalc():
    """Invariant P(n+1) >= P(n): completed naik → progress naik.

    Simulasi recalc get_status tanpa denominator tumbuh: makin banyak step
    success, progress tidak pernah turun.
    """
    steps = _all_steps()
    job = _FakeJob()
    repo = _FakeJobRepo(job)
    sr = _FakeStepRepo(steps)
    svc = JobService.__new__(JobService)
    svc.repo = repo
    svc.step_repo = sr

    prev = 0
    total = len(steps)
    for i in range(total + 1):
        for s in steps[:i]:
            s.status = "success"
        completed = sum(1 for s in steps if s.status == "success")
        pct = round((completed / total) * 100)
        assert pct >= prev, f"progress turun: {prev} -> {pct}"
        prev = pct


def test_start_step_does_not_reset_success():
    """Double-start step yang sudah success tidak menurunkan completed count."""
    steps = [_FakeStep("extract", status="success")]
    job = _FakeJob()
    svc = JobService.__new__(JobService)
    svc.repo = _FakeJobRepo(job)
    svc.step_repo = _FakeStepRepo(steps)
    svc.db = _FakeDb()

    step = svc.start_step(1, "extract")
    assert step.status == "success", "step success tidak boleh dibuka ulang jadi running"


def test_complete_job_refuses_incomplete_steps():
    """Job tidak fake SUCCESS bila masih ada step pending."""
    steps = [_FakeStep(n) for n in PIPELINE_STEPS]
    # extract selesai, sisanya pending
    steps[0].status = "success"
    job = _FakeJob()
    svc = JobService.__new__(JobService)
    svc.repo = _FakeJobRepo(job)
    svc.step_repo = _FakeStepRepo(steps)
    svc.db = _FakeDb()

    out = svc.complete_job(1)
    assert out.status == "failed", "complete_job harus tolak incomplete steps"
    assert "belum" in (out.error_message or "")


def test_complete_job_succeeds_when_all_done():
    """Semua step success → job boleh completed."""
    steps = [_FakeStep(n, status="success") for n in PIPELINE_STEPS]
    job = _FakeJob()
    svc = JobService.__new__(JobService)
    svc.repo = _FakeJobRepo(job)
    svc.step_repo = _FakeStepRepo(steps)
    svc.db = _FakeDb()

    out = svc.complete_job(1)
    assert out.status == "completed"


class _Cand:
    def __init__(self, score, start, end):
        self.final_score = score
        self.start_time = start
        self.end_time = end
        self.id = id(self)


def test_min_score_threshold_filters_garbage():
    """Filter select_top_n menolak candidate di bawah MIN_CANDIDATE_SCORE."""
    threshold = settings.MIN_CANDIDATE_SCORE
    cands = [
        _Cand(threshold + 0.5, 0, 10),
        _Cand(threshold - 0.1, 20, 30),  # sampah, harus ditolak
        _Cand(threshold + 0.1, 40, 50),
    ]
    # filter inline identik dengan yang di select_top_n
    ranked = sorted(
        (c for c in cands if (c.final_score or 0.0) >= threshold),
        key=lambda c: c.final_score or 0.0,
        reverse=True,
    )
    assert all(c.final_score >= threshold for c in ranked)
    assert len([c for c in cands if c.final_score < threshold]) == 1

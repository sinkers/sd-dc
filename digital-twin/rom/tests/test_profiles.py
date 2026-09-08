"""The auto-mode training-run generator."""

import numpy as np
import pytest

from dthall.profiles import PHASES, ProfileConfig, TrainingRunProfile


def drive(profile, seconds, dt=0.5):
    return [profile.advance(dt) for _ in range(int(seconds / dt))]


def test_same_seed_gives_an_identical_run():
    a = drive(TrainingRunProfile(16, seed=7), 900.0)
    b = drive(TrainingRunProfile(16, seed=7), 900.0)
    assert [s.phase for s in a] == [s.phase for s in b]
    assert np.allclose([s.mean_utilisation for s in a], [s.mean_utilisation for s in b])


def test_different_seeds_give_different_runs():
    a = drive(TrainingRunProfile(16, seed=1), 900.0)
    b = drive(TrainingRunProfile(16, seed=2), 900.0)
    assert not np.allclose(
        [s.mean_utilisation for s in a], [s.mean_utilisation for s in b]
    )


def test_utilisation_stays_in_bounds():
    samples = drive(TrainingRunProfile(16, seed=3), 3600.0)
    u = np.concatenate([s.utilisation for s in samples])
    cfg = ProfileConfig()
    assert u.min() >= cfg.idle_util - 1e-9
    assert u.max() <= 1.0 + 1e-9
    assert np.all(np.isfinite(u))


def test_it_ramps_before_it_grinds():
    profile = TrainingRunProfile(16, seed=4)
    samples = drive(profile, 200.0)
    assert samples[0].phase == "ramp"
    assert samples[0].mean_utilisation < 0.3
    assert samples[-1].phase == "sustained"
    assert samples[-1].mean_utilisation > 0.85


def test_ramp_is_staggered_across_racks():
    """Ranks do not all come up on the same tick."""
    profile = TrainingRunProfile(16, seed=5)
    samples = drive(profile, 30.0)
    mid = samples[len(samples) // 2]
    assert mid.utilisation.std() > 0.01


def test_checkpoints_and_evals_both_occur():
    profile = TrainingRunProfile(16, seed=6)
    samples = drive(profile, 7200.0, dt=1.0)
    phases = {s.phase for s in samples}
    assert "checkpoint" in phases
    assert "eval" in phases
    assert profile.checkpoints >= 4
    assert profile.evals >= 1


def test_checkpoint_dips_are_deep_and_brief():
    cfg = ProfileConfig(checkpoint_interval_s=120.0, checkpoint_duration_s=30.0)
    profile = TrainingRunProfile(16, cfg, seed=8)
    samples = drive(profile, 1200.0)
    ckpt = [s for s in samples if s.phase == "checkpoint"]
    sustained = [s for s in samples if s.phase == "sustained"]
    assert ckpt, "no checkpoint occurred"
    assert np.mean([s.mean_utilisation for s in ckpt]) < 0.5 * np.mean(
        [s.mean_utilisation for s in sustained]
    )
    # brief relative to the interval between them
    assert len(ckpt) / len(samples) < 0.4


def test_a_straggler_idles_one_rack_and_stalls_the_rest():
    cfg = ProfileConfig(straggler_rate_per_hour=600.0, straggler_duration_s=60.0)
    profile = TrainingRunProfile(16, cfg, seed=9)
    samples = drive(profile, 1800.0)
    strag = [s for s in samples if s.phase == "straggler"]
    assert strag, "no straggler event with a high rate"
    s = strag[len(strag) // 2]
    assert s.straggler is not None
    assert s.utilisation[s.straggler] == pytest.approx(cfg.idle_util, abs=1e-6)
    peers = np.delete(s.utilisation, s.straggler)
    assert peers.mean() < ProfileConfig().sustained_util
    assert peers.mean() > cfg.idle_util


def test_jitter_is_correlated_in_time_not_white_noise():
    """GPUs on a job breathe together and smoothly; white noise would flicker."""
    profile = TrainingRunProfile(16, ProfileConfig(straggler_rate_per_hour=0.0), seed=11)
    drive(profile, 300.0)  # get past the ramp
    u = np.array([s.mean_utilisation for s in drive(profile, 200.0)])
    u = u[np.isclose(u, u.mean(), atol=0.15)]  # ignore any dip transitions
    d = np.diff(u)
    # lag-1 autocorrelation of the series should be high
    ac = np.corrcoef(u[:-1], u[1:])[0, 1]
    assert ac > 0.8, f"lag-1 autocorrelation {ac:.2f}"
    assert np.abs(d).max() < 0.05


def test_all_phases_are_reachable_and_named_consistently():
    cfg = ProfileConfig(
        checkpoint_interval_s=90.0,
        eval_every_n_checkpoints=2,
        straggler_rate_per_hour=200.0,
    )
    profile = TrainingRunProfile(16, cfg, seed=12)
    seen = {s.phase for s in drive(profile, 3600.0)}
    assert seen <= set(PHASES)
    assert seen == set(PHASES), f"never reached {set(PHASES) - seen}"


def test_progress_is_monotonic_within_a_phase():
    profile = TrainingRunProfile(16, seed=13)
    prev = None
    for s in drive(profile, 400.0):
        if prev and s.phase == prev.phase:
            assert s.progress >= prev.progress - 1e-9 or s.progress == 0.0
        prev = s


def test_bad_config_is_rejected_loudly():
    with pytest.raises(ValueError):
        TrainingRunProfile(4, ProfileConfig(sustained_util=1.5))
    with pytest.raises(ValueError):
        TrainingRunProfile(4, ProfileConfig(checkpoint_duration_s=1e6))
    with pytest.raises(ValueError):
        TrainingRunProfile(4, ProfileConfig(ramp_s=0.0))


def test_reset_restarts_the_run_identically():
    profile = TrainingRunProfile(16, seed=14)
    first = [s.mean_utilisation for s in drive(profile, 300.0)]
    profile.reset()
    profile.rng = np.random.Generator(np.random.PCG64(profile.seed))
    profile.reset()
    second = [s.mean_utilisation for s in drive(profile, 300.0)]
    assert np.allclose(first, second)

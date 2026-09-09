from __future__ import annotations

from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest

from kra_analytics.modeling_v2 import V2FeatureContract
from kra_analytics.ranking_oof import (
    PROVENANCE,
    expected_oof,
    join_oof,
    load_oof,
    make_oof,
    normalize_scores,
    validate_oof,
    write_oof,
)
from kra_analytics.ranking_research import (
    FEATURE_HASH,
    VERSION,
    RankingPaths,
    fit_ranker,
    grouped,
    l133_contract,
    model_config,
    prepare_fold,
    ranking_metrics,
    validate_groups,
    validate_rows,
)

ROOT = Path(__file__).resolve().parents[1]


def sample() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "race_id": ["A"] * 4 + ["B"] * 5,
            "horse_id": ["01", "02", "03", "04", "01", "02", "03", "04", "05"],
            "race_date": ["2023-07-02"] * 9,
            "place_hit": [1, 1, 0, 0, 0, 0, 1, 1, 1],
        }
    )


def provenance() -> dict[str, str]:
    values = dict.fromkeys(PROVENANCE, "a" * 64)
    values.update(feature_hash=FEATURE_HASH, contract_version=VERSION)
    return values


def test_source_is_read_only_and_outputs_are_local(tmp_path: Path) -> None:
    source = tmp_path / "source.duckdb"
    with duckdb.connect(str(source)) as conn:
        conn.execute("CREATE TABLE original(x INT)")
    paths = RankingPaths(tmp_path, source)
    with paths.connect_source() as conn:
        assert conn.execute("SELECT count(*) FROM original").fetchone() == (0,)
        with pytest.raises(duckdb.InvalidInputException):
            conn.execute("CREATE TABLE forbidden(x INT)")
    for target in [str(source), "../outside.json", "src/overwrite.py"]:
        with pytest.raises(ValueError):
            paths.output(target)
    paths.write_json(f"data/exports/modeling/{VERSION}/audit.json", {"ok": True})
    with pytest.raises(FileExistsError):
        paths.write_json(f"data/exports/modeling/{VERSION}/audit.json", {})
    collision = tmp_path / f"data/exports/modeling/{VERSION}/source.duckdb"
    collision.write_bytes(b"source")
    with pytest.raises(ValueError, match="collision"):
        RankingPaths(tmp_path, collision).output(str(collision))


def test_feature_hash_and_order(tmp_path: Path) -> None:
    contract = l133_contract(ROOT)
    assert len(contract.inputs) == 133
    assert contract.feature_hash == FEATURE_HASH
    # Validate corrupted order against the same protected inventory and bundle code.
    import shutil

    shutil.copytree(ROOT / "docs", tmp_path / "docs")
    path = tmp_path / "docs/post-baseline-v2-improvement-validation-contract.json"
    import json

    data = json.loads(path.read_text())
    data["candidate"]["feature_order"].reverse()
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash"):
        l133_contract(tmp_path)


def test_group_continuity_sizes_and_relevance() -> None:
    frame, sizes = grouped(sample().sample(frac=1, random_state=42))
    assert sizes.tolist() == [4, 5]
    validate_groups(frame, sizes)
    with pytest.raises(ValueError):
        validate_groups(frame, np.array([5, 4]))
    with pytest.raises(ValueError):
        validate_groups(frame, np.array([4, 4]))
    with pytest.raises(ValueError):
        validate_groups(frame, np.array([4.0, 5.0]))
    interleaved = frame.iloc[[0, 4, 1, 2, 3, 5, 6, 7, 8]]
    with pytest.raises(ValueError, match="Noncontiguous"):
        validate_groups(interleaved, sizes)
    for bad in [2, np.nan, -1]:
        changed = frame.copy()
        changed.loc[0, "place_hit"] = bad
        with pytest.raises(ValueError, match="Relevance"):
            grouped(changed)
    with pytest.raises(ValueError, match="Duplicate"):
        grouped(pd.concat([frame, frame.iloc[:1]]))


def test_dates_and_race_leakage() -> None:
    frame = sample()
    frame.loc[0, "race_date"] = "2024-07-01"
    with pytest.raises(ValueError):
        validate_rows(frame)
    frame.loc[0, "race_date"] = "2023-06-01"
    with pytest.raises(ValueError, match="split across dates"):
        prepare_fold(frame, "fold_1")


def test_macro_metrics_have_hand_calculated_values() -> None:
    # Equal scores -> horse ID ordering. A: 2/2 hits; B: 1/3 hits.
    per_race, macro = ranking_metrics(sample(), np.zeros(9))
    expected_b = 0.5 / (1 + 1 / np.log2(3) + 0.5)
    assert per_race.ndcg_at_3.tolist() == pytest.approx([1, expected_b])
    assert macro["macro_ndcg_at_3"] == pytest.approx((1 + expected_b) / 2)
    assert macro["macro_recall_at_3"] == pytest.approx((1 + 1 / 3) / 2)
    assert macro["macro_top1_plc_hit"] == 0.5
    assert macro["macro_top3_any_plc_hit"] == 1
    assert macro["macro_plc_hits_in_top3"] == 1.5
    assert macro["macro_ndcg_at_3"] != pytest.approx((4 + 5 * expected_b) / 9)


def test_zero_positive_not_silently_ignored() -> None:
    frame = sample()
    frame.loc[frame.race_id.eq("A"), "place_hit"] = 0
    per_race, macro = ranking_metrics(frame, np.zeros(len(frame)))
    assert np.isnan(per_race.ndcg_at_3.iloc[0])
    assert np.isnan(macro["macro_ndcg_at_3"])


def test_oof_ties_normalization_and_round_trip(tmp_path: Path) -> None:
    frame, meta = sample(), provenance()
    expected = expected_oof(frame)
    rank = make_oof(
        frame, np.array([0.0, 0.0, 0.0, 0.0, -2.0, 1.0, 3.0, 8.0, 8.0]), meta, kind="ranking"
    )
    assert rank.ranking_within_race_rank.tolist() == [1, 2, 3, 4, 5, 4, 3, 1, 2]
    assert rank.ranking_normalized_score[:4].eq(0).all()
    assert rank.ranking_normalized_score[4:].std(ddof=0) == pytest.approx(1)
    plc = make_oof(frame, np.full(9, 0.3), meta, kind="plc")
    assert len(join_oof(rank, plc, expected)) == 9
    source = tmp_path / "source.duckdb"
    source.touch()
    paths = RankingPaths(tmp_path, source)
    path = write_oof(
        paths, f"data/exports/modeling/{VERSION}/test/ranking.csv", rank, expected, kind="ranking"
    )
    loaded = load_oof(path, expected, kind="ranking")
    assert loaded.horse_id.iloc[0] == "01"
    assert loaded.ranking_raw_score.tolist() == rank.ranking_raw_score.tolist()
    plc_path = write_oof(
        paths, f"data/exports/modeling/{VERSION}/test/plc.csv", plc, expected, kind="plc"
    )
    assert len(load_oof(plc_path, expected, kind="plc")) == 9


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "fold", "rank", "norm", "hash"])
def test_oof_rejects_contract_violations(mutation: str) -> None:
    frame = sample()
    expected = expected_oof(frame)
    oof = make_oof(frame, np.zeros(9), provenance(), kind="ranking")
    if mutation == "missing":
        oof = oof.iloc[:-1]
    elif mutation == "duplicate":
        oof = pd.concat([oof, oof.iloc[:1]], ignore_index=True)
    else:
        column, value = {
            "fold": ("fold_id", "fold_2"),
            "rank": ("ranking_within_race_rank", 9),
            "norm": ("ranking_normalized_score", 2),
            "hash": ("source_db_hash", "wrong"),
        }[mutation]
        oof.loc[0, column] = value
    with pytest.raises(ValueError):
        validate_oof(oof, expected, kind="ranking")


def test_reject_in_sample_oof_and_nonfinite_scores() -> None:
    frame = sample()
    frame["race_date"] = "2023-06-01"
    with pytest.raises(ValueError):
        make_oof(frame, np.zeros(9), provenance(), kind="ranking")
    with pytest.raises(ValueError):
        normalize_scores(sample(), np.full(9, np.inf))


def test_synthetic_lambdarank_fit_predict_deterministic(tmp_path: Path) -> None:
    rng = np.random.default_rng(12)
    n = 400
    x = rng.normal(size=n)
    train = pd.DataFrame(
        {
            "race_id": np.repeat([f"R{i:03}" for i in range(50)], 8),
            "horse_id": [f"{i % 8:02}" for i in range(n)],
            "race_date": ["2023-02-01"] * n,
            "numeric": x,
            "category": np.where(x > 0, "A", "B"),
            "place_hit": np.tile([1, 1, 1, 0, 0, 0, 0, 0], 50),
        }
    )
    train.loc[::9, "numeric"] = np.nan
    contract = V2FeatureContract(("numeric", "category"), ("category",), ("numeric",), (), "test")
    evaluation = train.iloc[:16].copy()
    evaluation["race_date"] = "2023-07-02"
    evaluation["category"] = "UNSEEN"
    evaluation["numeric"] = 9999.0
    first, second = fit_ranker(train, contract), fit_ranker(train, contract)
    scores = first.predict(evaluation)
    assert scores.shape == (16,)
    assert np.array_equal(scores, second.predict(evaluation))
    categorical = first.preprocessor.named_transformers_["categorical"]
    assert "UNSEEN" not in categorical.named_steps["onehot"].categories_[0]
    numeric = first.preprocessor.named_transformers_["numeric"]
    assert numeric.named_steps["imputer"].statistics_[0] == pytest.approx(
        np.nanmedian(train.numeric)
    )
    import joblib

    source = tmp_path / "source.duckdb"
    source.touch()
    saved = first.save(
        RankingPaths(tmp_path, source), f"data/exports/modeling/{VERSION}/synthetic/model.joblib"
    )
    assert np.array_equal(scores, joblib.load(saved).predict(evaluation))
    assert first.model.booster_.num_trees() > 1
    assert model_config()["n_estimators"] == 200
    assert model_config()["label_gain"] == [0, 1]


def test_loader_guards_query_population_and_pit(monkeypatch: pytest.MonkeyPatch) -> None:
    from contextlib import contextmanager
    from datetime import date

    from kra_analytics.ranking_research import load_dataset

    contract = l133_contract(ROOT)
    frame = sample()
    frame["race_date"] = pd.to_datetime(frame.race_date).dt.date
    frame = pd.concat([frame, pd.DataFrame(0, index=frame.index, columns=contract.inputs)], axis=1)
    frame = frame.assign(
        snapshot_id="s",
        result_status="FINISHED",
        is_valid_start=True,
        is_valid_finish=True,
        feature_as_of=pd.Timestamp("2023-07-02"),
        source_max_event_date=pd.Timestamp("2023-07-01"),
        population_exclusion_reason=None,
        runner_result_id="rr",
        official_finish_rank=1,
        canonical_status="FINISHED",
        canonical_start=True,
        canonical_finish=True,
        f1_source_max_event_date=pd.Timestamp("2023-07-01"),
        audit_horse_id="h",
    )

    class Connection:
        def execute(self, query, params):
            assert "WHERE s.race_date >= ? AND s.race_date < ?" in query
            assert params == [date(2023, 1, 1), date(2024, 7, 1)]
            return self

        def fetchdf(self):
            return frame.copy()

    @contextmanager
    def source(self):
        yield Connection()

    monkeypatch.setattr(RankingPaths, "connect_source", source)
    paths = RankingPaths(ROOT, ROOT / "unused.duckdb")
    loaded, _ = load_dataset(paths)
    assert len(loaded) == 9
    frame.loc[0, "f1_source_max_event_date"] = pd.Timestamp("2023-07-02")
    with pytest.raises(ValueError, match="PIT"):
        load_dataset(paths)
    frame.loc[0, "f1_source_max_event_date"] = pd.Timestamp("2023-07-01")
    frame.loc[0, "result_status"] = "DNS"
    with pytest.raises(ValueError, match="DNS"):
        load_dataset(paths)


def test_all_four_folds_and_single_relevance_exclusion() -> None:
    parts = []
    for month in pd.date_range("2023-01-01", periods=18, freq="MS"):
        part = sample().iloc[:4].copy()
        part["race_id"] = month.strftime("R%Y%m")
        part["race_date"] = month.date()
        parts.append(part)
    frame = pd.concat(parts, ignore_index=True)
    for i in range(1, 5):
        train, evaluation, exclusions = prepare_fold(frame, f"fold_{i}")
        assert train.race_date.max() < evaluation.race_date.min()
        assert not set(train.race_id) & set(evaluation.race_id)
        assert len(evaluation) == 12
        assert exclusions.empty
    frame.loc[frame.race_id.eq("R202301"), "place_hit"] = 1
    train, _, exclusions = prepare_fold(frame, "fold_1")
    assert "R202301" not in set(train.race_id)
    assert exclusions.reason.tolist() == ["SINGLE_RELEVANCE"]


def test_environment_drift_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata

    from kra_analytics.ranking_research import validate_environment

    assert validate_environment(ROOT)["lightgbm"] == "4.6.0"
    monkeypatch.setattr(importlib.metadata, "version", lambda name: "0.0.0")
    with pytest.raises(ValueError, match="Environment drift"):
        validate_environment(ROOT)


def test_plc_oof_includes_deterministic_within_race_rank() -> None:
    frame = sample()
    expected = expected_oof(frame)
    plc = make_oof(frame, np.zeros(len(frame)), provenance(), kind="plc")
    validate_oof(plc, expected, kind="plc")
    assert plc.plc_within_race_rank.tolist() == [1, 2, 3, 4, 1, 2, 3, 4, 5]

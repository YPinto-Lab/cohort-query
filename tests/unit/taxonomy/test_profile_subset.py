import pandas as pd
from Engines.TaxonomyEngine.profile_subset import ProfileSubset


def test_metadata_df_aligns_to_profile_index():
    profile = pd.DataFrame({"t1": [1, 2]}, index=pd.Index(["SRR1", "SRR2"], name="acc"))
    metadata = pd.DataFrame({"acc": ["SRR1", "SRR2", "SRR3"], "Group": ["a", "b", "c"]})

    subset = ProfileSubset(profile_df=profile, full_metadata_df=metadata)

    assert list(subset.metadata_df["acc"]) == ["SRR1", "SRR2"]


def test_metadata_df_preserves_profile_order():
    profile = pd.DataFrame({"t1": [1, 2]}, index=pd.Index(["SRR2", "SRR1"], name="acc"))
    metadata = pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["a", "b"]})

    subset = ProfileSubset(profile_df=profile, full_metadata_df=metadata)

    assert list(subset.metadata_df["acc"]) == ["SRR2", "SRR1"]

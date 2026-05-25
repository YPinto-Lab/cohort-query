from pathlib import Path
from Accessors.MergedDumpAccessor.merged_dump_accessor import MergedDumpAccessor

FIXTURE = Path("Tests/fixtures/merged_tiny.dmp")


def test_load_parses_old_to_new_map():
    accessor = MergedDumpAccessor()

    mapping = accessor.load(FIXTURE)

    assert mapping == {999: 561, 888: 2}

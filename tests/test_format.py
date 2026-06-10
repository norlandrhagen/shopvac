import pyarrow as pa

from shopvac.format import print_table, table_to_data


def make_tree_table() -> pa.Table:
    return pa.table(
        {
            "prefix": [
                "proj-b",
                "proj-b/data-v1",
                "proj-b/data-v2",
                "proj-a",
                "proj-a/model-1",
            ],
            "size_bytes": [4300, 4000, 300, 2550, 2000],
            "size_formatted": ["4.3 kB", "4.0 kB", "300 Bytes", "2.6 kB", "2.0 kB"],
            "depth": [1, 2, 2, 1, 2],
        }
    )


def test_print_table_tree_connectors(capsys):
    print_table(make_tree_table())
    out = capsys.readouterr().out
    assert "proj-b" in out
    assert "├── data-v1" in out
    assert "└── data-v2" in out
    assert "└── model-1" in out


def test_print_table_flat_unchanged(capsys):
    table = pa.table(
        {
            "prefix": ["prefix-a"],
            "size_bytes": [6000],
            "size_formatted": ["6.0 kB"],
        }
    )
    print_table(table)
    out = capsys.readouterr().out
    assert "prefix-a" in out
    assert "├──" not in out


def test_table_to_data_tree_indents():
    data = table_to_data(make_tree_table())
    assert data[0] == ["Prefix", "Size"]
    assert data[1] == ["proj-b", "4.3 kB"]
    assert data[2] == ["  data-v1", "4.0 kB"]

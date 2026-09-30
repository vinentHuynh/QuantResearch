import tempfile
import unittest
from pathlib import Path

from workbench.dataset_reference import resolve_dataset_path
from workbench.datasets import logical_dataset_path


class DatasetProtocolTests(unittest.TestCase):
    def test_resolver_reads_v1_absolute_and_v2_logical_references(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'state'
            bars = home / 'datasets' / 'fixture.parquet'
            bars.parent.mkdir(parents=True)
            bars.write_bytes(b'fixture')
            self.assertEqual(resolve_dataset_path({'path': str(bars)}), bars.resolve())
            self.assertEqual(
                resolve_dataset_path(
                    {'schema_version': 2, 'path': 'datasets/fixture.parquet'},
                    home,
                ),
                bars.resolve(),
            )
            for invalid in (
                '../outside.parquet', str(bars), 'datasets\\fixture.parquet',
                'datasets//fixture.parquet', 'datasets/./fixture.parquet',
                'C:fixture.parquet',
            ):
                with self.subTest(path=invalid), self.assertRaises(ValueError):
                    resolve_dataset_path(
                        {'schema_version': 2, 'path': invalid},
                        home,
                    )

    def test_new_dataset_paths_are_logical_to_workbench_home(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state'
            destination = state / 'datasets'
            bars = destination / 'fixture-v1' / 'bars.parquet'
            bars.parent.mkdir(parents=True)
            bars.write_bytes(b'fixture')
            self.assertEqual(
                logical_dataset_path(destination, bars),
                'datasets/fixture-v1/bars.parquet',
            )

    def test_new_dataset_paths_cannot_escape_workbench_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / 'state' / 'datasets'
            destination.mkdir(parents=True)
            outside = root / 'outside.parquet'
            outside.write_bytes(b'fixture')
            with self.assertRaisesRegex(ValueError, 'outside WORKBENCH_HOME'):
                logical_dataset_path(destination, outside)


if __name__ == '__main__':
    unittest.main()

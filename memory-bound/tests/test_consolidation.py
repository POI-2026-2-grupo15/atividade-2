import io
import unittest

from app.consolidation import CSVSource, InvalidCSV, consolidate, read_into_catalog

HEADER = b"id,name,email,description\n"


class ConsolidationTests(unittest.TestCase):
    def test_last_occurrence_replaces_the_complete_record(self):
        catalog = {}
        source = CSVSource("updates.csv", io.BytesIO(
            HEADER + b"001,Ana,old@example.com,old\n001,Ana,new@example.com,new\n"
        ))
        self.assertEqual(read_into_catalog(source, catalog), 2)
        self.assertEqual(catalog["001"], {
            "id": "001", "name": "Ana", "email": "new@example.com", "description": "new",
        })

    def test_ids_preserve_leading_zeroes(self):
        result = consolidate([CSVSource("ids.csv", io.BytesIO(
            HEADER + b"001,Ana,,one\n1,Bruno,,two\n"
        ))])
        self.assertEqual(result.unique_records, 2)
        self.assertEqual(result.replaced_occurrences, 0)

    def test_duplicates_within_and_across_files(self):
        result = consolidate([
            CSVSource("a.csv", io.BytesIO(HEADER + b"1,A,,old\n1,A,,updated\n2,B,,other\n")),
            CSVSource("b.csv", io.BytesIO(HEADER + b"1,A,,latest\n3,C,,new\n")),
        ])
        self.assertEqual((result.files_processed, result.records_received,
                          result.unique_records, result.replaced_occurrences), (2, 5, 3, 2))
        self.assertGreaterEqual(result.processing_time_ms, 0)

    def test_bom_quoted_comma_and_multiline_field(self):
        catalog = {}
        received = read_into_catalog(CSVSource("quoted.csv", io.BytesIO(
            b"\xef\xbb\xbf" + HEADER + b'1,"Ana, Silva",,"first\nsecond"\n'
        )), catalog)
        self.assertEqual(received, 1)
        self.assertEqual(catalog["1"]["name"], "Ana, Silva")
        self.assertEqual(catalog["1"]["description"], "first\nsecond")

    def test_header_only_is_valid_and_blank_lines_are_ignored(self):
        result = consolidate([CSVSource("empty.csv", io.BytesIO(HEADER + b"\n"))])
        self.assertEqual(result.records_received, 0)
        self.assertEqual(result.unique_records, 0)

    def test_invalid_csv_reports_source_without_echoing_record(self):
        cases = [b"", b"wrong,header\n", HEADER + b" ,secret,,data\n",
                 HEADER + b"1,secret\n", HEADER + b'1,secret,,"unfinished\n',
                 HEADER + b"1,secret,,\xff\n"]
        for contents in cases:
            with self.subTest(contents=contents):
                with self.assertRaises(InvalidCSV) as caught:
                    consolidate([CSVSource("invalid.csv", io.BytesIO(contents))])
                self.assertEqual(caught.exception.filename, "invalid.csv")
                self.assertGreaterEqual(caught.exception.line, 1)
                self.assertNotIn("secret", caught.exception.reason)


if __name__ == "__main__":
    unittest.main()

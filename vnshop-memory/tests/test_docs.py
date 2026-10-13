import unittest
from pathlib import Path

from kg import docs as D

SAMPLE_DOCS = Path(__file__).resolve().parent.parent / "data" / "docs_md.sample"


class CleanTest(unittest.TestCase):
    def test_removes_images_and_tokens(self):
        stats = D.DocStats()
        text = ("Trước ![a](x.png?atl_token=abc123) sau <img src='y.png'>\n"
                "[link](https://wiki/x?atl_token=DEF456&b=1)")
        out = D.clean(text, stats)
        self.assertNotIn("abc123", out)
        self.assertNotIn("DEF456", out)
        self.assertNotIn("<img", out)
        self.assertIn("atl_token=REDACTED", out)
        self.assertEqual(stats.images_removed, 2)
        self.assertEqual(stats.atl_tokens_removed, 2)


class ChunkTest(unittest.TestCase):
    def test_heading_paths_and_empty_sections(self):
        text = ("# Màn hình\nGiới thiệu đủ dài để giữ lại.\n## Trống\n### Bộ lọc\n"
                "Nội dung bộ lọc đủ dài.\n```\n# không phải tiêu đề\n```\n## Khác\nNội dung mục khác đủ dài.")
        sections = D.chunk_markdown(text)
        self.assertEqual([h for h, _ in sections], ["Màn hình", "Màn hình > Trống > Bộ lọc", "Màn hình > Khác"])
        self.assertIn("# không phải tiêu đề", sections[1][1])

    def test_long_section_is_split_under_limit(self):
        table = "\n".join(f"| trường {i} | kiểu | mô tả khá dài cho trường số {i} |" for i in range(200))
        sections = D.chunk_markdown(f"# Bảng\n{table}")
        self.assertGreater(len(sections), 1)
        self.assertTrue(all(len(body) <= D.MAX_CHARS for _, body in sections))
        joined = "\n".join(body for _, body in sections)
        self.assertIn("trường 0 |", joined)
        self.assertIn("trường 199 |", joined)


class ReadDocsTest(unittest.TestCase):
    def test_sample_folder(self):
        chunks, stats = D.read_docs(SAMPLE_DOCS)
        self.assertEqual(stats.files, 2)
        self.assertEqual(stats.atl_tokens_removed, 2)
        self.assertTrue(all(c["path"].startswith("docs_md/bo_admin/module-mau/") for c in chunks))
        self.assertTrue(all("atl_token=" not in c["text"] or "REDACTED" in c["text"] for c in chunks))
        self.assertEqual(len({c["id"] for c in chunks}), len(chunks))
        headings = [c["heading"] for c in chunks if c["path"].endswith("011.md")]
        self.assertNotIn("Màn hình mẫu 047 > Mục trống", headings)
        self.assertIn("nut mau 047", chunks[[c["path"].endswith("011.md") for c in chunks].index(True)]["text_folded"])


if __name__ == "__main__":
    unittest.main()

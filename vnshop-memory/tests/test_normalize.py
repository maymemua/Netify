import json
import unittest
from pathlib import Path

from kg import schema_map as sm
from kg.normalize import normalize, parse_source_path
from kg.query import build_fulltext_query

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "graph.sample.json"


class SchemaMapTest(unittest.TestCase):
    def test_fold(self):
        self.assertEqual(sm.fold("Màn hình BO"), "man hinh bo")
        self.assertEqual(sm.fold("Đơn hàng"), "don hang")
        self.assertEqual(sm.fold("screen_"), "screen")

    def test_node_label_variants(self):
        for raw in ("screen", "Screen", "screen_", "Màn hình BO"):
            self.assertEqual(sm.node_label(raw), ("Screen", True), raw)
        for raw in ("func", "function", "Function", "Chức năng"):
            self.assertEqual(sm.node_label(raw)[0], "Function", raw)
        self.assertEqual(sm.node_label("Trạng thái")[0], "Status")
        self.assertEqual(sm.node_label("kiểu lạ"), ("Concept", False))
        self.assertEqual(sm.node_label(None), ("Concept", False))

    def test_relation_name(self):
        self.assertEqual(sm.relation_name("navigates_to"), "NAVIGATES_TO")
        self.assertEqual(sm.relation_name("gọi API"), "CALLS_API")
        self.assertEqual(sm.relation_name("Có trạng thái"), "HAS_STATUS")
        # Văn bản tự do tiếng Việt không được thành tên quan hệ.
        self.assertIsNone(sm.relation_name("Nhãn cạnh giả"))
        self.assertIsNone(sm.relation_name("Khi đơn ở trạng thái chờ duyệt"))
        self.assertIsNone(sm.relation_name("Phần mềm"))


class NormalizeSampleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = json.loads(SAMPLE.read_text(encoding="utf-8"))
        cls.data = normalize(cls.graph)

    def test_counts(self):
        s = self.data.stats
        self.assertEqual(s["nodes_in"], 56)
        self.assertEqual(s["edges_in"], 74)
        self.assertEqual(s["nodes_out"], 56)
        self.assertEqual(s["edges_dangling_skipped"], 0)
        self.assertEqual(s["groups"], 3)
        self.assertEqual(s["unmapped_node_types"], {})

    def test_duplicate_edges_are_merged_not_lost(self):
        # screen_sample_023 -> sys_sample_026 "displays" xuất hiện 2 lần (label và relation).
        displays = self.data.rels["DISPLAYS"]
        item = next(e for e in displays
                    if e["source"] == "screen_sample_023" and e["target"] == "sys_sample_026")
        self.assertEqual(item["weight"], 2)
        # Cùng cặp đó còn có quan hệ FILTERS riêng.
        self.assertTrue(any(e["source"] == "screen_sample_023" and e["target"] == "sys_sample_026"
                            for e in self.data.rels["FILTERS"]))

    def test_relation_from_type_and_free_text_label_kept_as_note(self):
        nav = self.data.rels["NAVIGATES_TO"]
        item = next(e for e in nav if e["source"] == "screen_sample_051")
        self.assertEqual(item["notes"], ["Nhãn cạnh giả"])
        self.assertNotIn("RELATED_TO", self.data.rels)

    def test_every_relation_type_is_safe_for_cypher(self):
        for rel in self.data.rels:
            self.assertRegex(rel, sm.SAFE_IDENT)
        for node in self.data.nodes:
            self.assertRegex(node["label"], sm.SAFE_IDENT)

    def test_properties_source_file_must_be_a_path(self):
        node = next(n for n in self.data.nodes if n["id"] == "report_sample_004")
        self.assertIsNone(node["source_file"])
        self.assertEqual(node["description"], "giá trị giả (description)")

    def test_modules_from_paths(self):
        self.assertEqual({m["key"] for m in self.data.modules}, {"bo_admin/module-mau"})

    def test_dangling_and_unmapped(self):
        graph = {
            "nodes": [{"id": "a", "label": "A", "type": "kiểu lạ"}, {"id": "b", "label": "B"}],
            "links": [
                {"source": "a", "target": "b", "label": "Khi bấm nút lưu"},
                {"source": "a", "target": "missing", "relation": "contains"},
                {"source": "a", "target": "b", "type": "Phần mềm"},
            ],
            "hyperedges": [{"id": "h", "members": ["a", "missing"]}],
        }
        data = normalize(graph, {"node_to_community": {"a": 3}})
        self.assertEqual(data.stats["edges_dangling_skipped"], 1)
        self.assertEqual(data.stats["unmapped_node_types"], {"kiểu lạ": 1, "(không có type)": 1})
        related = data.rels["RELATED_TO"][0]
        self.assertEqual(related["weight"], 2)
        self.assertEqual(related["notes"], ["Khi bấm nút lưu"])
        self.assertEqual(data.groups[0]["members"], ["a"])
        self.assertEqual(data.stats["group_members_missing"], 1)
        self.assertEqual(next(n for n in data.nodes if n["id"] == "a")["community"], 3)


class PathAndQueryTest(unittest.TestCase):
    def test_parse_source_path(self):
        self.assertEqual(
            parse_source_path("docs_md/bo_admin/6-qun-l-n-hng/611-tao-don.md"),
            ("bo_admin", "bo_admin/6-qun-l-n-hng", "6", "Đơn hàng"),
        )
        self.assertEqual(parse_source_path("docs_md/policy/chinh-sach.md")[:2], ("policy", None))

    def test_build_fulltext_query(self):
        self.assertEqual(build_fulltext_query("là của"), None)
        q = build_fulltext_query("màn hình của đơn hàng")
        self.assertEqual(q, '"màn hình đơn hàng"^4 OR màn OR hình OR đơn OR hàng')
        self.assertEqual(build_fulltext_query("PO?"), "po")


if __name__ == "__main__":
    unittest.main()

"""跨模块标签。

标签是唯一横穿所有模块的东西，所以边界最容易糊：
它不能拥有数据、不能改来源记录，而链接刻意没有外键，
所以「来源被删了怎么办」必须有明确答案。
"""
import tempfile
import unittest
from datetime import date
from pathlib import Path

from fastapi import HTTPException

from backend import main
from backend.core import db as db_core
from backend.modules import fitness, inbox, study, tags
from backend.views import tags as tag_view


class TagTests(unittest.TestCase):
    def setUp(self):
        self.original_db_path = db_core.current_path()
        self.temp_dir = tempfile.TemporaryDirectory()
        db_core.use_database(Path(self.temp_dir.name) / "ledger.db")
        main.init_db()
        self.today = date.today().isoformat()

    def tearDown(self):
        db_core.use_database(self.original_db_path)
        self.temp_dir.cleanup()

    def a_study_record(self, conn, subject="高等数学"):
        return study.record_study_session(
            conn, occurred_on=self.today, subject=subject, duration_minutes=45, focus=4,
        )

    # ---------- 标签名 ----------

    def test_hash_prefix_is_stripped_so_the_tag_is_the_same(self):
        with main.db() as conn:
            first = tags.get_or_create_tag(conn, "#考研")
            second = tags.get_or_create_tag(conn, "考研")
        self.assertEqual(first["id"], second["id"])

    def test_invalid_names_are_rejected(self):
        for name in ("", "   ", "#", "带 空格", "逗号,不行", "x" * 21):
            with self.subTest(name=name):
                with main.db() as conn:
                    with self.assertRaises(HTTPException):
                        tags.get_or_create_tag(conn, name)

    # ---------- 贴与撕 ----------

    def test_same_tag_twice_makes_one_link(self):
        with main.db() as conn:
            record = self.a_study_record(conn)
            tags.attach_tag(conn, name="考研", module="study", record_id=record["id"])
            tags.attach_tag(conn, name="考研", module="study", record_id=record["id"])
            links = tags.get_tag_links(conn, "考研")
        self.assertEqual(len(links), 1)

    def test_unsupported_module_is_rejected(self):
        with main.db() as conn:
            with self.assertRaises(HTTPException):
                tags.attach_tag(conn, name="考研", module="astrology", record_id=1)

    def test_detaching_leaves_the_source_record_alone(self):
        with main.db() as conn:
            record = self.a_study_record(conn)
            tags.attach_tag(conn, name="考研", module="study", record_id=record["id"])
            tags.detach_tag(conn, name="考研", module="study", record_id=record["id"])
            still_there = conn.execute(
                "SELECT COUNT(*) FROM study_sessions WHERE id = ?", (record["id"],)
            ).fetchone()[0]
        self.assertEqual(still_there, 1)

    def test_deleting_a_tag_removes_links_but_not_records(self):
        with main.db() as conn:
            record = self.a_study_record(conn)
            tag = tags.attach_tag(conn, name="考研", module="study", record_id=record["id"])
            tags.delete_tag(conn, tag["id"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM tag_links").fetchone()[0], 0)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM study_sessions").fetchone()[0], 1
            )

    # ---------- 跨模块解析 ----------

    def test_one_tag_spans_several_modules(self):
        with main.db() as conn:
            study_record = self.a_study_record(conn, "课程项目")
            session = fitness.record_workout(
                conn, occurred_on=self.today, activity="cardio",
                duration_minutes=30, intensity=6, note="边跑边想项目",
            )
            item = inbox.add_inbox_item(conn, content="查一下项目参考文献")
            for module, record_id in (("study", study_record["id"]),
                                      ("fitness", session["id"]),
                                      ("inbox", item["id"])):
                tags.attach_tag(conn, name="课程项目", module=module, record_id=record_id)
            resolved = tag_view.get_tagged_records(conn, "课程项目")

        self.assertEqual(resolved["total"], 3)
        self.assertEqual(set(resolved["by_module"]), {"study", "fitness", "inbox"})
        for record in resolved["records"]:
            self.assertTrue(record["title"])
            self.assertTrue(record["module_label"])

    def test_unknown_tag_returns_an_honest_empty_result(self):
        with main.db() as conn:
            resolved = tag_view.get_tagged_records(conn, "不存在的标签")
        self.assertEqual(resolved["total"], 0)
        self.assertIn("没有贴在任何记录上", resolved["note"])

    # ---------- 悬空链接 ----------

    def test_deleted_source_becomes_a_reported_dead_link(self):
        """链接没有外键，来源删了链接还在。不能假装它不存在。"""
        with main.db() as conn:
            record = self.a_study_record(conn)
            tags.attach_tag(conn, name="考研", module="study", record_id=record["id"])
            conn.execute("DELETE FROM study_sessions WHERE id = ?", (record["id"],))
            resolved = tag_view.get_tagged_records(conn, "考研")

        self.assertEqual(resolved["total"], 0)
        self.assertEqual(resolved["dead_links"], 1)

    def test_cleanup_is_explicit_and_only_removes_dead_links(self):
        with main.db() as conn:
            alive = self.a_study_record(conn, "还在的")
            doomed = self.a_study_record(conn, "要删的")
            tags.attach_tag(conn, name="考研", module="study", record_id=alive["id"])
            tags.attach_tag(conn, name="考研", module="study", record_id=doomed["id"])
            conn.execute("DELETE FROM study_sessions WHERE id = ?", (doomed["id"],))

            before = tag_view.get_tagged_records(conn, "考研")
            self.assertEqual((before["total"], before["dead_links"]), (1, 1))

            result = tag_view.cleanup_dead_links(conn)
            after = tag_view.get_tagged_records(conn, "考研")

        self.assertEqual(result["removed"], 1)
        self.assertEqual((after["total"], after["dead_links"]), (1, 0))

    def test_reading_never_prunes_by_itself(self):
        """用户应当先看到有多少条失效，再决定要不要清。"""
        with main.db() as conn:
            record = self.a_study_record(conn)
            tags.attach_tag(conn, name="考研", module="study", record_id=record["id"])
            conn.execute("DELETE FROM study_sessions WHERE id = ?", (record["id"],))
            tag_view.get_tagged_records(conn, "考研")
            tag_view.get_tagged_records(conn, "考研")
            remaining = conn.execute("SELECT COUNT(*) FROM tag_links").fetchone()[0]
        self.assertEqual(remaining, 1, "读取不该悄悄删链接")

    # ---------- 总览 ----------

    def test_overview_counts_only_records_that_still_exist(self):
        with main.db() as conn:
            keep = self.a_study_record(conn, "留着")
            gone = self.a_study_record(conn, "删掉")
            tags.attach_tag(conn, name="考研", module="study", record_id=keep["id"])
            tags.attach_tag(conn, name="考研", module="study", record_id=gone["id"])
            conn.execute("DELETE FROM study_sessions WHERE id = ?", (gone["id"],))
            overview = tag_view.get_tag_overview(conn)

        entry = next(item for item in overview["tags"] if item["name"] == "考研")
        self.assertEqual(entry["total"], 1)
        self.assertEqual(entry["dead_links"], 1)

    def test_raw_state_counts_links_and_says_so(self):
        with main.db() as conn:
            record = self.a_study_record(conn)
            tags.attach_tag(conn, name="考研", module="study", record_id=record["id"])
            conn.execute("DELETE FROM study_sessions WHERE id = ?", (record["id"],))
            state = tags.get_tags_state(conn)

        self.assertEqual(state["tags"][0]["link_count"], 1)
        self.assertIn("不保证目标记录仍然存在", state["note"])

    def test_every_taggable_module_can_be_resolved(self):
        """可贴标签的模块与解析规则必须一一对应，少一条就会静默变成死链。"""
        self.assertEqual(set(tags.TAGGABLE_MODULES), set(tag_view._SOURCES))


if __name__ == "__main__":
    unittest.main()

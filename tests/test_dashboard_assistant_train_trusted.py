from __future__ import annotations

import unittest

from dashboard.routes.assistant import (
    _MAX_TRAIN_TRUSTED_USERS,
    _parse_train_trusted_user_ids,
    _serialize_train_trusted_user_ids,
)


class DashboardTrainTrustedParseTests(unittest.TestCase):
    def test_parse_empty(self) -> None:
        self.assertEqual(_parse_train_trusted_user_ids(""), set())
        self.assertEqual(_parse_train_trusted_user_ids(None), set())

    def test_parse_and_serialize_roundtrip(self) -> None:
        raw = " 1 , 2 , x , 2 , 918427390719234161 "
        ids = _parse_train_trusted_user_ids(raw)
        self.assertEqual(ids, {1, 2, 918427390719234161})
        self.assertEqual(_parse_train_trusted_user_ids(_serialize_train_trusted_user_ids(ids)), ids)

    def test_max_constant_matches_bot(self) -> None:
        self.assertEqual(_MAX_TRAIN_TRUSTED_USERS, 50)


if __name__ == "__main__":
    unittest.main()

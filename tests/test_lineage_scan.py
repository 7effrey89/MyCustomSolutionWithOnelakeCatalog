import unittest
from unittest.mock import Mock, patch

import explorer
from fabric_client import AppError, Asset


ASSET = Asset("item", "Lake", "Lakehouse", "workspace", "Workspace", "")


class ScanCleanupTests(unittest.TestCase):
    def test_completed_scan_cleanup_is_idempotent(self):
        for status in ("Succeeded", "Failed"):
            for replacement in (None, "newer-scan"):
                with self.subTest(status=status, replacement=replacement):
                    state = {}
                    details = Mock()
                    details.start_lineage_scan.return_value = "scan"

                    def finish(_):
                        pending = state["explorer_pending_scans"]
                        pending.pop(ASSET.workspace_id)
                        if replacement:
                            pending[ASSET.workspace_id] = replacement
                        return {"status": status, "error": "Scan failed"}

                    details.scan_status.side_effect = finish
                    details.scan_result.return_value = {"workspaces": []}
                    with patch.object(explorer.st, "session_state", state):
                        if status == "Succeeded":
                            self.assertEqual(explorer.scan_lineage(details, ASSET), {"workspaces": []})
                        else:
                            with self.assertRaisesRegex(AppError, "Scan failed"):
                                explorer.scan_lineage(details, ASSET)
                    self.assertEqual(state["explorer_pending_scans"].get(ASSET.workspace_id), replacement)

    def test_result_fetch_failure_keeps_scan_for_retry(self):
        state = {}
        details = Mock()
        details.start_lineage_scan.return_value = "scan"
        details.scan_status.return_value = {"status": "Succeeded"}
        details.scan_result.side_effect = AppError("Result unavailable")
        with patch.object(explorer.st, "session_state", state):
            with self.assertRaisesRegex(AppError, "Result unavailable"):
                explorer.scan_lineage(details, ASSET)
        self.assertEqual(state["explorer_pending_scans"], {"workspace": "scan"})

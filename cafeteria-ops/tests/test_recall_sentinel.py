import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.recall_sentinel import recall_sentinel_agent as rs
from agents.recall_sentinel.recall_sentinel_agent import (
    RecallSentinelAgent,
    find_watched_ingredients,
    relevant_recalls,
)

SENTINEL_URL = "http://127.0.0.1:8308/"
MENU_DESIGNER_URL = "http://127.0.0.1:8301/"
CONVENER_URL = "http://127.0.0.1:8300/"
HUMAN_URI = "openFloor://localhost:8090/CafeteriaOpsLineCheck"


def recall(number, product, reason, classification="Class I", report_date="20260819"):
    return {"recall_number": number, "classification": classification, "status": "Ongoing",
            "report_date": report_date, "product": product, "reason": reason,
            "firm": "Taylor Farms", "distribution": "Nationwide"}


LETTUCE_RECALL = recall("H-1286-2026", 'SHRED LETTUCE 1/8" 4/5# Iceberg only products', "Potential Cyclospora contamination.")
SALSA_RECALL = recall("H-1379-2026", "PICO DE GALLO-HOT-6/9oz", "Jalapenos have the potential to be contaminated with Salmonella")

GUANCIALE_RECALL = {
    "agency": "FSIS", "recall_number": "019-020-2026", "classification": "Class I", "status": "Active Recall",
    "report_date": "20260906", "product": "Imported Ready-To-Eat Pork Guanciale Products",
    "reason": "Possible Listeria Contamination (Product Contamination)", "firm": "Prime Line Distributors",
    "distribution": "Nationwide", "snapshot_saved": "2026-11-12",
}

# What the food_recalls MCP server returns, per tool and searched term.
FAKE_RESULTS = {
    "search_food_recalls": {"lettuce": [LETTUCE_RECALL], "iceberg": [LETTUCE_RECALL], "jalapeno": [SALSA_RECALL]},
    "search_fsis_recalls": {"pork": [GUANCIALE_RECALL], "guanciale": [GUANCIALE_RECALL]},
}


def fake_lookups(requests, timeout=None):
    return [json.dumps({"term": args["term"], "results": FAKE_RESULTS[tool].get(args["term"], [])}) for _, tool, args in requests]


class FindWatchedIngredientsTests(unittest.TestCase):
    def test_plurals_accents_and_multiword_names(self):
        found = find_watched_ingredients("Tuesday: tacos with jalapeños, fresh strawberries and pico de gallo")
        self.assertIn("jalapeno", found)
        self.assertIn("strawberry", found)
        self.assertIn("pico de gallo", found)

    def test_longer_name_wins(self):
        found = find_watched_ingredients("Friday: cottage cheese pancakes")
        self.assertIn("cottage cheese", found)
        self.assertNotIn("cheese", found)

    def test_reports_the_dish_clause(self):
        found = find_watched_ingredients("Monday: Chicken tacos with shredded lettuce, black beans")
        self.assertEqual(found["lettuce"], "Monday: Chicken tacos with shredded lettuce")


class RelevantRecallsTests(unittest.TestCase):
    def test_ingredient_named_in_the_reason_counts(self):
        self.assertEqual(relevant_recalls("jalapeno", [SALSA_RECALL]), [SALSA_RECALL])

    def test_ingredient_that_is_the_product_counts(self):
        self.assertEqual(relevant_recalls("lettuce", [LETTUCE_RECALL]), [LETTUCE_RECALL])

    def test_ingredient_only_in_the_ingredient_list_does_not_count(self):
        kit = recall("H-1", "Chef Salad Kit. Ingredients: Iceberg lettuce, cucumber, cheese", "Potential contamination with Salmonella.")
        self.assertEqual(relevant_recalls("cucumber", [kit]), [])

    def test_a_component_of_the_product_does_not_count(self):
        salad = recall("H-2", "Fiesta Salad with Shrimp", "Potential contamination with Salmonella")
        self.assertEqual(relevant_recalls("shrimp", [salad]), [])

    def test_a_product_without_the_ingredient_does_not_count(self):
        dip = recall("H-5", "Whole Foods Mild Guacamole Dip No Tomatoes, Keep Refrigerated", "Potential contamination with Salmonella")
        self.assertEqual(relevant_recalls("tomato", [dip]), [])

    def test_an_ingredient_the_product_merely_contains_does_not_count(self):
        mix = recall("H-6", "Everything Sprouts Zesty Garlic Mix, containing Garlic, Onion and Alfalfa", "STEC E. coli contamination")
        self.assertEqual(relevant_recalls("onion", [mix]), [])

    def test_labeling_and_foreign_object_recalls_do_not_count(self):
        label = recall("H-3", "Cheddar Cheese Snack Pack", "Undeclared milk", classification="Class II")
        metal = recall("H-4", "Strawberry Ice Cream", "Foreign object: may contain pieces of metal", classification="Class II")
        self.assertEqual(relevant_recalls("cheese", [label]), [])
        self.assertEqual(relevant_recalls("strawberry", [metal]), [])


class EnvelopeTests(unittest.TestCase):
    """End to end through handle_json_envelope, the way the floor manager
    delivers events, with the recall lookups faked."""

    TO_ME = {"speakerUri": SENTINEL_URL, "serviceUrl": SENTINEL_URL}

    def setUp(self):
        self.agent = RecallSentinelAgent()
        patcher = patch.object(rs.mcp_client, "call_tools_parallel_sync", side_effect=fake_lookups)
        self.lookups = patcher.start()
        self.addCleanup(patcher.stop)

    def _send(self, events, conversants=(SENTINEL_URL, MENU_DESIGNER_URL, CONVENER_URL)):
        envelope = {"openFloor": {
            "schema": {"version": "1.1"},
            "conversation": {"id": "conv-recall", "conversants": [
                {"identification": {"speakerUri": url, "serviceUrl": url, "conversationalName": "", "organization": "", "synopsis": ""}}
                for url in conversants
            ]},
            "sender": {"speakerUri": "tag:web-floor,2026:floor-manager"},
            "events": events,
        }}
        out = json.loads(self.agent.handle_json_envelope(json.dumps(envelope)))
        return out["openFloor"].get("events") or []

    @staticmethod
    def _utterance(speaker_uri, text):
        return {"eventType": "utterance", "parameters": {"dialogEvent": {
            "speakerUri": speaker_uri, "features": {"text": {"mimeType": "text/plain", "tokens": [{"value": text}]}}}}}

    @staticmethod
    def _texts(events):
        return [e["parameters"]["dialogEvent"]["features"]["text"]["tokens"][0]["value"]
                for e in events if e.get("eventType") == "utterance"]

    def _grant(self):
        return self._send([{"eventType": "grantFloor", "to": self.TO_ME}])

    def test_invite_is_accepted_with_a_short_greeting(self):
        events = self._send([{"eventType": "invite", "to": {"serviceUrl": SENTINEL_URL}}])
        self.assertIn("acceptInvite", [e["eventType"] for e in events])
        self.assertIn("Recall Sentinel on watch", self._texts(events)[0])

    def test_a_recalled_ingredient_requests_the_floor_with_an_issue_token(self):
        events = self._send([self._utterance(MENU_DESIGNER_URL, "Monday: Chicken tacos with shredded lettuce")])
        self.assertEqual([e["eventType"] for e in events], ["requestFloor"])
        self.assertEqual(events[0]["reason"], "@issueDetected active FDA recalls involve lettuce")
        self.assertEqual(events[0]["to"]["speakerUri"], SENTINEL_URL)

    def test_grant_releases_the_alert_with_recall_details(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Monday: Chicken tacos with shredded iceberg lettuce")])
        alert = self._texts(self._grant())[0]
        self.assertTrue(alert.startswith("Food recall alert:"))
        self.assertIn("Check your supplier's brand and lot", alert)
        # lettuce and iceberg found the same recall: listed once, one entry
        self.assertEqual(alert.count("H-1286-2026"), 1)
        self.assertEqual(alert.count("-- on the menu in"), 1)
        self.assertIn("Cyclospora", alert)

    def test_the_alert_has_an_html_version_with_the_ingredients_in_bold(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Monday: Chicken tacos with shredded iceberg lettuce")])
        features = self._grant()[0]["parameters"]["dialogEvent"]["features"]
        html = features["html"]["tokens"][0]["value"]
        self.assertEqual(features["html"]["mimeType"], "text/html")
        self.assertIn("-- on the menu in", html)
        self.assertIn("<b>Lettuce</b> -- on the menu in", html)
        self.assertIn("iceberg <b>lettuce</b>", html)  # in the dish, any case
        self.assertIn("SHRED <b>LETTUCE</b>", html)  # and in the recalled product
        self.assertNotIn("<b>Chicken</b>", html)  # not recalled, not bold
        self.assertNotIn("<b>", features["text"]["tokens"][0]["value"])

    def test_every_ingredient_in_a_dish_gets_a_recall_shown(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Tuesday: Tacos with shredded lettuce and jalapenos")])
        alert = self._texts(self._grant())[0]
        self.assertIn("H-1286-2026", alert)  # lettuce
        self.assertIn("H-1379-2026", alert)  # jalapeno

    def test_fsis_recalls_are_labelled_with_their_agency_and_snapshot_date(self):
        events = self._send([self._utterance(MENU_DESIGNER_URL, "Wednesday: Pasta carbonara with pork guanciale")])
        self.assertIn("USDA FSIS", events[0]["reason"])
        alert = self._texts(self._grant())[0]
        self.assertIn("FSIS Class I recall 019-020-2026", alert)
        self.assertIn("copy saved 2026-11-12", alert)
        self.assertEqual(alert.count("019-020-2026"), 1)  # pork and guanciale found the same recall

    def test_both_agencies_are_searched_for_every_ingredient(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Monday: Tacos with lettuce")])
        tools = sorted(tool for _, tool, _ in self.lookups.call_args.args[0])
        self.assertEqual(tools, ["search_food_recalls", "search_fsis_recalls"])

    def test_declined_revoke_drops_the_alert(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Monday: Tacos with lettuce")])
        self._send([{"eventType": "revokeFloor", "to": self.TO_ME, "reason": "declined: no"}])
        self.assertEqual(self._grant(), [])

    def test_silent_when_no_recall_matches(self):
        events = self._send([self._utterance(MENU_DESIGNER_URL, "Monday: Grilled chicken with basil")])
        self.assertEqual(events, [])

    def test_request_and_convener_are_never_checked(self):
        self._send([self._utterance(HUMAN_URI, "Plan tacos with lettuce")])
        self._send([self._utterance(CONVENER_URL, "Plan tacos with lettuce")])
        self.lookups.assert_not_called()

    def test_each_ingredient_and_recall_is_reported_once(self):
        self._send([self._utterance(MENU_DESIGNER_URL, "Monday: Tacos with lettuce")])
        self._grant()
        self.assertEqual(self._send([self._utterance(MENU_DESIGNER_URL, "Tuesday: Lettuce wraps")]), [])
        self.assertEqual(self.lookups.call_count, 1)  # lettuce isn't looked up again

    def test_another_sentinels_alert_is_not_rechecked(self):
        allergy_alert = "Allergy alert: these items contain severe allergens.\nTree nuts: Tacos with lettuce and pesto (pesto)"
        self.assertEqual(self._send([self._utterance("http://127.0.0.1:8307/", allergy_alert)]), [])
        self.lookups.assert_not_called()

    def test_lookup_failure_is_silent(self):
        self.lookups.side_effect = lambda requests, timeout=None: [json.dumps({"error": "openFDA returned 500"}) for _ in requests]
        self.assertEqual(self._send([self._utterance(MENU_DESIGNER_URL, "Monday: Tacos with lettuce")]), [])


class FsisSnapshotSearchTests(unittest.TestCase):
    """search_fsis_recalls over a saved copy of FSIS's recall API JSON."""

    def _search(self, term, records):
        import asyncio
        import importlib
        import os
        import tempfile
        sys.path.insert(0, str(ROOT / "mcp"))
        import food_recalls_mcp
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "fsis.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(records, f)
            with patch.object(food_recalls_mcp, "FSIS_RECALLS_FILE", path):
                return json.loads(asyncio.run(food_recalls_mcp.search_fsis_recalls(term)))

    @staticmethod
    def _record(title, recall_type="Active Recall", lang="English", date_offset_days=10, items=None):
        from datetime import date, timedelta
        return {"field_title": title, "field_recall_type": recall_type, "langcode": lang,
                "field_recall_date": (date.today() - timedelta(days=date_offset_days)).isoformat(),
                "field_recall_number": "001-2026", "field_recall_classification": "Class I",
                "field_recall_reason": ["Product Contamination"], "field_archive_recall": "False",
                "field_product_items": items or [], "field_states": ["Nationwide"], "field_establishment": ""}

    def test_parses_product_and_hazard_from_the_title_including_two_firm_titles(self):
        d = self._search("pork", [self._record(
            "Prime Line Distributors, Inc. and Ferrarini USA, Inc. Recall Imported Ready-To-Eat Pork Guanciale Products Due to Possible Listeria Contamination")])
        r = d["results"][0]
        self.assertEqual(r["product"], "Imported Ready-To-Eat Pork Guanciale Products")
        self.assertEqual(r["reason"], "Possible Listeria Contamination (Product Contamination)")
        self.assertEqual(r["agency"], "FSIS")
        self.assertIn("snapshot", d["source"])

    def test_only_open_recent_english_records(self):
        records = [
            self._record("A Recalls Chicken Products Due to Possible Listeria Contamination", recall_type="Closed Recall"),
            self._record("B Recalls Chicken Products Due to Possible Listeria Contamination", lang="Spanish"),
            self._record("C Recalls Chicken Products Due to Possible Listeria Contamination", date_offset_days=200),
            self._record("D Recalls Chicken Products Due to Possible Listeria Contamination"),
        ]
        d = self._search("chicken", records)
        self.assertEqual([r["firm"] for r in d["results"]], ["D"])

    def test_missing_snapshot_is_an_empty_result_not_an_error(self):
        import asyncio
        sys.path.insert(0, str(ROOT / "mcp"))
        import food_recalls_mcp
        with patch.object(food_recalls_mcp, "FSIS_RECALLS_FILE", str(ROOT / "no-such-file.json")):
            d = json.loads(asyncio.run(food_recalls_mcp.search_fsis_recalls("chicken")))
        self.assertEqual(d["results"], [])
        self.assertNotIn("error", d)


if __name__ == "__main__":
    unittest.main()
